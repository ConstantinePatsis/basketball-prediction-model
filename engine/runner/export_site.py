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
    parts = [x.strip() for x in str(name).split(",")]
    return " ".join(reversed(parts)).title() if len(parts) == 2 else str(name).title()


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


def slate():
    rnd = latest("lines_scored_round")
    if rnd is None:
        return {"round": None, "games": []}
    s = pd.read_csv(f"{RUN}/lines_scored_round{rnd}.csv").dropna(subset=["model_P_over"])
    s["side"] = np.where(s.edge_over >= s.edge_under, "OVER", "UNDER")
    s["odds"] = np.where(s.side == "OVER", s.over_odds, s.under_odds)
    s["model_p"] = np.where(s.side == "OVER", s.model_P_over, 1 - s.model_P_over)
    s["book_p"] = np.where(s.side == "OVER", s.book_P_over_novig, 1 - s.book_P_over_novig)
    s["edge"] = s.model_p - s.book_p
    s["pick"] = s.flag.fillna("").astype(str).ne("") & s.flag.astype(str).ne("nan")
    s["stat_label"] = s.stat.map(LABEL)
    inj = pd.read_csv(f"{RUN}/injuries_round{rnd}.csv") if os.path.exists(f"{RUN}/injuries_round{rnd}.csv") else pd.DataFrame()
    games = []
    for g, x in s.groupby("game"):
        home, away = g.split(" vs ")
        teams = {}
        for t in (home, away):
            i = inj[(inj.team == t) & inj.status.isin(["OUT", "GTD", "LIKELY_OUT"])] if len(inj) else pd.DataFrame()
            teams[t] = [{"player": nice(p), "status": st} for p, st in zip(i.get("player", []), i.get("status", []))]
        x = x.sort_values("edge", ascending=False)
        cols = ["player", "team", "stat", "stat_label", "line", "side", "odds", "over_odds", "under_odds", "model_p", "book_p",
                "edge", "model_mean", "expected_minutes", "status", "tags", "caution", "pick"]
        games.append({"game": g, "home": home, "away": away, "tipoff": athens(x.tipoff.iloc[0]),
                      "injuries": teams, "lines": records(x[cols].assign(player=x.player.map(nice)))})
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
