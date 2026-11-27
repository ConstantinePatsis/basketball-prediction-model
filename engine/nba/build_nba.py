"""NBA pre-game features (only information from earlier games) -> /home/claude/nba/nba_dataset.parquet
One row per player per game he was listed for (dressed). Targets: minutes and stats."""
import os
import sqlite3

import numpy as np
import pandas as pd

DB = "/home/claude/nba/nba.db"
OUT = os.environ.get("NBA_OUT", "/home/claude/nba/nba_dataset.parquet")
FUT = os.environ.get("NBA_FUTURE")          # optional parquet with future rows (event_id, date, team, opp, home, athlete_id, player, ...)
TEAM = {  # lat, lon, UTC offset (standard time)
 "ATL": (33.76, -84.40, -5), "BOS": (42.37, -71.06, -5), "BKN": (40.68, -73.98, -5), "CHA": (35.23, -80.84, -5),
 "CHI": (41.88, -87.67, -6), "CLE": (41.50, -81.69, -5), "DAL": (32.79, -96.81, -6), "DEN": (39.75, -105.01, -7),
 "DET": (42.34, -83.06, -5), "GS": (37.77, -122.39, -8), "HOU": (29.75, -95.36, -6), "IND": (39.76, -86.16, -5),
 "LAC": (33.94, -118.34, -8), "LAL": (34.04, -118.27, -8), "MEM": (35.14, -90.05, -6), "MIA": (25.78, -80.19, -5),
 "MIL": (43.05, -87.92, -6), "MIN": (44.98, -93.28, -6), "NO": (29.95, -90.08, -6), "NY": (40.75, -73.99, -5),
 "OKC": (35.46, -97.52, -6), "ORL": (28.54, -81.38, -5), "PHI": (39.90, -75.17, -5), "PHX": (33.45, -112.07, -7),
 "POR": (45.53, -122.67, -8), "SAC": (38.58, -121.50, -8), "SA": (29.43, -98.44, -6), "TOR": (43.64, -79.38, -5),
 "UTAH": (40.77, -111.90, -7), "WSH": (38.90, -77.02, -5)}
BUBBLE = (28.37, -81.55, -5)                 # 2020 restart, Orlando
STATS = ["pts", "reb", "ast", "fg3m", "fga", "fta", "tov", "oreb", "stl", "blk"]


def km(a, b):
    la1, lo1, la2, lo2 = map(np.radians, (a[0], a[1], b[0], b[1]))
    return 6371 * 2 * np.arcsin(np.sqrt(np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2))


con = sqlite3.connect(DB)
g = pd.read_sql("SELECT * FROM games", con)
b = pd.read_sql("SELECT * FROM box", con)
# drop games ESPN stored without stats
tot = b.groupby("event_id").pts.sum()
g = g[g.event_id.isin(tot[tot > 0].index)]
b = b[b.event_id.isin(g.event_id)]
b["min"] = b["min"].fillna(0)
b.loc[b.dnp == 1, "min"] = 0
for s in STATS:
    b[s] = pd.to_numeric(b[s], errors="coerce").fillna(0)
g["date"] = pd.to_datetime(g.date)
b = b.merge(g[["event_id", "season", "season_type", "date", "home", "away", "home_score", "away_score", "neutral"]], on="event_id")
b["is_home"] = (b.team == b.home).astype(int)
b["opp"] = np.where(b.is_home == 1, b.away, b.home)
b["team_score"] = np.where(b.is_home == 1, b.home_score, b.away_score)
b["opp_score"] = np.where(b.is_home == 1, b.away_score, b.home_score)
b["playoff"] = (b.season_type != 2).astype(int)

if FUT:
    f = pd.read_parquet(FUT)
    f["date"] = pd.to_datetime(f.date)
    for c in ["min"] + STATS + ["team_score", "opp_score", "starter"]:
        f[c] = np.nan
    b = pd.concat([b, f], ignore_index=True)

# ---------------- team-level game table: strength, pace, rest, travel
tg = b.groupby(["event_id", "team"]).agg(date=("date", "first"), season=("season", "first"), opp=("opp", "first"),
                                          is_home=("is_home", "first"), neutral=("neutral", "first"),
                                          pts=("team_score", "first"), opp_pts=("opp_score", "first"),
                                          fga=("fga", "sum"), fta=("fta", "sum"), oreb=("oreb", "sum"), tov=("tov", "sum")).reset_index()
tg = tg.sort_values(["team", "date"])
tg["poss"] = tg.fga + 0.44 * tg.fta - tg.oreb + tg.tov
tg.loc[tg.pts.isna(), "poss"] = np.nan
grp = tg.groupby(["team", "season"])
tg["net10"] = grp.apply(lambda x: (x.pts - x.opp_pts).shift().rolling(10, 1).mean()).reset_index(level=[0, 1], drop=True)
tg["pace10"] = grp.poss.transform(lambda s: s.shift().rolling(10, 1).mean())
tg["days_rest"] = tg.groupby("team").date.diff().dt.days.clip(upper=10)
tg["b2b"] = (tg.days_rest == 1).astype(int)
tg["g_last4"] = tg.groupby("team", group_keys=False).apply(lambda x: pd.Series([((x.date < d) & (x.date >= d - pd.Timedelta(days=4))).sum() for d in x.date], index=x.index))
tg["g_last7"] = tg.groupby("team", group_keys=False).apply(lambda x: pd.Series([((x.date < d) & (x.date >= d - pd.Timedelta(days=7))).sum() for d in x.date], index=x.index))


def loc(r):
    if r.neutral == 1 and r.season == 2019 and r.date >= pd.Timestamp("2020-07-01"):
        return BUBBLE
    host = r.team if r.is_home == 1 else r.opp
    return TEAM.get(host, BUBBLE)


tg["loc"] = tg.apply(loc, axis=1)
tg["prev_loc"] = tg.groupby("team")["loc"].shift()
tg["travel_km"] = [km(a, c) if isinstance(a, tuple) else 0.0 for a, c in zip(tg.prev_loc, tg["loc"])]
tg["tz_shift"] = [abs(c[2] - a[2]) if isinstance(a, tuple) else 0 for a, c in zip(tg.prev_loc, tg["loc"])]
tg["away_streak"] = tg.groupby(["team", "season"]).is_home.transform(lambda s: s.eq(0).groupby(s.eq(1).cumsum()).cumsum())
opp = tg[["event_id", "team", "net10", "pace10", "days_rest", "b2b"]].rename(columns={"team": "opp", "net10": "opp_net10", "pace10": "opp_pace10", "days_rest": "opp_days_rest", "b2b": "opp_b2b"})
TF = ["net10", "pace10", "days_rest", "b2b", "g_last4", "g_last7", "travel_km", "tz_shift", "away_streak"]
b = b.merge(tg[["event_id", "team"] + TF], on=["event_id", "team"], how="left").merge(opp, on=["event_id", "opp"], how="left")
b["exp_margin"] = b.net10 - b.opp_net10 + np.where(b.is_home == 1, 2.5, -2.5)
b["abs_exp_margin"] = b.exp_margin.abs()
b["exp_pace"] = (b.pace10 + b.opp_pace10) / 2

# ---------------- player history (shifted: only earlier games)
b = b.sort_values(["athlete_id", "date"]).reset_index(drop=True)
p = b.groupby("athlete_id")
sh = lambda col, w, fn="mean": p[col].transform(lambda s: getattr(s.shift().rolling(w, 1), fn)())
b["min_last1"] = p["min"].shift()
for w in (3, 5, 10):
    b[f"min_avg{w}"] = sh("min", w)
b["min_std5"] = sh("min", 5, "std")
ps = b.groupby(["athlete_id", "season"])
b["season_games"] = ps.cumcount()
b["season_min_avg"] = ps["min"].transform(lambda s: s.shift().expanding().mean())
b["start_rate_season"] = ps.starter.transform(lambda s: s.shift().expanding().mean())
b["start_rate5"] = p.starter.transform(lambda s: s.shift().rolling(5, 1).mean())
b["last_start"] = p.starter.shift()
b["career_games"] = p.cumcount()
prev = b[b.playoff == 0].groupby(["athlete_id", "season"])["min"].mean().reset_index()
prev["season"] += 1
b = b.merge(prev.rename(columns={"min": "prev_season_min"}), on=["athlete_id", "season"], how="left")
b = b.sort_values(["athlete_id", "date"]).reset_index(drop=True)
p = b.groupby("athlete_id")
b["days_since_last"] = p.date.diff().dt.days.clip(upper=30)
b["min_trend"] = b.min_avg3 - b.season_min_avg
for s in ["pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]:
    for w in (5, 15, 60):
        num = p[s].transform(lambda x: x.shift().rolling(w, 1).sum())
        den = p["min"].transform(lambda x: x.shift().rolling(w, 1).sum())
        b[f"r_{s}_{w}"] = num / den.replace(0, np.nan)
b["usage_15"] = b.r_fga_15 + 0.44 * b.r_fta_15 + b.r_tov_15

# ---------------- rotation context (who is dressed tonight)
b["avg5_fill"] = b.min_avg5.fillna(b.prev_season_min).fillna(0)
b["team_min_available"] = b.groupby(["event_id", "team"]).avg5_fill.transform("sum")
b["teammate_min_share"] = b.avg5_fill / b.team_min_available.replace(0, np.nan)
# minutes missing: rotation players from the team's last 3 games who are not listed tonight
tgames = b[["team", "event_id", "date"]].drop_duplicates().sort_values(["team", "date"])
played = b[b["min"] > 0].groupby(["team", "event_id"]).athlete_id.apply(set).to_dict()
listed = b.groupby(["team", "event_id"]).athlete_id.apply(set).to_dict()
last_avg = b.set_index(["athlete_id", "event_id"]).avg5_fill.to_dict()
miss = {}
for t, x in tgames.groupby("team"):
    ev = list(x.event_id)
    for i, e in enumerate(ev):
        rot = set().union(*[played.get((t, c), set()) for c in ev[max(0, i - 3):i]])
        gone = rot - listed.get((t, e), set())
        miss[(t, e)] = sum(last_avg.get((a, ev[i - 1]), 0) for a in gone) if i else 0.0
b["missing_min"] = [miss.get((t, e), 0.0) for t, e in zip(b.team, b.event_id)]

# ---------------- opponent: stats allowed per minute over its last 15 games
allowed = b.groupby(["event_id", "opp"]).agg(date=("date", "first"), **{f"a_{s}": (s, "sum") for s in ["pts", "reb", "ast", "fg3m"]},
                                              m=("min", "sum")).reset_index().sort_values(["opp", "date"])
for s in ["pts", "reb", "ast", "fg3m"]:
    allowed[f"opp_allow_{s}"] = allowed.groupby("opp")[f"a_{s}"].transform(lambda x: x.shift().rolling(15, 1).sum()) / \
        allowed.groupby("opp")["m"].transform(lambda x: x.shift().rolling(15, 1).sum()).replace(0, np.nan)
b = b.merge(allowed[["event_id", "opp"] + [f"opp_allow_{s}" for s in ["pts", "reb", "ast", "fg3m"]]], on=["event_id", "opp"], how="left")

b.to_parquet(OUT, index=False)
print(b.shape, "rows; with minutes > 0:", int((b["min"] > 0).sum()))
