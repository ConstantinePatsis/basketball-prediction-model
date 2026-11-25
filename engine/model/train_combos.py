"""Combination bets (P+R+A, P+R, P+A, R+A) and PIR.

Combos: points, rebounds and assists are simulated JOINTLY. They are linked through the shared
minutes draw, and additionally through a Gaussian copula fitted on the validation season
(captures e.g. big men whose points and rebounds rise together).
PIR (EuroLeague Performance Index Rating) can be negative, so it is modelled as a per-minute rate
(LightGBM, weighted by minutes) with a normal spread whose variance grows with minutes.
Split: train <=2023-24, validation 2024-25 (spread, copula, calibration), test 2025-26 + 2026-27.
"""
import bisect
import json
import pickle
import sqlite3
from collections import defaultdict

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import nbinom, norm
from sklearn.isotonic import IsotonicRegression

rng = np.random.default_rng(21)
M = "/home/claude/model"
N = 1000
df = pd.read_parquet(f"{M}/rates_dataset.parquet")
df["round"] = pd.to_numeric(df["round"], errors="coerce")
df["starter_rate"] = df.season_start_rate

# ---------------- PIR outcome + PIR rate history ----------------
con = sqlite3.connect("/home/claude/basketball.db")
g = pd.read_sql("SELECT Season, gameCode, date FROM el_games", con)
g["gameCode"] = g.gameCode.astype(int)
g["date"] = pd.to_datetime(g.date, format="%b %d, %Y")
eb = pd.read_sql("SELECT Season, Gamecode, Player_ID, Minutes_float AS minutes, Valuation AS pir FROM el_box", con)
eb = eb.merge(g, left_on=["Season", "Gamecode"], right_on=["Season", "gameCode"])
dg = pd.read_sql("SELECT league, season, game_id, date FROM dom_games", con)
dbx = pd.read_sql("SELECT league, season, game_id, el_player_id AS Player_ID, minutes, rating AS pir "
                  "FROM dom_box WHERE el_player_id IS NOT NULL", con)
dbx = dbx.merge(dg, on=["league", "season", "game_id"])
dbx["date"] = pd.to_datetime(dbx.date, errors="coerce")
dbx["pir"] = pd.to_numeric(dbx.pir, errors="coerce")
dbx = dbx.dropna(subset=["date", "pir"])

hist = defaultdict(dict)
for src, d in (("EL", eb[eb.minutes.notna()]), ("DOM", dbx)):
    for pid, grp in d.sort_values("date").groupby("Player_ID"):
        hist[pid][src] = (grp.date.values.astype("datetime64[D]").astype(np.int64).tolist(),
                          grp[["minutes", "pir"]].to_numpy(float))


def pir_rate(pid, day, src, n):
    e = hist.get(pid, {}).get(src)
    if not e:
        return np.nan
    i = bisect.bisect_left(e[0], day)
    w = e[1][max(0, i - n):i]
    return w[:, 1].sum() / w[:, 0].sum() if len(w) and w[:, 0].sum() >= 1 else np.nan


day = df.date.values.astype("datetime64[D]").astype(np.int64)
for src, n, tag in (("EL", 5, "el5"), ("EL", 15, "el15"), ("EL", 60, "el60"), ("DOM", 10, "dom10")):
    df[f"r_pir_{tag}"] = [pir_rate(p, d, src, n) for p, d in zip(df.Player_ID, day)]
df = df.merge(eb[["Season", "Gamecode", "Player_ID", "pir"]].rename(columns={"pir": "y_pir"}),
              on=["Season", "Gamecode", "Player_ID"], how="left")
df.to_parquet(f"{M}/rates_dataset_pir.parquet", index=False)

df = df[df.minutes > 0].copy()
MIN_FEATS = lgb.Booster(model_file=f"{M}/minutes_median.txt").feature_name()
for n_ in ("median", "q10", "q90"):
    df[f"m_{n_}"] = lgb.Booster(model_file=f"{M}/minutes_{n_}.txt").predict(df[MIN_FEATS])
train, valid, test = df[df.Season <= 2023], df[df.Season == 2024].copy(), df[df.Season >= 2025].copy()
calib = pickle.load(open(f"{M}/calibration.pkl", "rb"))
rate_models = {s: lgb.Booster(model_file=f"{M}/rate_{s}.txt") for s in ("pts", "reb", "ast")}

# ---------------- PIR model ----------------
CTX = ["home", "playoff", "starter_rate", "start_rate5", "el_avg5", "season_avg", "prev_season_avg",
       "exp_margin", "abs_exp_margin", "teammate_min_share", "team_total10", "has_dom_data",
       "el_games_career", "days_since_any", "min_last7d"]
RATE = [c for c in df.columns if c.startswith("r_")] + ["min_el5", "min_el15", "min_el60", "min_dom10"]
PIR_FEATS = RATE + CTX + [f"opp_allow_{s}" for s in ("pts", "reb", "ast")]
tr = train.dropna(subset=["y_pir"])
va = valid.dropna(subset=["y_pir"])
pir_m = lgb.train(dict(objective="regression", learning_rate=0.03, num_leaves=31, min_data_in_leaf=100,
                       feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=3),
                  lgb.Dataset(tr[PIR_FEATS], tr.y_pir / tr.minutes, weight=tr.minutes),
                  3000, valid_sets=[lgb.Dataset(va[PIR_FEATS], va.y_pir / va.minutes, weight=va.minutes)],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
pir_m.save_model(f"{M}/rate_pir.txt")
# spread: residual variance = a * minutes + b   (fitted on validation, actual minutes)
res = va.y_pir - pir_m.predict(va[PIR_FEATS]) * va.minutes
A = np.vstack([va.minutes, np.ones(len(va))]).T
a_b = np.clip(np.linalg.lstsq(A, res ** 2, rcond=None)[0], [0.1, 0.0], None)

# ---------------- copula correlation (validation, actual minutes) ----------------
def lam(s, d, minutes):
    return np.exp(rate_models[s].predict(d[rate_models[s].feature_name()], raw_score=True)
                  + np.log(np.clip(minutes, 0.5, None)))


Z = []
for s in ("pts", "reb", "ast"):
    k, lv, y = calib[s]["k"], lam(s, valid, valid.minutes), valid[f"y_{s}"].to_numpy()
    p = k / (k + lv)
    lo, hi = nbinom.cdf(y - 1, k, p), nbinom.cdf(y, k, p)
    u = np.clip(lo + rng.random(len(y)) * (hi - lo), 1e-6, 1 - 1e-6)     # randomized PIT
    Z.append(norm.ppf(u))
CORR = np.corrcoef(np.vstack(Z))


# ---------------- joint simulation ----------------
def simulate(d, correlated=True):
    med, sd = d.m_median.to_numpy(), np.clip((d.m_q90 - d.m_q10).to_numpy() / 2.563, 1.0, None)
    smin = np.clip(med[:, None] + sd[:, None] * rng.standard_normal((len(d), N)), 1, 48)
    zz = rng.standard_normal((len(d), N, 3))
    if correlated:
        zz = zz @ np.linalg.cholesky(CORR).T
    out = {}
    for j, s in enumerate(("pts", "reb", "ast")):
        k = calib[s]["k"]
        raw = rate_models[s].predict(d[rate_models[s].feature_name()], raw_score=True)
        lm = np.exp(raw[:, None] + np.log(smin))
        out[s] = nbinom.ppf(norm.cdf(zz[:, :, j]), k, k / (k + lm))
    r = pir_m.predict(d[PIR_FEATS])
    out["pir"] = r[:, None] * smin + np.sqrt(a_b[0] * smin + a_b[1]) * rng.standard_normal(smin.shape)
    return out


COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
NAME = {"pra": "Points+Rebounds+Assists", "pr": "Points+Rebounds", "pa": "Points+Assists",
        "ra": "Rebounds+Assists", "pir": "PIR"}


def totals(sims):
    t = {c: sum(sims[s] for s in parts) for c, parts in COMBOS.items()}
    t["pir"] = sims["pir"]
    return t


def naive_mean(d, s):
    league = train[f"y_{s}"].sum() / train.minutes.sum()
    rate = d[f"r_{s}_el60"].fillna(d[f"r_{s}_el15"]).fillna(d[f"r_{s}_dom10"]).fillna(league)
    return (rate * d.season_avg.fillna(d.el_avg5).fillna(d.prev_season_avg).fillna(train.minutes.mean())).to_numpy()


def actual(d, c):
    return d.y_pir.to_numpy() if c == "pir" else sum(d[f"y_{s}"].to_numpy() for s in COMBOS[c])


def naive_p(d, c, line):
    """Naive: normal around the naive expectation with the model's typical spread."""
    mu = naive_mean(d, "pir") if c == "pir" else sum(naive_mean(d, s) for s in COMBOS[c])
    return mu, None


sv, st, st_ind = simulate(valid), simulate(test), simulate(test, correlated=False)
tv, tt, tt_ind = totals(sv), totals(st), totals(st_ind)
report = {"copula_correlation_pts_reb_ast": np.round(CORR, 3).tolist(),
          "pir_variance_per_minute": round(float(a_b[0]), 3), "results_test": {}, "calibration_test": {}}
calib_c = {"corr": CORR, "pir_ab": a_b, "pir_feats": PIR_FEATS}
for c in ["pra", "pr", "pa", "ra", "pir"]:
    vmask, tmask = ~np.isnan(actual(valid, c)), ~np.isnan(actual(test, c))
    vmu = (naive_mean(valid, "pir") if c == "pir" else sum(naive_mean(valid, s) for s in COMBOS[c]))
    tmu = (naive_mean(test, "pir") if c == "pir" else sum(naive_mean(test, s) for s in COMBOS[c]))
    vline, tline = np.floor(vmu) + 0.5, np.floor(tmu) + 0.5
    vover, tover = (actual(valid, c) > vline).astype(int), (actual(test, c) > tline).astype(int)
    pv = np.clip((tv[c] > vline[:, None]).mean(1), .005, .995)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=.01, y_max=.99).fit(pv[vmask], vover[vmask])
    calib_c[c] = iso
    p_raw = np.clip((tt[c] > tline[:, None]).mean(1), .005, .995)
    p_ind = np.clip((tt_ind[c] > tline[:, None]).mean(1), .005, .995)
    p_cal = np.clip(iso.predict(p_raw), .01, .99)
    # naive: same spread as the model's simulation, but centred on the naive expectation
    shift = tt[c].mean(1) - tmu
    p_naive = np.clip(((tt[c] - shift[:, None]) > tline[:, None]).mean(1), .01, .99)
    m, o = tmask, tover

    def brier(p):
        return round(float(np.mean((p[m] - o[m]) ** 2)), 4)

    report["results_test"][NAME[c]] = {
        "n": int(m.sum()), "over_rate": round(float(o[m].mean()), 3),
        "Brier model (calibrated)": brier(p_cal), "Brier model (raw)": brier(p_raw),
        "Brier if stats treated as independent": brier(p_ind) if c != "pir" else None,
        "Brier naive": brier(p_naive), "Brier coin-flip": 0.25,
        "MAE of mean": round(float(np.mean(np.abs(tt[c].mean(1)[m] - actual(test, c)[m]))), 2),
        "MAE naive": round(float(np.mean(np.abs(tmu[m] - actual(test, c)[m]))), 2)}
    bins = pd.cut(p_cal[m], [0, .3, .4, .45, .5, .55, .6, .7, 1.0])
    report["calibration_test"][NAME[c]] = (pd.DataFrame({"b": bins, "p": p_cal[m], "o": o[m]})
                                           .groupby("b", observed=True)
                                           .agg(n=("o", "size"), predicted=("p", "mean"), actual=("o", "mean"))
                                           .round(3).reset_index().astype({"b": str}).to_dict("records"))
pickle.dump(calib_c, open(f"{M}/calibration_combos.pkl", "wb"))
json.dump(report, open(f"{M}/combos_report.json", "w"), indent=1)
print(json.dumps({k: v for k, v in report.items() if k != "calibration_test"}, indent=1))
