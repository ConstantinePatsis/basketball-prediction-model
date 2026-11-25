"""Write the website's data files (web/data/*.json) from the engine's outputs."""
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

BASE = "/home/claude"
RUN = f"{BASE}/runner"
OUT = os.environ.get("SITE_DATA", os.path.join(os.path.dirname(os.path.realpath(BASE)), "web", "data"))
CET, ATH = ZoneInfo("Europe/Madrid"), ZoneInfo("Europe/Athens")
STAKE = 10.0
LABEL = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "Threes", "pr": "Pts+Reb",
         "pa": "Pts+Ast", "pra": "Pts+Reb+Ast", "ra": "Reb+Ast"}


def nice(name):
    """'TANASKOVIC, NIKOLA' -> 'Nikola Tanaskovic'"""
    import re
    parts = [x.strip() for x in str(name).split(",")]
    s = " ".join(reversed(parts)) if len(parts) == 2 else str(name)
    s = s.title()
    s = re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group(1).upper(), s)
    s = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), s)
    return s.replace(" Jr ", " Jr. ").replace("'S", "'s")


def latest(prefix):
    r = [int(f[len(prefix):-4]) for f in os.listdir(RUN) if f.startswith(prefix) and f.endswith(".csv")]
    return max(r) if r else None


def athens(t):
    try:
        return datetime.strptime(str(t).strip(), "%b %d, %Y %H:%M").replace(tzinfo=CET).astimezone(ATH).isoformat()
    except ValueError:
        return None


def clean(x):
    if isinstance(x, float) and (np.isnan(x) or np.isinf(x)):
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if np.isnan(x) else round(float(x), 4)
    return x


def records(df):
    return [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]


STAT_COLS = {"pts": ["Points"], "reb": ["TotalRebounds"], "ast": ["Assistances"], "fg3m": ["FieldGoalsMade3"],
             "pr": ["Points", "TotalRebounds"], "pa": ["Points", "Assistances"], "pra": ["Points", "TotalRebounds", "Assistances"],
             "ra": ["TotalRebounds", "Assistances"]}
WORD = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3m": "threes", "pr": "points + rebounds",
        "pa": "points + assists", "pra": "points + rebounds + assists", "ra": "rebounds + assists"}


def season_box(season):
    import sqlite3
    con = sqlite3.connect(f"{BASE}/euroleague.db")
    b = pd.read_sql("SELECT Gamecode, Team, Player_ID, Minutes_float, Points, TotalRebounds, Assistances, FieldGoalsMade3 "
                    "FROM player_boxscores WHERE Season = ?", con, params=(season,))
    g = pd.read_sql("SELECT gameCode AS Gamecode, date, homecode, awaycode FROM games WHERE Season = ?", con, params=(season,))
    g["Gamecode"] = pd.to_numeric(g.Gamecode)
    b = b.merge(g, on="Gamecode", how="left")
    b["Player_ID"] = b.Player_ID.astype(str).str.strip()
    b["opp"] = np.where(b.Team == b.homecode, b.awaycode, b.homecode)
    b["dt"] = pd.to_datetime(b.date, format="%b %d, %Y", errors="coerce")
    for k, cols in STAT_COLS.items():
        b[k] = b[cols].sum(axis=1)
    return b


def defence_ranks(b):
    """per team: average of each stat allowed to opponents per game; rank 1 = allows the most"""
    per_game = b.groupby(["Gamecode", "opp"])[list(STAT_COLS)].sum().reset_index()
    allowed = per_game.groupby("opp")[list(STAT_COLS)].mean()
    return allowed, allowed.rank(ascending=False, method="min").astype(int), len(allowed)


def reasons(l, logs, mins, allowed, ranks, nteams, out_mates, team_name):
    side_over = l["side"] == "OVER"
    word, line = WORD[l["stat"]], l["line"]
    r = []
    diff = l["model_mean"] - line
    r.append(f"The model expects {l['model_mean']:.1f} {word} against a line of {line:g} "
             f"({'+' if diff >= 0 else ''}{diff:.1f}).")
    if mins:
        lo, hi = mins.get("low"), mins.get("high")
        txt = f"Expected minutes: about {l['expected_minutes']:.0f}"
        if lo is not None and hi is not None:
            txt += f" (normal range {lo:.0f}–{hi:.0f})"
        if mins.get("season") is not None:
            txt += f", against {mins['season']:.1f} per game this season and {mins['last5']:.1f} over his last 5."
        r.append(txt)
    if logs:
        vals = [x["value"] for x in logs]
        hit = lambda v: (v > line) if side_over else (v < line)
        l5 = sum(hit(v) for v in vals[:5]); l10 = sum(hit(v) for v in vals[:10])
        r.append(f"Recent form: {'over' if side_over else 'under'} {line:g} in {l5} of his last {min(5, len(vals))} "
                 f"and {l10} of his last {min(10, len(vals))} games (average {np.mean(vals[:10]):.1f}).")
        pm = [x["value"] / x["min"] for x in logs[:5] if x["min"] > 0]
        pms = [x["value"] / x["min"] for x in logs if x["min"] > 0]
        if pm and pms and len(pms) >= 6:
            a, s_ = np.mean(pm), np.mean(pms)
            if abs(a / s_ - 1) >= 0.15:
                r.append(f"Per-minute production is {'up' if a > s_ else 'down'} lately: {a * 30:.1f} per 30 minutes "
                         f"over the last 5 games, against {s_ * 30:.1f} for the season.")
    opp = l["opp"]
    if opp in ranks.index:
        rk = int(ranks.loc[opp, l["stat"]])
        tone = "one of the most generous" if rk <= 4 else "one of the stingiest" if rk >= nteams - 3 else "about average"
        r.append(f"Matchup: {team_name(opp)} allow {allowed.loc[opp, l['stat']]:.1f} {word} per game to opponents, "
                 f"rank {rk} of {nteams} ({tone}).")
    if out_mates:
        r.append("Missing teammates: " + ", ".join(f"{p} ({m:.0f} min/game)" for p, m in out_mates) +
                 ". The model gives their minutes to the players who usually replace them.")
    if l.get("tags") and "after_hot_game" in str(l["tags"]):
        r.append("He is coming off a big game; the model weighs it lightly, as one game is mostly noise.")
    if l.get("tags") and "after_cold_game" in str(l["tags"]):
        r.append("He is coming off a quiet game; the model weighs it lightly, as one game is mostly noise.")
    r.append(f"Market: Stoiximan's odds imply {100 * l['book_p']:.0f}% for this side (margin removed); "
             f"the model says {100 * l['model_p']:.0f}%. Gap {100 * l['edge']:+.0f} points, "
             f"expected return {100 * l['ev']:+.0f}% per bet at {l['odds']:.2f}.")
    if l.get("status") in ("GTD", "LIKELY_OUT"):
        r.append("Caution: his own status is uncertain, so treat this as no bet until he is confirmed.")
    return r


TEAM_NAMES = {"MUN": "Bayern", "TEL": "Maccabi", "PAM": "Valencia", "PAN": "Panathinaikos", "ASV": "ASVEL", "MIL": "Milan",
              "BAR": "Barcelona", "ULK": "Fenerbahçe", "DUB": "Dubai", "PAR": "Partizan", "OLY": "Olympiacos",
              "HTA": "Hapoel Tel Aviv", "BAS": "Baskonia", "IST": "Anadolu Efes", "MAD": "Real Madrid", "ZAL": "Žalgiris",
              "RED": "Crvena Zvezda", "VIR": "Virtus", "PRS": "Paris", "BES": "Beşiktaş", "MCO": "Monaco"}


def team_name(c):
    return TEAM_NAMES.get(c, c)


def tier(edge):
    return "Strong" if edge >= 0.15 else "Good" if edge >= 0.10 else "Lean" if edge >= 0.05 else ""


def slate():
    rnd = latest("lines_scored_round")
    if rnd is None:
        return {"round": None, "games": []}
    s = pd.read_csv(f"{RUN}/lines_scored_round{rnd}.csv", dtype={"player_id": str}).dropna(subset=["model_P_over"])
    s["player_id"] = s.player_id.astype(str).str.strip()
    s["side"] = np.where(s.edge_over >= s.edge_under, "OVER", "UNDER")
    s["odds"] = np.where(s.side == "OVER", s.over_odds, s.under_odds)
    s["model_p"] = np.where(s.side == "OVER", s.model_P_over, 1 - s.model_P_over)
    s["book_p"] = np.where(s.side == "OVER", s.book_P_over_novig, 1 - s.book_P_over_novig)
    s["edge"] = s.model_p - s.book_p
    s["ev"] = s.model_p * s.odds - 1
    s["pick"] = s.flag.fillna("").astype(str).isin(["OVER", "UNDER"])
    s["stat_label"] = s.stat.map(LABEL)
    s["tier"] = np.where(s.pick, s.edge.map(tier), "")
    season = int(s.season.iloc[0])
    box = season_box(season)
    allowed, ranks, nteams = defence_ranks(box)
    proj = pd.read_csv(f"{RUN}/projections_round{rnd}.csv") if os.path.exists(f"{RUN}/projections_round{rnd}.csv") else pd.DataFrame()
    pmins = {(p, t): (lo, hi) for p, t, lo, hi in zip(proj.get("player", []), proj.get("team", []), proj.get("min_low", []), proj.get("min_high", []))}
    inj = pd.read_csv(f"{RUN}/injuries_round{rnd}.csv", dtype={"player_id": str}) if os.path.exists(f"{RUN}/injuries_round{rnd}.csv") else pd.DataFrame()
    avg_min = box[box.Minutes_float > 0].groupby("Player_ID").Minutes_float.mean()
    games = []
    for g, x in s.groupby("game"):
        home, away = g.split(" vs ")
        x = x.assign(opp=np.where(x.team == home, away, home))
        teams, out_by_team = {}, {}
        for t in (home, away):
            i = inj[(inj.team == t) & inj.status.isin(["OUT", "GTD", "LIKELY_OUT"])] if len(inj) else pd.DataFrame()
            teams[t] = [{"player": nice(p), "status": st, "min": clean(round(float(avg_min.get(str(pid).strip(), np.nan)), 1))}
                        for p, st, pid in zip(i.get("player", []), i.get("status", []), i.get("player_id", []))]
            out_by_team[t] = [(e["player"], e["min"]) for e in teams[t] if e["status"] == "OUT" and e["min"] and e["min"] >= 10]
        rows = []
        for l in x.sort_values("edge", ascending=False).to_dict("records"):
            pb = box[(box.Player_ID == l["player_id"]) & (box.Minutes_float > 0)].sort_values("dt", ascending=False)
            logs = [{"date": d.strftime("%d %b") if pd.notna(d) else "", "opp": o, "value": float(v), "min": round(float(m), 1)}
                    for d, o, v, m in zip(pb.dt, pb.opp, pb[l["stat"]], pb.Minutes_float)][:10]
            lo_hi = pmins.get((l["player"], l["team"]), (None, None))
            mins = {"low": lo_hi[0], "high": lo_hi[1],
                    "season": round(float(pb.Minutes_float.mean()), 1) if len(pb) else None,
                    "last5": round(float(pb.Minutes_float.head(5).mean()), 1) if len(pb) else None}
            hit = (lambda v: v > l["line"]) if l["side"] == "OVER" else (lambda v: v < l["line"])
            vals = [e["value"] for e in logs]
            rows.append({k: clean(v) for k, v in {
                "player": nice(l["player"]), "team": l["team"], "stat": l["stat"], "stat_label": l["stat_label"],
                "line": l["line"], "side": l["side"], "odds": l["odds"], "over_odds": l["over_odds"], "under_odds": l["under_odds"],
                "model_p": l["model_p"], "book_p": l["book_p"], "edge": l["edge"], "ev": l["ev"], "tier": l["tier"],
                "model_mean": l["model_mean"], "expected_minutes": l["expected_minutes"], "min_low": lo_hi[0], "min_high": lo_hi[1],
                "status": l["status"], "pick": bool(l["pick"]),
                "hit_l5": sum(hit(v) for v in vals[:5]), "n_l5": min(5, len(vals)),
                "hit_l10": sum(hit(v) for v in vals[:10]), "n_l10": min(10, len(vals)),
                "opp_rank": int(ranks.loc[l["opp"], l["stat"]]) if l["opp"] in ranks.index else None,
            }.items()} | {"logs": logs,
                          "reasons": reasons(l, logs, mins, allowed, ranks, nteams, out_by_team[l["team"]], team_name)})
        games.append({"id": f"{home}-{away}".lower(), "game": g, "home": home, "away": away,
                      "home_name": team_name(home), "away_name": team_name(away),
                      "tipoff": athens(x.tipoff.iloc[0]), "injuries": teams, "lines": rows, "n_teams": nteams})
    games.sort(key=lambda g: g["tipoff"] or "")
    return {"round": rnd, "games": games}


def results():
    f = f"{RUN}/paper_log.csv"
    if not os.path.exists(f):
        return {}
    l = pd.read_csv(f, dtype={"result": "object", "flag": "object"})
    l["side"] = l.bet_side.fillna("")
    bets = l[l.side.isin(["OVER", "UNDER"])].copy()
    bets["edge"] = np.where(bets.side == "OVER", bets.edge_over, bets.edge_under)
    settled = bets[bets.result.isin(["win", "loss"])].copy()
    settled["profit_eur"] = np.where(settled.result == "win", STAKE * (settled.bet_odds - 1), -STAKE)
    settled["tip_dt"] = pd.to_datetime(settled.tipoff, format="%b %d, %Y %H:%M", errors="coerce")

    def summ(x):
        if len(x) == 0:
            return {"bets": 0}
        w = int((x.result == "win").sum())
        return {"bets": int(len(x)), "wins": w, "losses": int(len(x) - w), "win_pct": round(100 * w / len(x), 1),
                "breakeven_pct": round(100 * float((1 / x.bet_odds).mean()), 1),
                "profit_eur": round(float(x.profit_eur.sum()), 2), "roi_pct": round(100 * float(x.profit_eur.sum()) / (STAKE * len(x)), 1)}

    daily = settled.groupby(settled.tip_dt.dt.date).profit_eur.sum().cumsum()
    graded = l[l.result.notna() & ~l.result.astype(str).str.startswith(("void", "push"))].copy()
    acc = {}
    if len(graded):
        y = (graded.actual > graded.line).astype(float)
        acc = {"lines": int(len(graded)), "brier_model": round(float(((graded.model_P_over - y) ** 2).mean()), 4),
               "brier_stoiximan": round(float(((graded.book_P_over_novig - y) ** 2).mean()), 4)}
    recent = settled.sort_values("tip_dt", ascending=False).head(150)
    recent = recent.assign(player=recent.player.map(nice), stat_label=recent.stat.map(LABEL))
    return {
        "stake_eur": STAKE,
        "overall": summ(settled),
        "pending": int(bets.result.isna().sum()),
        "voids": int(bets.result.astype(str).str.startswith("void").sum()),
        "by_stat": {LABEL.get(k, k): summ(v) for k, v in settled.groupby("stat")},
        "by_side": {k.title(): summ(v) for k, v in settled.groupby("side")},
        "by_edge": {k: summ(v) for k, v in settled.groupby(pd.cut(settled.edge, [0, .1, .2, 1], labels=["5-10", "10-20", "20+"]), observed=True)},
        "by_tag": {k: summ(v) for k, v in settled.assign(t=settled.tags.fillna("plain").str.split(",")).explode("t").groupby("t")},
        "cumulative": [{"date": "start", "profit_eur": 0.0}] + [{"date": str(d), "profit_eur": round(float(v), 2)} for d, v in daily.items()],
        "accuracy": acc,
        "recent": records(recent[["tipoff", "game", "player", "team", "stat_label", "line", "side", "bet_odds", "actual",
                                  "result", "profit_eur", "edge"]]),
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    data = {"slate": slate(), "results": results(),
            "updated_at": datetime.now(timezone.utc).astimezone(ATH).isoformat(timespec="minutes")}
    bt = f"{BASE}/odds/backtest_results.json"
    if os.path.exists(bt):
        data["backtest"] = json.load(open(bt))
    for k, v in data.items():
        json.dump(v, open(os.path.join(OUT, f"{k}.json"), "w"), indent=1, default=str)
    print("site data written to", OUT, {k: (len(v["games"]) if k == "slate" else "") for k, v in data.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
