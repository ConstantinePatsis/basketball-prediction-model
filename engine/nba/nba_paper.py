"""NBA paper trading log (€10 paper stake, top 10 flagged lines per game by gap).

  python3 nba_paper.py record /home/claude/runner/nba_scored_YYYYMMDD.csv
  python3 nba_paper.py grade
  python3 nba_paper.py report
Each line is logged once (event, player, stat), only before tip-off; at most 10 picks per game.
Graded from ESPN box scores in nba.db; did not play -> void. Paper money only."""
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

LOG = "/home/claude/runner/nba_paper_log.csv"
DB = "/home/claude/nba/nba.db"
PER_GAME = 10
STAKE = 10.0
COMBO = {"pr": ("pts", "reb"), "pa": ("pts", "ast"), "pra": ("pts", "reb", "ast"), "ra": ("reb", "ast")}


def load():
    try:
        return pd.read_csv(LOG, dtype={"event_id": str, "athlete_id": str, "result": object, "flag": object})
    except FileNotFoundError:
        return pd.DataFrame()


def record(path):
    s = pd.read_csv(path, dtype={"event_id": str, "athlete_id": str})
    now = pd.Timestamp(datetime.now(timezone.utc))
    s = s[(s.flag.isin(["OVER", "UNDER"])) & (pd.to_datetime(s.tipoff, utc=True) > now)].copy()
    s["edge"] = np.where(s.flag == "OVER", s.edge_over, s.edge_under)
    s["bet_side"] = s.flag
    s["bet_odds"] = np.where(s.flag == "OVER", s.over_odds, s.under_odds)
    s["logged_at"] = now.isoformat(timespec="minutes")
    log = load()
    for c in ("result", "actual"):
        if len(log) and c not in log:
            log[c] = np.nan
    have = set(zip(log.event_id, log.athlete_id, log.stat)) if len(log) else set()
    count = log.groupby("event_id").size().to_dict() if len(log) else {}
    new = []
    for ev, x in s.sort_values("edge", ascending=False).groupby("event_id", sort=False):
        room = PER_GAME - count.get(ev, 0)
        for r in x.to_dict("records"):
            if room <= 0:
                break
            if (ev, r["athlete_id"], r["stat"]) in have:
                continue
            new.append(r)
            room -= 1
    if new:
        log = pd.concat([log, pd.DataFrame(new)], ignore_index=True)
        log.to_csv(LOG, index=False)
    print(f"logged {len(new)} new NBA paper picks ({len(log)} total)")


def grade():
    log = load()
    if log.empty:
        return
    for c in ("result", "actual"):
        if c not in log:
            log[c] = np.nan
    log["result"] = log.result.astype(object)
    con = sqlite3.connect(DB)
    todo = log[log.result.isna()]
    if todo.empty:
        print("nothing to grade")
        return
    q = ",".join("?" * todo.event_id.nunique())
    box = pd.read_sql(f"SELECT event_id, athlete_id, min, pts, reb, ast, fg3m FROM box WHERE event_id IN ({q})", con,
                      params=list(todo.event_id.unique()))
    done = set(box.event_id)
    box = box.set_index(["event_id", "athlete_id"])
    n = 0
    for i, r in todo.iterrows():
        if r.event_id not in done:
            continue
        k = (r.event_id, str(r.athlete_id))
        if k not in box.index or not (box.loc[k, "min"] > 0):
            log.loc[i, "result"] = "void (did not play)"
        else:
            b = box.loc[k]
            a = sum(b[x] for x in COMBO.get(r.stat, (r.stat,)))
            log.loc[i, "actual"] = a
            if a == r.line:
                log.loc[i, "result"] = "push"
            else:
                win = (a > r.line) if r.bet_side == "OVER" else (a < r.line)
                log.loc[i, "result"] = "win" if win else "loss"
        n += 1
    log.to_csv(LOG, index=False)
    print(f"graded {n} NBA picks")


def report():
    log = load()
    s = log[log.result.isin(["win", "loss"])]
    if s.empty:
        print("no graded picks yet")
        return
    p = np.where(s.result == "win", STAKE * (s.bet_odds - 1), -STAKE)
    print(f"{len(s)} graded: {int((s.result == 'win').sum())}W-{int((s.result == 'loss').sum())}L, paper profit €{p.sum():.2f}")


if __name__ == "__main__":
    {"record": lambda: record(sys.argv[2]), "grade": grade, "report": report}[sys.argv[1]]()
