"""Paper-trading log: record the model's picks BEFORE tip-off, grade them after, keep score.

  python3 paper_trade.py record --round 14     # after predict_round.py has scored lines.csv
  python3 paper_trade.py close  --round 14     # optional: closing odds from closing_lines.csv (same format as lines.csv)
  python3 paper_trade.py grade                 # after games: fills results from official box scores
  python3 paper_trade.py report                # scoreboard

paper_log.csv holds every scored line (bets and non-bets). A "bet" is a line the model flagged (edge >= 5 points).
Stake is a flat 1 unit per bet. Lines are refused once their game has tipped off, so the record stays honest.
Paper money only.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

RUN = "/home/claude/runner"
LOG = f"{RUN}/paper_log.csv"
CET = ZoneInfo("Europe/Madrid")          # EuroLeague schedule times are Central European
COLS = ["logged_at_utc", "season", "round", "gamecode", "game", "tipoff", "player_id", "player", "team", "book",
        "stat", "line", "over_odds", "under_odds", "model_P_over", "book_P_over_novig", "edge_over", "edge_under",
        "flag", "bet_side", "bet_odds", "status", "caution", "tags", "expected_minutes", "model_mean",
        "close_over_odds", "close_under_odds", "clv",
        "actual", "minutes_played", "result", "profit"]
STAT_COLS = {"pts": ["Points"], "reb": ["TotalRebounds"], "ast": ["Assistances"], "fg3m": ["FieldGoalsMade3"],
             "pir": ["Valuation"], "pra": ["Points", "TotalRebounds", "Assistances"], "pr": ["Points", "TotalRebounds"],
             "pa": ["Points", "Assistances"], "ra": ["TotalRebounds", "Assistances"]}
KEY = ["season", "round", "player_id", "stat", "line", "book"]


def load():
    if os.path.exists(LOG):
        text = {c: "object" for c in ("player_id", "book", "result", "flag", "bet_side", "status", "caution", "tags", "game", "tipoff")}
        return pd.read_csv(LOG, dtype=text)
    return pd.DataFrame(columns=COLS)


def save(df):
    df[COLS].to_csv(LOG, index=False)


def tipoff_utc(s):
    try:
        return datetime.strptime(str(s).strip(), "%b %d, %Y %H:%M").replace(tzinfo=CET).astimezone(timezone.utc)
    except ValueError:
        return None


def record(rnd):
    f = f"{RUN}/lines_scored_round{rnd}.csv"
    if not os.path.exists(f):
        sys.exit(f"{f} not found - run predict_round.py with lines.csv first.")
    sc = pd.read_csv(f, dtype={"player_id": str, "book": str})
    sc = sc[sc.get("model_P_over").notna()] if "model_P_over" in sc else sc.iloc[0:0]
    now = datetime.now(timezone.utc)
    started = sc.tipoff.map(tipoff_utc).map(lambda t: t is None or t <= now)
    if started.any():
        print(f"Refused {int(started.sum())} line(s): game already started (or tip-off unknown).")
    sc = sc[~started].copy()
    sc["book"] = sc["book"].fillna("")
    sc["logged_at_utc"] = now.strftime("%Y-%m-%d %H:%M:%S")
    sc["flag"] = sc["flag"].fillna("")
    sc["bet_side"] = sc.flag
    sc["bet_odds"] = np.where(sc.flag == "OVER", sc.over_odds, np.where(sc.flag == "UNDER", sc.under_odds, np.nan))
    log = load()
    if len(log):
        log["book"] = log["book"].fillna("")
        seen = set(map(tuple, log[KEY].astype(str).values))
        new = sc[[tuple(r) not in seen for r in sc[KEY].astype(str).values]]
    else:
        new = sc
    for c in COLS:
        if c not in new:
            new[c] = np.nan
    log = pd.concat([log, new[COLS]], ignore_index=True)
    save(log)
    print(f"Recorded {len(new)} new line(s) for round {rnd} ({int((new.flag != '').sum())} bets). Log: {len(log)} rows.")


def close(rnd):
    f = f"{RUN}/closing_lines.csv"
    if not os.path.exists(f):
        sys.exit("closing_lines.csv not found (same columns as lines.csv, odds taken just before tip-off).")
    cl = pd.read_csv(f)
    log = load()
    sys.path.insert(0, RUN)
    from predict_round import name_key
    n = 0
    for i, r in log[(log["round"] == rnd) & (log.bet_side.fillna("") != "")].iterrows():
        m = cl[(cl.stat == r.stat) & (cl.line == r.line) & cl.player.map(lambda p: name_key(p) <= name_key(r.player))]
        if len(m) != 1:
            continue
        co, cu = float(m.over_odds.iloc[0]), float(m.under_odds.iloc[0])
        log.loc[i, ["close_over_odds", "close_under_odds"]] = [co, cu]
        p_close = (1 / co) / (1 / co + 1 / cu)
        p_open = r.book_P_over_novig
        # closing-line value: how much the no-vig market moved toward our side (positive = market agreed)
        log.loc[i, "clv"] = round((p_close - p_open) if r.bet_side == "OVER" else (p_open - p_close), 4)
        n += 1
    save(log)
    print(f"Closing odds added for {n} bet(s).")


def grade():
    log = load()
    todo = log[log.result.isna()]
    if todo.empty:
        print("Nothing to grade."); return
    con = sqlite3.connect("/home/claude/euroleague.db")
    box = pd.read_sql("SELECT * FROM player_boxscores", con)
    box["Player_ID"] = box.Player_ID.astype(str).str.strip()
    played_games = set(zip(box.Season, box.Gamecode))
    n = 0
    for i, r in todo.iterrows():
        if (int(r.season), int(r.gamecode)) not in played_games:
            continue
        b = box[(box.Season == r.season) & (box.Gamecode == r.gamecode) & (box.Player_ID == str(r.player_id).strip())]
        mins = float(b.Minutes_float.iloc[0]) if len(b) else 0.0
        log.loc[i, "minutes_played"] = round(mins, 1)
        if mins <= 0:
            log.loc[i, ["result", "profit"]] = ["void (did not play)", 0.0]; n += 1; continue
        actual = float(b[STAT_COLS[r.stat]].sum(axis=1).iloc[0])
        log.loc[i, "actual"] = actual
        side = r.bet_side if isinstance(r.bet_side, str) and r.bet_side else None
        over = actual > r.line
        if actual == r.line:
            res, prof = "push", 0.0
        elif side is None:
            res, prof = ("over" if over else "under") + " (no bet)", 0.0
        else:
            won = over if side == "OVER" else not over
            res, prof = ("win", round(r.bet_odds - 1, 3)) if won else ("loss", -1.0)
        log.loc[i, ["result", "profit"]] = [res, prof]
        n += 1
    save(log)
    print(f"Graded {n} line(s).")


def report():
    log = load()
    if log.empty:
        print("Log is empty."); return
    g = log[log.result.notna()]
    bets = g[g.result.isin(["win", "loss"])]
    print(f"Lines logged: {len(log)} | graded: {len(g)} | bets settled: {len(bets)} | pending: {int(log.result.isna().sum())}")
    if len(bets):
        def summary(x):
            w = (x.result == "win").sum()
            return pd.Series({"bets": len(x), "win %": round(100 * w / len(x), 1),
                              "break-even win %": round(100 * (1 / x.bet_odds).mean(), 1),
                              "profit (units)": round(x.profit.sum(), 2), "ROI %": round(100 * x.profit.sum() / len(x), 1),
                              "avg CLV (pts)": round(100 * x.clv.mean(), 2) if x.clv.notna().any() else np.nan})
        print("\nAll bets:"); print(summary(bets).to_string())
        print("\nBy stat:"); print(bets.groupby("stat").apply(summary).to_string())
        print("\nBy tag:"); print(bets.assign(tags=bets.tags.str.split(",")).explode("tags").groupby("tags").apply(summary).to_string())
        e = np.where(bets.bet_side == "OVER", bets.edge_over, bets.edge_under)
        print("\nBy edge size:"); print(bets.groupby(pd.cut(e, [0, .07, .10, 1], labels=["5-7", "7-10", "10+"]), observed=True).apply(summary).to_string())
    # probability quality on every graded line (bets or not): model vs bookmaker
    s = g[~g.result.str.startswith(("void", "push"))]
    if len(s):
        y = (s.actual > s.line).astype(float)
        print(f"\nAll graded lines ({len(s)}): Brier model {np.mean((s.model_P_over - y) ** 2):.4f}"
              f" vs bookmaker {np.mean((s.book_P_over_novig - y) ** 2):.4f} (lower is better)")
    if len(bets) < 300:
        print(f"\nNote: {len(bets)} settled bets is a small sample. Results mean little before a few hundred.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record", "close", "grade", "report"])
    ap.add_argument("--round", type=int)
    a = ap.parse_args()
    {"record": lambda: record(a.round), "close": lambda: close(a.round), "grade": grade, "report": report}[a.cmd]()
