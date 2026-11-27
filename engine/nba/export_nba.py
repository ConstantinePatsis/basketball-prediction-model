"""Website data for the NBA section: web/data/nba_slate.json, nba_results.json, nba_backtest.json."""
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/runner")
import export_site as X  # noqa: E402  (shared helpers: reasons, tier, clean, records, OUT, LABEL)

N = "/home/claude/nba/"
RUN = "/home/claude/runner/"
STAKE = 10.0
NAMES = {"ATL": "Hawks", "BOS": "Celtics", "BKN": "Nets", "CHA": "Hornets", "CHI": "Bulls", "CLE": "Cavaliers",
         "DAL": "Mavericks", "DEN": "Nuggets", "DET": "Pistons", "GS": "Warriors", "HOU": "Rockets", "IND": "Pacers",
         "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIA": "Heat", "MIL": "Bucks", "MIN": "Timberwolves",
         "NO": "Pelicans", "NY": "Knicks", "OKC": "Thunder", "ORL": "Magic", "PHI": "76ers", "PHX": "Suns",
         "POR": "Trail Blazers", "SAC": "Kings", "SA": "Spurs", "TOR": "Raptors", "UTAH": "Jazz", "WSH": "Wizards"}
team_name = lambda c: NAMES.get(c, c)
STATS = {"pts": ["pts"], "reb": ["reb"], "ast": ["ast"], "fg3m": ["fg3m"], "pr": ["pts", "reb"], "pa": ["pts", "ast"],
         "pra": ["pts", "reb", "ast"], "ra": ["reb", "ast"]}


def season_box():
    con = sqlite3.connect(N + "nba.db")
    b = pd.read_sql("SELECT b.event_id, b.team, b.athlete_id, b.player, b.min, b.pts, b.reb, b.ast, b.fg3m, g.date, g.home, g.away "
                    "FROM box b JOIN games g USING(event_id) WHERE g.season = 2026", con)
    b = b[b.event_id.isin(b.groupby("event_id").pts.sum().loc[lambda s: s > 0].index)]
    b["opp"] = np.where(b.team == b.home, b.away, b.home)
    b["dt"] = pd.to_datetime(b.date)
    for k, c in STATS.items():
        b[k] = b[c].sum(axis=1)
    return b


def slate():
    files = sorted(glob.glob(RUN + "nba_scored_*.csv"))
    if not files:
        return {"date": None, "games": []}
    s = pd.read_csv(files[-1], dtype={"athlete_id": str, "event_id": str})
    s = s[pd.to_datetime(s.tipoff, utc=True) > pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=14)]
    if s.empty:
        return {"date": None, "games": []}
    s["side"] = np.where(s.edge_over >= s.edge_under, "OVER", "UNDER")
    s["odds"] = np.where(s.side == "OVER", s.over_odds, s.under_odds)
    s["model_p"] = np.where(s.side == "OVER", s.model_P_over, 1 - s.model_P_over)
    s["book_p"] = np.where(s.side == "OVER", s.book_P_over_novig, 1 - s.book_P_over_novig)
    s["edge"] = s.model_p - s.book_p
    s["ev"] = s.model_p * s.odds - 1
    s["pick"] = s.flag.fillna("").isin(["OVER", "UNDER"])
    s["stat_label"] = s.stat.map(X.LABEL)
    s["tier"] = np.where(s.pick, s.edge.map(X.tier), "")
    box = season_box()
    per = box.groupby(["event_id", "opp"])[list(STATS)].sum().reset_index()
    allowed = per.groupby("opp")[list(STATS)].mean()
    ranks = allowed.rank(ascending=False, method="min").astype(int)
    nteams = len(allowed)
    avg_min = box[box["min"] > 0].groupby("athlete_id")["min"].mean()
    inj = pd.concat([pd.read_csv(f, dtype={"athlete_id": str, "event_id": str}) for f in glob.glob(RUN + "nba_injuries_*.csv")[-3:]]) \
        if glob.glob(RUN + "nba_injuries_*.csv") else pd.DataFrame(columns=["event_id", "team", "athlete_id", "player", "status"])
    logged = pd.read_csv(RUN + "nba_paper_log.csv", dtype={"event_id": str, "athlete_id": str}) if os.path.exists(RUN + "nba_paper_log.csv") else pd.DataFrame()
    logged_keys = set(zip(logged.event_id, logged.athlete_id, logged.stat)) if len(logged) else set()
    games = []
    for ev, x in s.groupby("event_id"):
        home, away = x.home.iloc[0], x.away.iloc[0]
        teams, outs = {}, {}
        for t in (home, away):
            i = inj[(inj.event_id == ev) & (inj.team == t) & inj.status.isin(["OUT", "GTD", "LIKELY_OUT"])].drop_duplicates("athlete_id")
            teams[t] = [{"player": p, "status": st, "min": X.clean(round(float(avg_min.get(a, np.nan)), 1))}
                        for p, st, a in zip(i.player, i.status, i.athlete_id)]
            outs[t] = [(e["player"], e["min"]) for e in teams[t] if e["status"] == "OUT" and e["min"] and e["min"] >= 12]
        rows = []
        for l in x.sort_values("edge", ascending=False).to_dict("records"):
            pb = box[(box.athlete_id == l["athlete_id"]) & (box["min"] > 0)].sort_values("dt", ascending=False)
            logs = [{"date": d.strftime("%d %b"), "opp": o, "value": float(v), "min": round(float(m), 1)}
                    for d, o, v, m in zip(pb.dt, pb.opp, pb[l["stat"]], pb["min"])][:10]
            mins = {"low": l["min_low"], "high": l["min_high"],
                    "season": round(float(pb["min"].mean()), 1) if len(pb) else None,
                    "last5": round(float(pb["min"].head(5).mean()), 1) if len(pb) else None}
            hit = (lambda v: v > l["line"]) if l["side"] == "OVER" else (lambda v: v < l["line"])
            vals = [e["value"] for e in logs]
            l["tags"] = l.get("tags") if isinstance(l.get("tags"), str) else ""
            rs = X.reasons(l, logs, mins, allowed, ranks, nteams, outs[l["team"]], team_name)
            if isinstance(l.get("caution"), str) and l["caution"]:
                rs.append("Caution: a regular teammate is a game-time decision, so his minutes could change.")
            rows.append({k: X.clean(v) for k, v in {
                "player": l["player"], "team": l["team"], "stat": l["stat"], "stat_label": l["stat_label"], "line": l["line"],
                "side": l["side"], "odds": l["odds"], "over_odds": l["over_odds"], "under_odds": l["under_odds"],
                "model_p": l["model_p"], "book_p": l["book_p"], "edge": l["edge"], "ev": l["ev"], "tier": l["tier"],
                "model_mean": l["model_mean"], "expected_minutes": l["expected_minutes"], "min_low": l["min_low"],
                "min_high": l["min_high"], "status": l["status"], "pick": bool(l["pick"]),
                "logged": (ev, l["athlete_id"], l["stat"]) in logged_keys,
                "hit_l5": sum(hit(v) for v in vals[:5]), "n_l5": min(5, len(vals)),
                "hit_l10": sum(hit(v) for v in vals[:10]), "n_l10": min(10, len(vals)),
                "opp_rank": int(ranks.loc[l["opp"], l["stat"]]) if l["opp"] in ranks.index else None}.items()}
                | {"logs": logs, "reasons": rs})
        games.append({"id": f"{home}-{away}".lower(), "game": f"{home} vs {away}", "home": home, "away": away,
                      "home_name": team_name(home), "away_name": team_name(away),
                      "tipoff": pd.Timestamp(x.tipoff.iloc[0]).tz_convert("Europe/Athens").isoformat(),
                      "injuries": teams, "lines": rows, "n_teams": nteams})
    games.sort(key=lambda g: g["tipoff"])
    return {"date": files[-1][-12:-4], "games": games}


def results():
    f = RUN + "nba_paper_log.csv"
    if not os.path.exists(f):
        return {}
    l = pd.read_csv(f, dtype={"result": object})
    for c in ("result", "actual"):
        if c not in l:
            l[c] = np.nan
    st = l[l.result.isin(["win", "loss"])].copy()
    st["profit_eur"] = np.where(st.result == "win", STAKE * (st.bet_odds - 1), -STAKE)
    st["tip_dt"] = pd.to_datetime(st.tipoff, utc=True).dt.tz_convert("America/New_York")

    def summ(x):
        if len(x) == 0:
            return {"bets": 0}
        w = int((x.result == "win").sum())
        return {"bets": int(len(x)), "wins": w, "losses": int(len(x) - w), "win_pct": round(100 * w / len(x), 1),
                "breakeven_pct": round(100 * float((1 / x.bet_odds).mean()), 1),
                "profit_eur": round(float(x.profit_eur.sum()), 2), "roi_pct": round(100 * float(x.profit_eur.sum()) / (STAKE * len(x)), 1)}

    daily = st.groupby(st.tip_dt.dt.date).profit_eur.sum().cumsum()
    g = st.copy()
    acc = {}
    if len(g):
        y = (g.actual > g.line).astype(float)
        acc = {"lines": int(len(g)), "brier_model": round(float(((g.model_P_over - y) ** 2).mean()), 4),
               "brier_stoiximan": round(float(((g.book_P_over_novig - y) ** 2).mean()), 4)}
    recent = st.sort_values("tip_dt", ascending=False).head(150)
    recent = recent.assign(stat_label=recent.stat.map(X.LABEL), side=recent.bet_side)
    return {"stake_eur": STAKE, "overall": summ(st), "pending": int(l.result.isna().sum()),
            "voids": int(l.result.astype(str).str.startswith("void").sum()),
            "by_stat": {X.LABEL.get(k, k): summ(v) for k, v in st.groupby("stat")},
            "by_side": {k.title(): summ(v) for k, v in st.groupby("bet_side")},
            "by_edge": {k: summ(v) for k, v in st.groupby(pd.cut(st.edge, [0, .1, .2, 1], labels=["5-10", "10-20", "20+"]), observed=True)},
            "cumulative": [{"date": "start", "profit_eur": 0.0}] + [{"date": str(d), "profit_eur": round(float(v), 2)} for d, v in daily.items()],
            "accuracy": acc,
            "recent": X.records(recent[["tipoff", "game", "player", "team", "stat_label", "line", "side", "bet_odds", "actual",
                                        "result", "profit_eur", "edge"]])}


def main():
    os.makedirs(X.OUT, exist_ok=True)
    data = {"nba_slate": slate(), "nba_results": results()}
    if os.path.exists(N + "nba_backtest_site.json"):
        data["nba_backtest"] = json.load(open(N + "nba_backtest_site.json"))
    for k, v in data.items():
        json.dump(v, open(os.path.join(X.OUT, f"{k}.json"), "w"), indent=1, default=str)
    print("NBA site data written:", {k: len(v.get("games", [])) if k == "nba_slate" else "" for k, v in data.items()})


if __name__ == "__main__":
    main()
