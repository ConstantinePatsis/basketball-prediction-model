"""How much is knowing absences worth? Test seasons (2025+).
Informed  = availability features from the players who actually dressed (what a perfect injury report gives).
Naive     = roster guessed as 'everyone who played in the team's last 3 games' (what we had before)."""
import numpy as np, pandas as pd, lightgbm as lgb, json
df = pd.read_parquet("minutes_dataset.parquet").sort_values("date")
m = lgb.Booster(model_file="minutes_median.txt"); F = m.feature_name()
# each player's avg of last 5 EL minutes before each date
df["avg5_now"] = df.groupby("Player_ID").minutes.transform(lambda s: s.shift().rolling(5, 1).mean()).fillna(0)
df["round"] = pd.to_numeric(df["round"], errors="coerce")
test = df[df.Season >= 2025].copy()
games = df[["Season", "Team", "Gamecode", "date"]].drop_duplicates().sort_values("date")
played = df[df.minutes > 0].groupby(["Season", "Team", "Gamecode"]).Player_ID.apply(set).to_dict()
last_row = df.set_index(["Player_ID", "date"]).avg5_now   # latest avg before a date
hist = {pid: g[["date", "minutes"]].values for pid, g in df.groupby("Player_ID")}

def avg5_before(pid, day):
    h = hist[pid]; h = h[h[:, 0] < day][-5:, 1]
    return float(np.mean(h)) if len(h) else 0.0

rows = []
for (s, t), g in games[games.Season >= 2025].groupby(["Season", "Team"]):
    codes = list(g.Gamecode); dates = list(g.date)
    for i, (gc, day) in enumerate(zip(codes, dates)):
        if i < 3: continue
        naive = set().union(*[played.get((s, t, c), set()) for c in codes[i-3:i]])
        actual = played.get((s, t, gc), set())
        rows.append((s, t, gc, sum(avg5_before(p, day) for p in naive), len(naive - actual), len(actual - naive)))
nv = pd.DataFrame(rows, columns=["Season", "Team", "Gamecode", "tma_naive", "n_missing", "n_new"])
test = test.merge(nv, on=["Season", "Team", "Gamecode"])
test = test[test.minutes > 0]
test["pred_informed"] = m.predict(test[F])
X = test[F].copy(); X["team_min_available"] = test.tma_naive
X["teammate_min_share"] = test.el_avg5 / test.tma_naive.replace(0, np.nan)
test["pred_naive"] = m.predict(X)
ae = lambda c: (test[c] - test.minutes).abs()
out = {"players": len(test),
       "mae_naive": round(ae("pred_naive").mean(), 3), "mae_informed": round(ae("pred_informed").mean(), 3)}
aff = test.n_missing > 0
out["share_games_with_surprise_absence"] = round(aff.mean(), 3)
out["mae_naive_when_absence"] = round(ae("pred_naive")[aff].mean(), 3)
out["mae_informed_when_absence"] = round(ae("pred_informed")[aff].mean(), 3)
big = test.n_missing >= 2
out["mae_naive_2plus_absent"] = round(ae("pred_naive")[big].mean(), 3)
out["mae_informed_2plus_absent"] = round(ae("pred_informed")[big].mean(), 3)
out["avg_minutes_underpredicted_naive_when_absence"] = round((test.minutes - test.pred_naive)[aff].mean(), 2)
print(json.dumps(out, indent=1)); json.dump(out, open("absence_backtest.json", "w"), indent=1)
