"""Build the minutes-model dataset: one row per EuroLeague player-game.

Every feature uses only games played BEFORE the target game's date (no leakage).
Sources: basketball.db (el_box, el_games, dom_box, dom_games, team_xwalk).
Output: /home/claude/model/minutes_dataset.parquet
"""
import bisect
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd

DB = "/home/claude/basketball.db"
con = sqlite3.connect(DB)

# ---------- EuroLeague games ----------
g = pd.read_sql("SELECT Season, gameCode, date, Phase, Round, homecode, awaycode, "
                "homescore, awayscore FROM el_games", con)
g["gameCode"] = g.gameCode.astype(int)
g["date"] = pd.to_datetime(g.date, format="%b %d, %Y")
b = pd.read_sql("SELECT Season, Gamecode, Home, Player_ID, IsStarter, Team, Player, Minutes_float "
                "FROM el_box", con)
# optional upcoming games (daily runner): rows with unknown minutes, appended so they get identical features
import os
FUT = os.environ.get("FUTURE_DIR")
if FUT:
    fg = pd.read_parquet(f"{FUT}/future_games.parquet")
    fg["date"] = pd.to_datetime(fg.date, format="%b %d, %Y")
    g = pd.concat([g, fg], ignore_index=True)
    b = pd.concat([b, pd.read_parquet(f"{FUT}/future_box.parquet")], ignore_index=True)
b = b.merge(g, left_on=["Season", "Gamecode"], right_on=["Season", "gameCode"])
b["opp"] = np.where(b.Home == 1, b.awaycode, b.homecode)
b["team_pts"] = np.where(b.Home == 1, b.homescore, b.awayscore).astype(float)
b["opp_pts"] = np.where(b.Home == 1, b.awayscore, b.homescore).astype(float)
b = b.rename(columns={"Minutes_float": "minutes"})
# drop the one game with a corrupted box score
b = b[~((b.Season == 2017) & (b.Gamecode == 14))]

# ---------- all appearances per player (EuroLeague + linked domestic) ----------
dg = pd.read_sql("SELECT league, season, game_id, date FROM dom_games", con)
db = pd.read_sql("SELECT league, season, game_id, el_player_id, minutes FROM dom_box "
                 "WHERE el_player_id IS NOT NULL", con)
db = db.merge(dg, on=["league", "season", "game_id"])
db["date"] = pd.to_datetime(db.date, errors="coerce")
db = db.dropna(subset=["date"])

apps = pd.concat([
    b[b.minutes.notna()][["Player_ID", "date", "minutes"]].assign(comp="EL"),
    db.rename(columns={"el_player_id": "Player_ID"})[["Player_ID", "date", "minutes"]].assign(comp="DOM"),
]).sort_values("date")

by_player = defaultdict(lambda: {"EL": ([], []), "DOM": ([], []), "ALL": ([], [])})
for pid, d, m, c in apps.itertuples(index=False):
    ts = d.value // 86_400_000_000_000          # day number
    for key in (c, "ALL"):
        by_player[pid][key][0].append(ts)
        by_player[pid][key][1].append(m)

# which EuroLeague team-seasons have domestic data at all
tx = pd.read_sql("SELECT season, el_team FROM team_xwalk", con)
has_dom = set(zip(tx.season, tx.el_team))

# ---------- team strength: rolling point differential before each game ----------
tg = b.groupby(["Season", "Gamecode", "Team", "date"]).agg(diff=("team_pts", "first"),
                                                            opp_pts=("opp_pts", "first")).reset_index()
tg["diff"] = tg["diff"] - tg["opp_pts"]
tg = tg.sort_values("date")
tg["net10"] = tg.groupby(["Season", "Team"])["diff"].transform(lambda s: s.shift().rolling(10, 1).mean())
net = tg.set_index(["Season", "Gamecode", "Team"])["net10"]

# ---------- player EuroLeague history (season-level) ----------
b = b.sort_values(["Player_ID", "date"])
prev_season_avg = (b[b.minutes > 0].groupby(["Player_ID", "Season"]).minutes.mean()
                   .rename("avg").reset_index())
prev_season_avg["Season"] += 1
prev_season_avg = prev_season_avg.set_index(["Player_ID", "Season"])["avg"]


def window(arr_t, arr_m, day, lo_days=None, last_n=None):
    """Values strictly before `day`; either within lo_days or the last_n."""
    i = bisect.bisect_left(arr_t, day)
    if last_n is not None:
        return arr_m[max(0, i - last_n):i]
    j = bisect.bisect_left(arr_t, day - lo_days)
    return arr_m[j:i]


rows = []
for r in b.itertuples(index=False):
    day = r.date.value // 86_400_000_000_000
    P = by_player[r.Player_ID]
    el_t, el_m = P["EL"]
    dom_t, dom_m = P["DOM"]
    all_t, all_m = P["ALL"]

    i_el = bisect.bisect_left(el_t, day)
    last_el = [x for x in el_m[max(0, i_el - 10):i_el]]
    i_all = bisect.bisect_left(all_t, day)


    rows.append({
        "Season": r.Season, "Gamecode": r.Gamecode, "date": r.date, "Player_ID": r.Player_ID,
        "Player": r.Player, "Team": r.Team, "opp": r.opp, "home": r.Home,
        "playoff": int(r.Phase != "RS"), "round": r.Round,
        "minutes": r.minutes, "starter": r.IsStarter,
        "el_last1": last_el[-1] if last_el else np.nan,
        "el_avg3": np.mean(last_el[-3:]) if last_el else np.nan,
        "el_avg5": np.mean(last_el[-5:]) if last_el else np.nan,
        "el_avg10": np.mean(last_el) if last_el else np.nan,
        "el_std5": np.std(last_el[-5:]) if len(last_el) >= 2 else np.nan,
        "el_games_career": i_el,
        "days_since_el": (day - el_t[i_el - 1]) if i_el else np.nan,
        "days_since_any": (day - all_t[i_all - 1]) if i_all else np.nan,
        "min_last3d": float(np.sum(window(all_t, all_m, day, lo_days=3))),
        "min_last7d": float(np.sum(window(all_t, all_m, day, lo_days=7))),
        "games_last7d": len(window(all_t, all_m, day, lo_days=7)),
        "min_last14d": float(np.sum(window(all_t, all_m, day, lo_days=14))),
        "dom_avg5": (np.mean(window(dom_t, dom_m, day, last_n=5))
                     if bisect.bisect_left(dom_t, day) else np.nan),
        "dom_games_last7d": len(window(dom_t, dom_m, day, lo_days=7)),
        "has_dom_data": int((r.Season, r.Team) in has_dom),
        "prev_season_avg": prev_season_avg.get((r.Player_ID, r.Season), np.nan),
        "team_net10": net.get((r.Season, r.Gamecode, r.Team), np.nan),
        "opp_net10": net.get((r.Season, r.Gamecode, r.opp), np.nan),
    })

df = pd.DataFrame(rows).sort_values(["Player_ID", "date"])

# season-to-date features (shifted so the current game is excluded)
grp = df.groupby(["Player_ID", "Season"])
df["season_games"] = grp.cumcount()
df["season_avg"] = grp.minutes.transform(lambda s: s.shift().expanding().mean())
df["season_start_rate"] = grp.starter.transform(lambda s: s.shift().expanding().mean())
df["start_rate5"] = grp.starter.transform(lambda s: s.shift().rolling(5, 1).mean())
df["last_start"] = grp.starter.shift()
df["exp_margin"] = df.team_net10 - df.opp_net10 + np.where(df.home == 1, 3.0, -3.0)
df["abs_exp_margin"] = df.exp_margin.abs()
df["trend"] = df.el_avg3 - df.season_avg

# rotation context: minutes the team lost from players who were absent from its previous game
team_games = df[["Season", "Team", "Gamecode", "date"]].drop_duplicates().sort_values("date")
roster_min = df.groupby(["Season", "Team", "Gamecode"]).apply(
    lambda x: dict(zip(x.Player_ID, x.el_avg5.fillna(0)))).rename("roster")
df = df.merge(roster_min.reset_index(), on=["Season", "Team", "Gamecode"])
df["team_min_available"] = df.roster.apply(lambda d: sum(v for v in d.values()))
df["teammate_min_share"] = df.el_avg5 / df.team_min_available.replace(0, np.nan)
df = df.drop(columns=["roster"])

df.to_parquet(os.environ.get("OUT_MIN", "/home/claude/model/minutes_dataset.parquet"), index=False)
print(df.shape)
print(df[df.minutes > 0].describe().T[["mean", "min", "max"]].round(2).to_string())
