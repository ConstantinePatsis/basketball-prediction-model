"""Live NBA picks: tonight's games -> rosters + ESPN injury statuses -> features -> 8,000 simulations ->
compare with Stoiximan main lines.

  python3 predict_nba.py /home/claude/odds/nba_live_today.json      # odds-by-tournaments response (tournament 132)
Writes /home/claude/runner/nba_scored_<YYYYMMDD>.csv (one row per Stoiximan line) and nba_injuries_<YYYYMMDD>.csv.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import timedelta

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, "/home/claude/nba")
import nba_engine as E

N = "/home/claude/nba/"
RUN = "/home/claude/runner/"
ODDS = "/home/claude/odds/"
U = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
STAT = {"playertotals-points": "pts", "playertotals-rebounds": "reb", "playertotals-assists": "ast",
        "playertotals-3pointers": "fg3m", "playertotals-ptsreb": "pr", "playertotals-ptsass": "pa",
        "playertotals-ptsassreb": "pra", "playertotals-assreb": "ra"}
ABBR = {"Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
        "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
        "Detroit Pistons": "DET", "Golden State Warriors": "GS", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
        "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
        "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NO", "New York Knicks": "NY",
        "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
        "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SA", "Toronto Raptors": "TOR",
        "Utah Jazz": "UTAH", "Washington Wizards": "WSH"}
STATUS = {"out": "OUT", "doubtful": "LIKELY_OUT", "questionable": "GTD", "day-to-day": "GTD", "probable": "AVAILABLE",
          "suspension": "OUT", "suspended": "OUT"}


def get(url, **p):
    r = S.get(url, params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def main_lines(fixtures):
    mm = {str(x["marketId"]): x for x in json.load(open(ODDS + "markets_basketball.json"))}
    rows = []
    for fx in fixtures:
        for m, v in fx.get("bookmakerOdds", {}).get("stoiximan", {}).get("markets", {}).items():
            d = mm.get(m, {})
            st = STAT.get(d.get("marketType"))
            if not st:
                continue
            oi, ui = str(d["outcomes"][0]["outcomeId"]), str(d["outcomes"][1]["outcomeId"])
            ov, un = v["outcomes"].get(oi, {}).get("players", {}), v["outcomes"].get(ui, {}).get("players", {})
            for pid in set(ov) & set(un):
                o, u = ov[pid], un[pid]
                if o.get("active") and u.get("active") and o.get("playerName"):
                    rows.append({"fixtureId": fx["fixtureId"], "player_name": o["playerName"], "stat": st, "line": d["handicap"],
                                 "over_odds": o["price"], "under_odds": u["price"]})
    L = pd.DataFrame(rows)
    if L.empty:
        return L
    L["gap"] = (L.over_odds - L.under_odds).abs()
    return L.sort_values("gap").groupby(["fixtureId", "player_name", "stat"]).head(1).drop(columns="gap")


def toks(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return [w for w in re.sub(r"[^A-Z ]", " ", s).split() if w not in ("JR", "SR", "II", "III", "IV")]


def match(name, cands):
    sur, _, first = str(name).partition(",")
    st, ft = toks(sur), toks(first)
    hits = [a for a, n in cands if st and " ".join(st) in " ".join(toks(n))]
    if len(hits) > 1 and ft:
        hits = [a for a, n in cands if a in hits and toks(n) and toks(n)[0][:3] == ft[0][:3]]
    return hits[0] if len(hits) == 1 else None


def main(path):
    fixtures = json.load(open(path))
    pn = json.load(open(ODDS + "nba_participants.json"))
    for f in fixtures:
        f.setdefault("participant1Name", pn.get(str(f.get("participant1Id"))))
        f.setdefault("participant2Name", pn.get(str(f.get("participant2Id"))))
    L = main_lines(fixtures)
    if L.empty:
        print("no NBA player props posted yet")
        return None
    tips = {f["fixtureId"]: pd.Timestamp(f["startTime"]) for f in fixtures}
    # ESPN events for the US dates covering these tip-offs
    days = sorted({(t - timedelta(hours=6)).strftime("%Y%m%d") for t in tips.values()})
    ev = {}
    for dd in days:
        for e in get(U + "/scoreboard", dates=dd).get("events", []):
            c = e["competitions"][0]
            teams = {x["homeAway"]: (x["team"]["abbreviation"], x["team"]["id"]) for x in c["competitors"]}
            ev[frozenset((teams["home"][0], teams["away"][0]))] = {
                "event_id": e["id"], "tip": pd.Timestamp(e["date"]), "home": teams["home"][0], "away": teams["away"][0],
                "home_id": teams["home"][1], "away_id": teams["away"][1], "neutral": int(bool(c.get("neutralSite")))}
    fmap = {}
    for f in fixtures:
        k = frozenset((ABBR.get(f.get("participant1Name")), ABBR.get(f.get("participant2Name"))))
        if k in ev and abs((ev[k]["tip"] - tips[f["fixtureId"]]).total_seconds()) < 6 * 3600:
            fmap[f["fixtureId"]] = ev[k]
    print(f"{len(fmap)} of {len(fixtures)} fixtures matched to ESPN games", flush=True)

    # rosters and injuries
    import sqlite3
    con = sqlite3.connect(N + "nba.db")
    hist = pd.read_sql("SELECT b.athlete_id, b.team, b.player, g.date FROM box b JOIN games g USING(event_id) "
                       "WHERE g.season >= 2025", con).sort_values("date")
    last_team = hist.groupby("athlete_id").team.last()
    fut, inj_rows = [], []
    for g in {v["event_id"]: v for v in fmap.values()}.values():
        summ = get(U + "/summary", event=g["event_id"])
        status = {}
        for t in summ.get("injuries", []):
            ab = t["team"]["abbreviation"]
            for i in t.get("injuries", []):
                a = i.get("athlete", {})
                st = STATUS.get(str(i.get("status", "")).lower(), "GTD")
                status[str(a.get("id"))] = st
                inj_rows.append({"event_id": g["event_id"], "team": ab, "athlete_id": str(a.get("id")),
                                 "player": a.get("displayName"), "status": st, "detail": i.get("status")})
        for side, opp_side in (("home", "away"), ("away", "home")):
            team, tid = g[side], g[f"{side}_id"]
            try:
                ros = get(U + f"/teams/{tid}/roster").get("athletes", [])
                ids = [(str(a["id"]), a.get("displayName")) for a in ros]
            except Exception:                                    # fall back to recent appearances for this team
                ids = [(a, None) for a in last_team[last_team == team].index]
            for aid, name in ids:
                if status.get(aid) in ("OUT", "LIKELY_OUT"):
                    continue
                fut.append({"event_id": g["event_id"], "team": team, "athlete_id": aid, "player": name,
                            "date": g["tip"].strftime("%Y-%m-%d"), "season": 2026, "season_type": 2,
                            "home": g["home"], "away": g["away"], "neutral": g["neutral"], "is_home": int(side == "home"),
                            "opp": g[opp_side], "playoff": 0, "dnp": 0, "status": status.get(aid, "AVAILABLE")})
    F = pd.DataFrame(fut)
    nm = hist.groupby("athlete_id").player.last()
    F["player"] = F.player.fillna(F.athlete_id.map(nm))
    F.drop(columns=["status"]).to_parquet(N + "future_rows.parquet", index=False)
    stamp = min(tips.values()).strftime("%Y%m%d")
    pd.DataFrame(inj_rows).to_csv(RUN + f"nba_injuries_{stamp}.csv", index=False)

    env = dict(os.environ, NBA_FUTURE=N + "future_rows.parquet", NBA_OUT=N + "nba_dataset_live.parquet")
    subprocess.run([sys.executable, N + "build_nba.py"], env=env, check=True)
    d = pd.read_parquet(N + "nba_dataset_live.parquet")
    d = d[d.event_id.isin(F.event_id.unique()) & d["min"].isna()].reset_index(drop=True)
    d = d.merge(F[["event_id", "athlete_id", "status"]], on=["event_id", "athlete_id"], how="left")
    d = E.add_predictions(d)
    # uncertainty: rotation teammates who are game-time decisions
    avg = d.set_index("athlete_id").avg5_fill
    gtd_min = d[d.status == "GTD"].groupby("team").avg5_fill.sum()

    rng = np.random.default_rng(11)
    out = []
    for f, lines in L.groupby("fixtureId"):
        if f not in fmap:
            continue
        g = fmap[f]
        gd = d[d.event_id == g["event_id"]].reset_index(drop=True)
        cands = list(zip(gd.athlete_id, gd.player))
        lines = lines.assign(athlete_id=[match(n, cands) for n in lines.player_name]).dropna(subset=["athlete_id"])
        if lines.empty:
            continue
        gd = gd[gd.athlete_id.isin(lines.athlete_id)].reset_index(drop=True)
        sims = E.simulate(gd, N=8000, rng=rng)
        idx = {a: i for i, a in enumerate(gd.athlete_id)}
        for r in lines.itertuples():
            i = idx[r.athlete_id]
            x = gd.iloc[i]
            p = E.p_over(sims, r.stat, i, r.line)
            bp = (1 / r.over_odds) / (1 / r.over_odds + 1 / r.under_odds)
            eo, eu = p - bp, (1 - p) - (1 - bp)
            team_unc = float(gtd_min.get(x.team, 0) - (x.avg5_fill if x.status == "GTD" else 0))
            flag = ""
            if max(eo, eu) >= 0.05 and x.status not in ("GTD", "LIKELY_OUT"):
                flag = "OVER" if eo > eu else "UNDER"
            tags = []
            if x.missing_min >= 15:
                tags.append("injury")
            out.append({"date": g["tip"].strftime("%Y-%m-%d"), "tipoff": g["tip"].isoformat(), "event_id": g["event_id"],
                        "fixtureId": f, "game": f"{g['home']} vs {g['away']}", "home": g["home"], "away": g["away"],
                        "athlete_id": r.athlete_id, "player": x.player, "book_name": r.player_name, "team": x.team, "opp": x.opp,
                        "stat": r.stat, "line": r.line, "over_odds": r.over_odds, "under_odds": r.under_odds, "book": "Stoiximan",
                        "book_P_over_novig": round(bp, 4), "model_P_over": round(p, 4),
                        "model_mean": round(float(sims[r.stat][i].mean()), 2),
                        "expected_minutes": round(float(x.m_median), 1), "min_low": round(float(x.m_q10), 1),
                        "min_high": round(float(x.m_q90), 1), "edge_over": round(eo, 4), "edge_under": round(eu, 4),
                        "flag": flag, "status": x.status, "team_uncertain_min": round(team_unc, 1),
                        "caution": "teammate game-time decision" if team_unc >= 20 else "", "tags": ",".join(tags),
                        "missing_min": round(float(x.missing_min), 1)})
    S_ = pd.DataFrame(out)
    S_.to_csv(RUN + f"nba_scored_{stamp}.csv", index=False)
    print(f"{len(S_)} NBA lines scored, {int((S_.flag != '').sum())} flagged ->", RUN + f"nba_scored_{stamp}.csv")
    return RUN + f"nba_scored_{stamp}.csv"


if __name__ == "__main__":
    main(sys.argv[1])
