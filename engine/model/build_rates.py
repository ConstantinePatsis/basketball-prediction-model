"""Per-minute rate features for points, rebounds, assists, 3PM (prior games only).

Adds to the minutes dataset: actual stat outcomes + rolling per-minute rates from EuroLeague
and linked domestic games, a usage proxy, and opponent / pace context.
Output: /home/claude/model/rates_dataset.parquet
"""
import bisect
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd

con = sqlite3.connect("/home/claude/basketball.db")
STATS = ["pts", "reb", "ast", "fg3m"]

g = pd.read_sql("SELECT Season, gameCode, date, homecode, awaycode, homescore, awayscore FROM el_games", con)
g["gameCode"] = g.gameCode.astype(int)
g["date"] = pd.to_datetime(g.date, format="%b %d, %Y")
b = pd.read_sql("""SELECT Season, Gamecode, Home, Player_ID, Team, Minutes_float AS minutes,
                   Points AS pts, TotalRebounds AS reb, Assistances AS ast, FieldGoalsMade3 AS fg3m,
                   FieldGoalsAttempted2 + FieldGoalsAttempted3 AS fga, FreeThrowsAttempted AS fta,
                   Turnovers AS tov FROM el_box""", con)
import os
FUT = os.environ.get("FUTURE_DIR")
if FUT:
    fg = pd.read_parquet(f"{FUT}/future_games.parquet")
    fg["date"] = pd.to_datetime(fg.date, format="%b %d, %Y")
    g = pd.concat([g, fg], ignore_index=True)
    fb = pd.read_parquet(f"{FUT}/future_box.parquet").rename(columns={"Minutes_float": "minutes"})
    b = pd.concat([b, fb[["Season", "Gamecode", "Home", "Player_ID", "Team", "minutes"]]], ignore_index=True)
b = b.merge(g, left_on=["Season", "Gamecode"], right_on=["Season", "gameCode"])
b = b[~((b.Season == 2017) & (b.Gamecode == 14))]
b["usage"] = b.fga + 0.44 * b.fta + b.tov
b["opp"] = np.where(b.Home == 1, b.awaycode, b.homecode)

dg = pd.read_sql("SELECT league, season, game_id, date FROM dom_games", con)
db = pd.read_sql("""SELECT league, season, game_id, el_player_id AS Player_ID, minutes, points AS pts,
                    reb, ast, fg3m, COALESCE(fg2a,0)+COALESCE(fg3a,0) AS fga, COALESCE(fta,0) AS fta,
                    COALESCE(tov,0) AS tov FROM dom_box WHERE el_player_id IS NOT NULL""", con)
db = db.merge(dg, on=["league", "season", "game_id"])
db["date"] = pd.to_datetime(db.date, errors="coerce")
db = db.dropna(subset=["date"])
db["usage"] = db.fga + 0.44 * db.fta + db.tov

COLS = ["minutes"] + STATS + ["usage"]
hist = defaultdict(lambda: {"EL": None, "DOM": None})
for src, d in (("EL", b[b.minutes.notna()]), ("DOM", db)):
    d = d.sort_values("date")
    for pid, grp in d.groupby("Player_ID"):
        days = (grp.date.values.astype("datetime64[D]").astype(np.int64)).tolist()
        hist[pid][src] = (days, grp[COLS].fillna(0).to_numpy(dtype=float))


def rates(entry, day, n):
    if entry is None:
        return None
    days, arr = entry
    i = bisect.bisect_left(days, day)
    w = arr[max(0, i - n):i]
    if len(w) == 0 or w[:, 0].sum() < 1:
        return None
    return w[:, 1:].sum(axis=0) / w[:, 0].sum(), w[:, 0].sum()


# opponent context: per-minute stats ALLOWED by the opponent (rolling 10 games) and game pace
team_game = b.groupby(["Season", "Gamecode", "Team", "opp", "date"])[STATS].sum().reset_index()
allowed = team_game.rename(columns={"Team": "x", "opp": "Team"}).rename(columns={"x": "scorer"})
allowed = allowed.sort_values("date")
for s in STATS:
    allowed[f"opp_allow_{s}"] = allowed.groupby(["Season", "Team"])[s].transform(
        lambda x: x.shift().rolling(10, 1).mean())
allowed = allowed[["Season", "Gamecode", "Team"] + [f"opp_allow_{s}" for s in STATS]].rename(
    columns={"Team": "opp"})
tg = b.groupby(["Season", "Gamecode", "Team", "date"]).agg(team_pts=("homescore", "first")).reset_index()
gm = g.assign(total=g.homescore.astype(float) + g.awayscore.astype(float))
pace_rows = pd.concat([gm[["Season", "gameCode", "date", "homecode", "total"]].rename(columns={"homecode": "Team"}),
                       gm[["Season", "gameCode", "date", "awaycode", "total"]].rename(columns={"awaycode": "Team"})])
pace_rows = pace_rows.sort_values("date")
pace_rows["team_total10"] = pace_rows.groupby(["Season", "Team"]).total.transform(
    lambda x: x.shift().rolling(10, 1).mean())
pace = pace_rows.rename(columns={"gameCode": "Gamecode"})[["Season", "Gamecode", "Team", "team_total10"]]

rows = []
for r in b.itertuples(index=False):
    day = int(np.datetime64(r.date, "D").astype(np.int64))
    H = hist[r.Player_ID]
    out = {"Season": r.Season, "Gamecode": r.Gamecode, "Player_ID": r.Player_ID}
    for s in STATS:
        out[f"y_{s}"] = getattr(r, s)
    for src, n, tag in (("EL", 5, "el5"), ("EL", 15, "el15"), ("EL", 60, "el60"), ("DOM", 10, "dom10")):
        res = rates(H[src], day, n)
        for k, s in enumerate(STATS + ["usage"]):
            out[f"r_{s}_{tag}"] = res[0][k] if res else np.nan
        out[f"min_{tag}"] = res[1] if res else 0.0
    rows.append(out)

rt = pd.DataFrame(rows)
mins = pd.read_parquet(os.environ.get("OUT_MIN", "/home/claude/model/minutes_dataset.parquet"))
df = mins.merge(rt, on=["Season", "Gamecode", "Player_ID"])
df = df.merge(allowed, on=["Season", "Gamecode", "opp"], how="left")
df = df.merge(pace, on=["Season", "Gamecode", "Team"], how="left")
df.to_parquet(os.environ.get("OUT_RATES", "/home/claude/model/rates_dataset.parquet"), index=False)
print(df.shape)
if not FUT: print(df[[c for c in df.columns if c.startswith("r_pts") or c.startswith("y_")]].describe().round(3).T)
