"""Autopilot for game days (run by GitHub Actions).

  python3 daily_run.py picks   # morning / pre-game: update data, read injuries, pull Stoiximan lines, run model, log picks
  python3 daily_run.py grade   # night: update EuroLeague box scores, grade the paper log
Both end by exporting the website's JSON files.

Uses 1 OddsPapi request per 'picks' run (odds-by-tournaments), only on days with EuroLeague games.
Paper trading only.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

BASE = "/home/claude"
RUN = f"{BASE}/runner"
ODDS = f"{BASE}/odds"
STAT = {"playertotals-points": "pts", "playertotals-rebounds": "reb", "playertotals-assists": "ast",
        "playertotals-3pointers": "fg3m", "playertotals-ptsreb": "pr", "playertotals-ptsass": "pa",
        "playertotals-ptsassreb": "pra", "playertotals-assreb": "ra"}


def key():
    k = os.environ.get("ODDSPAPI_KEY")
    if not k and os.path.exists(f"{ODDS}/.oddspapi_key"):
        k = open(f"{ODDS}/.oddspapi_key").read().strip()
    if not k:
        sys.exit("ODDSPAPI_KEY not set")
    return k


def sh(cmd, cwd):
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    return r.returncode == 0


def main_lines(fixtures):
    """Stoiximan player-prop main lines (over/under odds closest together) for the given fixtures."""
    mm = {str(x["marketId"]): x for x in json.load(open(f"{ODDS}/markets_basketball.json"))}
    rows = []
    for fx in fixtures:
        mk = fx.get("bookmakerOdds", {}).get("stoiximan", {}).get("markets", {})
        for m, v in mk.items():
            d = mm.get(m, {})
            st = STAT.get(d.get("marketType"))
            if not st:
                continue
            o_id, u_id = str(d["outcomes"][0]["outcomeId"]), str(d["outcomes"][1]["outcomeId"])
            ov = v["outcomes"].get(o_id, {}).get("players", {})
            un = v["outcomes"].get(u_id, {}).get("players", {})
            for pid in set(ov) & set(un):
                o, u = ov[pid], un[pid]
                if o.get("active") and u.get("active") and o.get("playerName"):
                    rows.append({"player": o["playerName"], "stat": st, "line": d["handicap"],
                                 "over_odds": o["price"], "under_odds": u["price"], "book": "Stoiximan"})
    if not rows:
        return pd.DataFrame()
    L = pd.DataFrame(rows)
    L["gap"] = (L.over_odds - L.under_odds).abs()
    return L.sort_values("gap").groupby(["player", "stat"]).head(1).drop(columns="gap")


def picks():
    now = datetime.now(timezone.utc)
    r = requests.get("https://api.oddspapi.io/v4/odds-by-tournaments",
                     params={"apiKey": key(), "tournamentIds": 138, "bookmaker": "stoiximan"}, timeout=120)
    r.raise_for_status()
    fx = r.json()
    soon = [f for f in fx if now < pd.Timestamp(f["startTime"]) < now + timedelta(hours=30)]
    print(f"{len(soon)} EuroLeague games in the next 30 hours with Stoiximan odds", flush=True)
    if not soon:
        return False
    json.dump(soon, open(f"{ODDS}/live_today.json", "w"))
    L = main_lines(soon)
    if L.empty:
        print("No player props posted yet.")
        return False
    L.to_csv(f"{RUN}/lines.csv", index=False)
    print(f"{len(L)} player-prop lines", flush=True)
    sh([sys.executable, "update_data.py"], RUN)
    if not sh([sys.executable, "predict_round.py"], RUN):
        return False
    rounds = [int(f[18:-4]) for f in os.listdir(RUN) if f.startswith("lines_scored_round") and f.endswith(".csv")]
    if rounds:
        sh([sys.executable, "paper_trade.py", "record", "--round", str(max(rounds))], RUN)
    return True


def grade():
    sh([sys.executable, "collect_euroleague.py", "--start", "2026", "--end", "2026"], BASE)
    sh([sys.executable, "paper_trade.py", "grade"], RUN)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "picks"
    if mode == "picks":
        picks()
    elif mode == "grade":
        grade()
    sh([sys.executable, "export_site.py"], RUN)
