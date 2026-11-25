"""Train and evaluate the EuroLeague minutes model.

Target: minutes played, for players who got on the court (prop bets void on DNP).
Split by time: train 2016-17..2023-24, validation 2024-25, test 2025-26 + 2026-27 to date.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

df = pd.read_parquet("/home/claude/model/minutes_dataset.parquet")
df = df[df.minutes > 0].copy()
df["round"] = pd.to_numeric(df["round"], errors="coerce")

BASE = ["home", "playoff", "round", "el_last1", "el_avg3", "el_avg5", "el_avg10", "el_std5",
        "el_games_career", "prev_season_avg", "season_games", "season_avg", "season_start_rate",
        "start_rate5", "last_start", "trend", "team_net10", "opp_net10", "exp_margin",
        "abs_exp_margin", "team_min_available", "teammate_min_share", "days_since_el"]
FATIGUE = ["days_since_any", "min_last3d", "min_last7d", "games_last7d", "min_last14d",
           "dom_avg5", "dom_games_last7d", "has_dom_data"]

train = df[df.Season <= 2023]
valid = df[df.Season == 2024]
test = df[df.Season >= 2025]


def fit(features, objective="regression_l1", alpha=None, seed=0):
    params = dict(objective=objective, learning_rate=0.03, num_leaves=31, min_data_in_leaf=80,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
                  verbose=-1, seed=seed)
    if alpha is not None:
        params["alpha"] = alpha
    dtr = lgb.Dataset(train[features], train.minutes)
    dva = lgb.Dataset(valid[features], valid.minutes)
    m = lgb.train(params, dtr, num_boost_round=3000, valid_sets=[dva],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
    return m


def metrics(y, p):
    e = y - p
    return {"MAE": round(float(np.mean(np.abs(e))), 3), "RMSE": round(float(np.sqrt(np.mean(e ** 2))), 3),
            "within_3min": round(float(np.mean(np.abs(e) <= 3)), 3)}


def baseline(d):
    return d.el_avg5.fillna(d.season_avg).fillna(d.prev_season_avg).fillna(df.minutes.median())


results = {}
for name, data in (("valid 2024-25", valid), ("test 2025-27", test)):
    results[name] = {"baseline: last-5 average": metrics(data.minutes, baseline(data)),
                     "baseline: season average": metrics(
                         data.minutes, data.season_avg.fillna(data.prev_season_avg).fillna(baseline(data)))}

m_base = fit(BASE)
m_full = fit(BASE + FATIGUE)
for name, data in (("valid 2024-25", valid), ("test 2025-27", test)):
    results[name]["model without fatigue features"] = metrics(data.minutes, m_base.predict(data[BASE]))
    results[name]["model with fatigue features"] = metrics(data.minutes, m_full.predict(data[BASE + FATIGUE]))

# where fatigue should matter most: players with domestic data, short rest
t = test.copy()
t["p_base"] = m_base.predict(t[BASE])
t["p_full"] = m_full.predict(t[BASE + FATIGUE])
segments = {
    "players with domestic data": t[t.has_dom_data == 1],
    "rest <= 3 days since last game (any comp)": t[t.days_since_any <= 3],
    "2+ games in previous 7 days": t[t.games_last7d >= 2],
    "first 5 EuroLeague games of season": t[t.season_games < 5],
}
seg = {k: {"n": int(len(v)), "MAE without fatigue": metrics(v.minutes, v.p_base)["MAE"],
           "MAE with fatigue": metrics(v.minutes, v.p_full)["MAE"]} for k, v in segments.items()}

# prediction intervals: 10th / 90th percentile models, checked for coverage on test
q10, q90 = fit(BASE + FATIGUE, "quantile", 0.1), fit(BASE + FATIGUE, "quantile", 0.9)
lo, hi = q10.predict(test[BASE + FATIGUE]), q90.predict(test[BASE + FATIGUE])
coverage = float(np.mean((test.minutes >= lo) & (test.minutes <= hi)))

imp = pd.Series(m_full.feature_importance("gain"), index=BASE + FATIGUE)
imp = (imp / imp.sum()).sort_values(ascending=False).round(3)

for m, n in ((m_full, "median"), (q10, "q10"), (q90, "q90")):
    m.save_model(f"/home/claude/model/minutes_{n}.txt")

report = {"rows": {"train": len(train), "valid": len(valid), "test": len(test)},
          "results": results, "segments_test": seg,
          "interval_10_90_coverage_test": round(coverage, 3),
          "avg_interval_width": round(float(np.mean(hi - lo)), 2),
          "top_features": imp.head(15).to_dict()}
json.dump(report, open("/home/claude/model/minutes_report.json", "w"), indent=2)
print(json.dumps(report, indent=2))
