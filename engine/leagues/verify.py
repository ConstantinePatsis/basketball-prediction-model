"""Per-league check: games per season, player points vs final score, minutes sanity."""
import sqlite3
import sys

import pandas as pd

lg = sys.argv[1]
con = sqlite3.connect(f"/home/claude/dbs/{lg}.db")
g = pd.read_sql("SELECT * FROM dom_games", con)
b = pd.read_sql("SELECT season, game_id, is_home, SUM(points) pts, SUM(minutes) mins, COUNT(*) n "
                "FROM dom_box GROUP BY 1,2,3", con)
m = b.merge(g, on=["season", "game_id"])
m["official"] = m.home_score.where(m.is_home == 1, m.away_score)
m["ok"] = m.pts == m.official
summary = (m.groupby("season")
           .agg(games=("game_id", "nunique"), team_rows=("ok", "size"), pts_match=("ok", "mean"),
                avg_team_minutes=("mins", "mean"))
           .round(3))
print(f"== {lg}")
print(summary.to_string())
fails = pd.read_sql("SELECT COUNT(*) n FROM dom_failed", con).n[0]
print(f"failed fetches: {fails}; player rows: {pd.read_sql('SELECT COUNT(*) n FROM dom_box', con).n[0]}")
bad = m[~m.ok]
if len(bad):
    print("mismatches (first 5):")
    print(bad[["season", "game_id", "home_team", "away_team", "is_home", "pts", "official"]].head().to_string(index=False))
