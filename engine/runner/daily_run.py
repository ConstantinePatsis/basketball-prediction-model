"""Autopilot for game days (run by GitHub Actions).

  python3 daily_run.py picks   # morning / pre-game: update data, read injuries, pull Stoiximan lines, run model, log picks
  python3 daily_run.py grade   # night: update EuroLeague box scores, grade the paper log
  python3 daily_run.py nba_picks / nba_grade   # the same for the NBA (ESPN data, top 10 per game)
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
    # full data refresh (all leagues) once per day; later runs only refresh odds, injuries and picks
    marker = f"{BASE}/dbs/.updated_{now.strftime('%Y%m%d')}"
    if not os.path.exists(marker):
        if sh([sys.executable, "update_data.py"], RUN):
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            open(marker, "w").write(now.isoformat())
    else:
        print("Data already refreshed today; skipping the full update.", flush=True)
    if not sh([sys.executable, "predict_round.py"], RUN):
        return False
    rounds = [int(f[18:-4]) for f in os.listdir(RUN) if f.startswith("lines_scored_round") and f.endswith(".csv")]
    if rounds:
        sh([sys.executable, "paper_trade.py", "record", "--round", str(max(rounds))], RUN)
    return True


NBA = f"{BASE}/nba"


def nba_picks():
    """NBA: 1 OddsPapi request. Games tipping off in the next 20 hours."""
    now = datetime.now(timezone.utc)
    r = requests.get("https://api.oddspapi.io/v4/odds-by-tournaments",
                     params={"apiKey": key(), "tournamentIds": 132, "bookmaker": "stoiximan"}, timeout=120)
    r.raise_for_status()
    soon = [f for f in r.json() if now < pd.Timestamp(f["startTime"]) < now + timedelta(hours=20)]
    if soon:   # one NBA night at a time (a team can't appear twice in the feature build)
        night = lambda f: (pd.Timestamp(f["startTime"]) - timedelta(hours=10)).date()
        first = min(night(f) for f in soon)
        soon = [f for f in soon if night(f) == first]
    print(f"{len(soon)} NBA games in the next 20 hours with Stoiximan odds", flush=True)
    if not soon:
        return False
    json.dump(soon, open(f"{ODDS}/nba_live_today.json", "w"))
    sh([sys.executable, "collect_nba.py", "2026", "2026"], NBA)
    if not sh([sys.executable, "predict_nba.py", f"{ODDS}/nba_live_today.json"], NBA):
        return False
    scored = sorted(f for f in os.listdir(RUN) if f.startswith("nba_scored_"))
    if scored:
        sh([sys.executable, "nba_paper.py", "record", f"{RUN}/{scored[-1]}"], NBA)
    return True


def nba_grade():
    sh([sys.executable, "collect_nba.py", "2026", "2026"], NBA)
    sh([sys.executable, "nba_paper.py", "grade"], NBA)


def grade():
    sh([sys.executable, "collect_euroleague.py", "--start", "2026", "--end", "2026"], BASE)
    sh([sys.executable, "paper_trade.py", "grade"], RUN)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "picks"
    if mode == "picks":
        picks()
    elif mode == "grade":
        grade()
    elif mode == "nba_picks":
        nba_picks()
    elif mode == "nba_grade":
        nba_grade()
    sh([sys.executable, "export_site.py"], RUN)
    sh([sys.executable, "export_nba.py"], NBA)
