"""NBA minutes + per-minute rate models, same design as the EuroLeague model.
Split by season (start year): train 2016-2023, validation 2024-25, test 2025-26 + 2026-27 to date.
Tests whether schedule features (rest, back-to-back, travel, time zones) add accuracy."""
import json
import pickle

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

D = "/home/claude/nba/"
rng = np.random.default_rng(7)
df = pd.read_parquet(D + "nba_dataset.parquet")
df = df[df["min"] > 0].copy()
df["min"] = df["min"].clip(upper=58)

MBASE = ["is_home", "playoff", "min_last1", "min_avg3", "min_avg5", "min_avg10", "min_std5", "season_games",
         "season_min_avg", "start_rate_season", "start_rate5", "last_start", "career_games", "prev_season_min",
         "days_since_last", "min_trend", "net10", "opp_net10", "exp_margin", "abs_exp_margin",
         "team_min_available", "teammate_min_share", "missing_min"]
SCHED = ["days_rest", "b2b", "g_last4", "g_last7", "travel_km", "tz_shift", "away_streak", "opp_days_rest", "opp_b2b"]
train, valid, test = df[df.season <= 2023], df[df.season == 2024], df[df.season >= 2025].copy()
P = dict(learning_rate=0.03, num_leaves=63, min_data_in_leaf=200, feature_fraction=0.8, bagging_fraction=0.8,
         bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=0)


def fit(feats, y="min", objective="regression_l1", alpha=None, offset=False):
    p = dict(P, objective=objective, **({"alpha": alpha} if alpha else {}))
    kw = lambda d: dict(init_score=np.log(d["min"])) if offset else {}
    dtr = lgb.Dataset(train[feats], train[y], **kw(train))
    dva = lgb.Dataset(valid[feats], valid[y], **kw(valid))
    return lgb.train(p, dtr, 4000, valid_sets=[dva], callbacks=[lgb.early_stopping(150, verbose=False)])


def mm(y, p):
    e = y - p
    return {"MAE": round(float(np.mean(np.abs(e))), 3), "within_3min": round(float(np.mean(np.abs(e) <= 3)), 3)}


rep = {"rows": {"train": len(train), "valid": len(valid), "test": len(test)}, "minutes": {}}
base = lambda d: d.min_avg5.fillna(d.season_min_avg).fillna(d.prev_season_min).fillna(train["min"].median())
rep["minutes"]["baseline last-5 average"] = mm(test["min"], base(test))
m0, m1 = fit(MBASE), fit(MBASE + SCHED)
test["p0"], test["p1"] = m0.predict(test[MBASE]), m1.predict(test[MBASE + SCHED])
rep["minutes"]["model without schedule"] = mm(test["min"], test.p0)
rep["minutes"]["model with schedule"] = mm(test["min"], test.p1)
seg = {"back-to-back": test.b2b == 1, "3+ games in 4 days... (g_last4>=2)": test.g_last4 >= 2,
       "travel > 2000 km": test.travel_km > 2000, "big expected margin (>10)": test.abs_exp_margin > 10,
       "teammates missing >= 25 min": test.missing_min >= 25}
rep["minutes_segments"] = {k: {"n": int(v.sum()), "MAE without": mm(test["min"][v], test.p0[v])["MAE"],
                               "MAE with": mm(test["min"][v], test.p1[v])["MAE"]} for k, v in seg.items()}
use_sched = rep["minutes"]["model with schedule"]["MAE"] < rep["minutes"]["model without schedule"]["MAE"] - 0.005
MF = MBASE + SCHED if use_sched else MBASE
mmed = m1 if use_sched else m0
q10, q90 = fit(MF, objective="quantile", alpha=0.1), fit(MF, objective="quantile", alpha=0.9)
for d in (valid, test):
    d["m_median"], d["m_q10"], d["m_q90"] = mmed.predict(d[MF]), q10.predict(d[MF]), q90.predict(d[MF])
rep["minutes"]["chosen"] = "with schedule" if use_sched else "without schedule"
rep["minutes"]["10-90 coverage"] = round(float(((test["min"] >= test.m_q10) & (test["min"] <= test.m_q90)).mean()), 3)
for m, n in ((mmed, "median"), (q10, "q10"), (q90, "q90")):
    m.save_model(D + f"nba_minutes_{n}.txt")

# ---------------- rate models
CTX = ["is_home", "playoff", "start_rate_season", "start_rate5", "min_avg5", "season_min_avg", "prev_season_min",
       "exp_margin", "abs_exp_margin", "teammate_min_share", "missing_min", "exp_pace", "career_games",
       "days_rest", "b2b"]
STATS = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "3-pointers made"}
RATE = [c for c in df.columns if c.startswith("r_")] + ["usage_15"]
rep.update(stat_given_minutes={}, dispersion_k={}, probabilities={})
calib = {}
for s in STATS:
    feats = RATE + [f"opp_allow_{s}"] + CTX
    m = fit(feats, y=s, objective="poisson", offset=True)
    m.save_model(D + f"nba_rate_{s}.txt")
    lam = lambda d, mins: np.exp(m.predict(d[feats], raw_score=True) + np.log(np.clip(mins, 0.5, None)))
    league = train[s].sum() / train["min"].sum()
    br = lambda d: d[f"r_{s}_60"].fillna(d[f"r_{s}_15"]).fillna(league)
    y = test[s].to_numpy()
    rep["stat_given_minutes"][STATS[s]] = {"MAE model": round(float(np.mean(np.abs(y - lam(test, test["min"])))), 3),
                                           "MAE naive": round(float(np.mean(np.abs(y - br(test) * test["min"]))), 3)}
    lv, yv = lam(valid, valid["min"]), valid[s].to_numpy()
    ex = np.sum((yv - lv) ** 2 - lv)
    k = float(np.sum(lv ** 2) / ex) if ex > 0 else 1e6
    rep["dispersion_k"][STATS[s]] = round(k, 2)

    def sim(d, line, N=2000):
        sd = np.clip((d.m_q90.to_numpy() - d.m_q10.to_numpy()) / 2.563, 1.0, None)
        mins = np.clip(d.m_median.to_numpy()[:, None] + sd[:, None] * rng.standard_normal((len(d), N)), 1, 48)
        l = np.exp(m.predict(d[feats], raw_score=True)[:, None] + np.log(mins))
        x = rng.negative_binomial(k, k / (k + l)) if k < 1e5 else rng.poisson(l)
        return np.clip((x > line[:, None]).mean(1), 0.005, 0.995)

    nm = lambda d: (br(d) * d.season_min_avg.fillna(d.min_avg5).fillna(d.prev_season_min).fillna(train["min"].mean())).to_numpy()
    vline = np.floor(nm(valid)) + 0.5
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(sim(valid, vline), (valid[s].to_numpy() > vline).astype(int))
    calib[s] = {"iso": iso, "k": k}
    line = np.floor(nm(test)) + 0.5
    over = (y > line).astype(int)
    p = np.clip(iso.predict(sim(test, line)), 0.01, 0.99)
    bm = nm(test)
    pb = np.clip(1 - np.array([(rng.negative_binomial(k, k / (k + mu), 3000) <= l).mean() for mu, l in zip(bm, line)]), .01, .99)
    rep["probabilities"][STATS[s]] = {"n": int(len(test)), "Brier model": round(float(np.mean((p - over) ** 2)), 4),
                                      "Brier naive": round(float(np.mean((pb - over) ** 2)), 4)}

pickle.dump(calib, open(D + "nba_calibration.pkl", "wb"))
json.dump({"MF": MF, "CTX": CTX, "RATE": RATE}, open(D + "nba_features.json", "w"))
imp = pd.Series(mmed.feature_importance("gain"), index=MF)
rep["minutes_top_features"] = (imp / imp.sum()).sort_values(ascending=False).round(3).head(12).to_dict()
json.dump(rep, open(D + "nba_report.json", "w"), indent=1)
print(json.dumps(rep, indent=1))
