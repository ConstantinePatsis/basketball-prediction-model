"""Per-minute stat models + over/under probability engine + evaluation.

1. Rate models: LightGBM Poisson on each stat with log(minutes) as offset, so the model learns a
   per-minute rate that scales with minutes.
2. Spread: negative binomial around the predicted mean (dispersion fitted on validation season).
3. Probabilities: Monte Carlo over the minutes model's predicted range (median + 10th/90th pct),
   then the stat distribution at each simulated minutes value -> P(over line).
Split: train 2016-17..2023-24, validation 2024-25, test 2025-26 + 2026-27 to date.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
df = pd.read_parquet("/home/claude/model/rates_dataset.parquet")
df = df[df.minutes > 0].copy()
df["round"] = pd.to_numeric(df["round"], errors="coerce")
STATS = ["pts", "reb", "ast", "fg3m"]
LABEL = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "3-pointers made"}

CTX = ["home", "playoff", "starter_rate", "season_start_rate", "start_rate5", "el_avg5", "season_avg",
       "prev_season_avg", "exp_margin", "abs_exp_margin", "teammate_min_share", "team_total10",
       "has_dom_data", "el_games_career", "days_since_any", "min_last7d"]
df["starter_rate"] = df.season_start_rate
RATE = [c for c in df.columns if c.startswith("r_") or c.startswith("min_el") or c == "min_dom10"]

# ---------------- minutes model predictions (median + range) ----------------
MIN_FEATS = ["home", "playoff", "round", "el_last1", "el_avg3", "el_avg5", "el_avg10", "el_std5",
             "el_games_career", "prev_season_avg", "season_games", "season_avg", "season_start_rate",
             "start_rate5", "last_start", "trend", "team_net10", "opp_net10", "exp_margin",
             "abs_exp_margin", "team_min_available", "teammate_min_share", "days_since_el",
             "days_since_any", "min_last3d", "min_last7d", "games_last7d", "min_last14d",
             "dom_avg5", "dom_games_last7d", "has_dom_data"]
mq = {n: lgb.Booster(model_file=f"/home/claude/model/minutes_{n}.txt") for n in ("median", "q10", "q90")}
for n, m in mq.items():
    df[f"m_{n}"] = m.predict(df[MIN_FEATS])

train, valid, test = df[df.Season <= 2023], df[df.Season == 2024], df[df.Season >= 2025].copy()


def baseline_rate(d, s):
    """Naive per-minute rate: season-scale EuroLeague rate, else domestic, else league average."""
    league = train[f"y_{s}"].sum() / train.minutes.sum()
    return d[f"r_{s}_el60"].fillna(d[f"r_{s}_el15"]).fillna(d[f"r_{s}_dom10"]).fillna(league)


report = {"stat_given_actual_minutes": {}, "dispersion_k": {}, "probabilities": {}, "calibration": {}}
models = {}
calib = {}
for s in STATS:
    feats = RATE + [f"opp_allow_{s}"] + CTX
    dtr = lgb.Dataset(train[feats], train[f"y_{s}"], init_score=np.log(train.minutes))
    dva = lgb.Dataset(valid[feats], valid[f"y_{s}"], init_score=np.log(valid.minutes))
    m = lgb.train(dict(objective="poisson", learning_rate=0.03, num_leaves=31, min_data_in_leaf=100,
                       feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=1),
                  dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(150, verbose=False)])
    models[s] = (m, feats)
    m.save_model(f"/home/claude/model/rate_{s}.txt")

    def lam(d, minutes):                      # predicted mean for given minutes
        return np.exp(m.predict(d[feats], raw_score=True) + np.log(np.clip(minutes, 0.5, None)))

    # --- accuracy when minutes are known (isolates the rate model) ---
    lt = lam(test, test.minutes)
    bt = baseline_rate(test, s) * test.minutes
    y = test[f"y_{s}"]
    report["stat_given_actual_minutes"][LABEL[s]] = {
        "MAE model": round(float(np.mean(np.abs(y - lt))), 3),
        "MAE naive rate x minutes": round(float(np.mean(np.abs(y - bt))), 3)}

    # --- negative binomial dispersion from validation (actual minutes) ---
    lv, yv = lam(valid, valid.minutes), valid[f"y_{s}"].to_numpy()
    excess = np.sum((yv - lv) ** 2 - lv)
    k = float(np.sum(lv ** 2) / excess) if excess > 0 else 1e6
    report["dispersion_k"][LABEL[s]] = round(k, 2)

    # --- full pipeline: simulate minutes, then stat (validation + test) ---
    def simulate(d, line):
        med, q10, q90 = d.m_median.to_numpy(), d.m_q10.to_numpy(), d.m_q90.to_numpy()
        sd = np.clip((q90 - q10) / 2.563, 1.0, None)
        N = 2000
        sims_min = np.clip(med[:, None] + sd[:, None] * rng.standard_normal((len(d), N)), 1, 48)
        lam_sim = np.exp(m.predict(d[feats], raw_score=True)[:, None] + np.log(sims_min))
        sims = rng.negative_binomial(k, k / (k + lam_sim)) if k < 1e5 else rng.poisson(lam_sim)
        return np.clip((sims > line[:, None]).mean(axis=1), 0.005, 0.995)

    def naive_mean(d):
        return (baseline_rate(d, s) * d.season_avg.fillna(d.el_avg5).fillna(d.prev_season_avg)
                .fillna(train.minutes.mean())).to_numpy()

    # "book-style" line: naive expectation rounded to x.5 (the most common prop-line format)
    base_mean = naive_mean(test)
    line = np.floor(base_mean) + 0.5
    over = (y.to_numpy() > line).astype(int)
    p_raw = simulate(test, line)

    # calibration fitted on the validation season only (isotonic regression)
    from sklearn.isotonic import IsotonicRegression
    vline = np.floor(naive_mean(valid)) + 0.5
    vover = (valid[f"y_{s}"].to_numpy() > vline).astype(int)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(simulate(valid, vline), vover)
    p_model = np.clip(iso.predict(p_raw), 0.01, 0.99)
    calib[s] = {'iso': iso, 'k': k}

    # naive comparison: negative binomial (same spread) around the naive expectation, no minutes model
    p_base = np.clip(1 - np.array([(rng.negative_binomial(k, k / (k + mu), 4000) <= l).mean()
                                   if k < 1e5 else (rng.poisson(mu, 4000) <= l).mean()
                                   for mu, l in zip(base_mean, line)]), 0.01, 0.99)

    def brier(p):
        return float(np.mean((p - over) ** 2))

    def logloss(p):
        return float(-np.mean(over * np.log(p) + (1 - over) * np.log(1 - p)))

    report["probabilities"][LABEL[s]] = {
        "n": int(len(test)), "actual over rate": round(float(over.mean()), 3),
        "Brier model (calibrated)": round(brier(p_model), 4), "Brier model (raw)": round(brier(p_raw), 4),
        "Brier naive": round(brier(p_base), 4),
        "Brier coin-flip": 0.25,
        "LogLoss model": round(logloss(p_model), 4), "LogLoss naive": round(logloss(p_base), 4)}

    bins = pd.cut(p_model, [0, .3, .4, .45, .5, .55, .6, .7, 1.0])
    cal = pd.DataFrame({"bin": bins, "p": p_model, "o": over}).groupby("bin", observed=True).agg(
        n=("o", "size"), predicted=("p", "mean"), actual=("o", "mean")).round(3)
    report["calibration"][LABEL[s]] = cal.reset_index().astype({"bin": str}).to_dict("records")

    test[f"p_over_{s}"], test[f"line_{s}"], test[f"over_{s}"] = p_model, line, over

test[["Season", "Gamecode", "date", "Player", "Team", "opp", "minutes", "m_median", "m_q10", "m_q90"]
     + [c for c in test.columns if c.startswith(("p_over_", "line_", "over_", "y_"))]].to_parquet(
    "/home/claude/model/test_predictions.parquet", index=False)
json.dump(report, open("/home/claude/model/rates_report.json", "w"), indent=2, default=str)
import pickle
pickle.dump(calib, open("/home/claude/model/calibration.pkl", "wb"))
print(json.dumps(report, indent=1, default=str))
