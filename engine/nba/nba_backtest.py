"""Backtest the NBA model against Stoiximan's real NBA player-prop lines (2026-27 season to date).
Bet price: last price at least 6h before tip-off (or when first posted). Main line: over/under prices closest.
Model inputs use only earlier games; dressed roster = who ESPN listed for the game (known from the
official injury report before tip-off). NAIVE=1 instead assumes everyone from the last 3 games is available."""
import glob
import json
import os
import re
import sqlite3
import sys
import unicodedata

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/nba")
import nba_engine as E

O = "/home/claude/odds/"
NAIVE = os.environ.get("NAIVE") == "1"
mm = {str(x["marketId"]): x for x in json.load(open(O + "markets_basketball.json"))}
names = json.load(open(O + "player_names_all.json"))
fx = pd.read_parquet(O + "nba_fixtures.parquet").set_index("fixtureId")
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


def price_at(h, t):
    ok = [x for x in h if pd.Timestamp(x["createdAt"]) <= t]
    return ok[-1]["price"] if ok and ok[-1].get("active", True) else np.nan


rows = []
for p in glob.glob(O + "nba_hist/*.json"):
    f = os.path.basename(p)[:-5]
    if f not in fx.index:
        continue
    mk = json.load(open(p))["bookmakers"].get("stoiximan", {}).get("markets", {})
    tip = fx.loc[f, "startTime"]
    bet_t = tip - pd.Timedelta(hours=6)
    for m, v in mk.items():
        d = mm.get(m, {})
        st = STAT.get(d.get("marketType"))
        if not st:
            continue
        oi, ui = str(d["outcomes"][0]["outcomeId"]), str(d["outcomes"][1]["outcomeId"])
        ov, un = v["outcomes"].get(oi, {}).get("players", {}), v["outcomes"].get(ui, {}).get("players", {})
        for pid in set(ov) & set(un):
            oh, uh = ov[pid], un[pid]
            first = max(pd.Timestamp(oh[0]["createdAt"]), pd.Timestamp(uh[0]["createdAt"]))
            tb = bet_t if first <= bet_t else first
            if tb >= tip:
                continue
            rows.append({"fixtureId": f, "tipoff": tip, "player_oid": pid, "player_name": names.get(pid), "stat": st,
                         "line": d["handicap"], "over_bet": price_at(oh, tb), "under_bet": price_at(uh, tb),
                         "over_close": price_at(oh, tip - pd.Timedelta(minutes=1)),
                         "under_close": price_at(uh, tip - pd.Timedelta(minutes=1)), "posted_late": first > bet_t})
L = pd.DataFrame(rows).dropna(subset=["over_bet", "under_bet"])
L["gap"] = (L.over_bet - L.under_bet).abs()
L = L.sort_values("gap").groupby(["fixtureId", "player_oid", "stat"]).head(1).reset_index(drop=True)
print("main lines:", len(L), "games:", L.fixtureId.nunique(), "| margin:", round(float((1 / L.over_bet + 1 / L.under_bet - 1).mean()), 4))

# fixture -> ESPN event (US Eastern date + teams)
con = sqlite3.connect("/home/claude/nba/nba.db")
g = pd.read_sql("SELECT event_id, date, home, away FROM games WHERE season = 2026", con)
key = {(r.date, frozenset((r.home, r.away))): r.event_id for r in g.itertuples()}
fmap = {}
for f in L.fixtureId.unique():
    r = fx.loc[f]
    day = r.startTime.strftime("%Y-%m-%d")          # the ESPN table stores the UTC date of tip-off
    e = key.get((day, frozenset((ABBR.get(r.participant1Name), ABBR.get(r.participant2Name)))))
    if e:
        fmap[f] = e
L["event_id"] = L.fixtureId.map(fmap)
print("fixtures matched to ESPN:", L.dropna(subset=["event_id"]).fixtureId.nunique(), "/", L.fixtureId.nunique())

d = pd.read_parquet("/home/claude/nba/nba_dataset.parquet")
d = d[(d.season == 2026)].copy()
if NAIVE:   # do not use who was actually dressed: team minutes = rotation of the last 3 games
    d["team_min_available"] = d.team_min_available + d.missing_min
    d["teammate_min_share"] = d.avg5_fill / d.team_min_available.replace(0, np.nan)
    d["missing_min"] = 0.0
d = E.add_predictions(d)


def toks(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return [w for w in re.sub(r"[^A-Z ]", " ", s).split() if w not in ("JR", "SR", "II", "III", "IV")]


def match(name, cands):
    """bookmaker 'Surname, First' vs ESPN 'First Surname'"""
    if not isinstance(name, str):
        return None
    sur, _, first = name.partition(",")
    st, ft = toks(sur), toks(first)
    hits = [a for a, n in cands if st and " ".join(st) in " ".join(toks(n))]
    if len(hits) > 1 and ft:
        hits = [a for a, n in cands if a in hits and toks(n) and toks(n)[0][:3] == ft[0][:3]]
    return hits[0] if len(hits) == 1 else None


rng = np.random.default_rng(11)
out = []
for ev, lines in L.dropna(subset=["event_id"]).groupby("event_id"):
    gd = d[d.event_id == ev].reset_index(drop=True)
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
        actual = sum(x[s] for s in E.COMBO.get(r.stat, (r.stat,))) if x["min"] > 0 else np.nan
        out.append({**r._asdict(), "player": x.player, "team": x.team, "date": x.date,
                    "model_p_over": E.p_over(sims, r.stat, i, r.line), "model_mean": float(sims[r.stat][i].mean()),
                    "exp_minutes": float(x.m_median), "actual": actual})
B = pd.DataFrame(out).drop(columns=["Index"])
print("lines scored:", len(B), "share of lines matched:", round(len(B) / len(L), 3))

# ---------------- evaluation (same as EuroLeague)
B = B.dropna(subset=["actual"])
B = B[B.actual != B.line]
B["over"] = (B.actual > B.line).astype(int)
B["book_p"] = (1 / B.over_bet) / (1 / B.over_bet + 1 / B.under_bet)
B["edge_over"] = B.model_p_over - B.book_p
B["side"] = np.where(B.edge_over > 0, "over", "under")
B["edge"] = B.edge_over.abs()
B["odds"] = np.where(B.side == "over", B.over_bet, B.under_bet)
B["won"] = np.where(B.side == "over", B.over == 1, B.over == 0)
B["profit"] = np.where(B.won, B.odds - 1, -1.0)
B["close_book_p"] = (1 / B.over_close) / (1 / B.over_close + 1 / B.under_close)
B["clv"] = np.where(B.side == "over", B.close_book_p - B.book_p, B.book_p - B.close_book_p)
br = lambda p: float(np.mean((p - B.over) ** 2))
R = {"graded lines": len(B), "games": int(B.event_id.nunique()),
     "Brier model": round(br(B.model_p_over), 4), "Brier Stoiximan (no vig)": round(br(B.book_p), 4),
     "Brier blend 55/45": round(br(0.55 * B.model_p_over + 0.45 * B.book_p), 4), "by_edge": {}}


def boot(x, n=2000):
    r = np.random.default_rng(3)
    m = [x[r.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(100 * float(np.percentile(m, 2.5)), 1), round(100 * float(np.percentile(m, 97.5)), 1)]


for e in (0.03, 0.05, 0.08, 0.10, 0.15):
    s = B[B.edge >= e]
    if len(s) < 30:
        continue
    R["by_edge"][f">= {int(e * 100)}"] = {"bets": len(s), "win%": round(100 * s.won.mean(), 1),
                                          "ROI%": round(100 * s.profit.mean(), 1), "ROI 95%": boot(s.profit.to_numpy()),
                                          "overs%": round(100 * (s.side == "over").mean(), 1),
                                          "avg CLV pts": round(100 * s.clv.mean(), 2)}
s = B[B.edge >= 0.05]
R["edge>=5 by stat"] = s.groupby("stat").agg(bets=("won", "size"), win=("won", "mean"), roi=("profit", "mean")).round(3).to_dict("index")
R["edge>=5 by side"] = s.groupby("side").agg(bets=("won", "size"), win=("won", "mean"), roi=("profit", "mean")).round(3).to_dict("index")
R["always under ROI%"] = round(100 * float(np.where(B.over == 0, B.under_bet - 1, -1).mean()), 1)
R["always over ROI%"] = round(100 * float(np.where(B.over == 1, B.over_bet - 1, -1).mean()), 1)
suf = "_naive" if NAIVE else ""
B.to_csv(f"/home/claude/nba/nba_backtest_graded{suf}.csv", index=False)
json.dump(R, open(f"/home/claude/nba/nba_backtest_results{suf}.json", "w"), indent=1)
print(json.dumps(R, indent=1))

# ---------------- website summary (bootstrap resamples whole games, since lines in one game move together)
def cboot(x, n=2000):
    r = np.random.default_rng(5)
    gs = {g: v.profit.to_numpy() for g, v in x.groupby("event_id")}
    keys = list(gs)
    m = []
    for _ in range(n):
        pick = r.integers(0, len(keys), len(keys))
        v = np.concatenate([gs[keys[i]] for i in pick])
        m.append(v.mean())
    return [round(100 * float(np.percentile(m, 2.5)), 1), round(100 * float(np.percentile(m, 97.5)), 1)]


def row(x):
    return {"bets": int(len(x)), "win %": round(100 * x.won.mean(), 1), "break-even win %": round(100 * float((1 / x.odds).mean()), 1),
            "ROI %": round(100 * x.profit.mean(), 1), "ROI 95% range %": cboot(x), "avg CLV (pts)": round(100 * float(x.clv.mean()), 2)}


flag = B[B.edge >= 0.05]
top10 = flag.sort_values("edge", ascending=False).groupby("event_id").head(10)
B["week"] = pd.to_datetime(B.tipoff).dt.tz_convert("America/New_York").dt.to_period("W").astype(str)
site = {"lines graded": len(B), "games": int(B.event_id.nunique()),
        "from": str(pd.to_datetime(B.tipoff).min().date()), "to": str(pd.to_datetime(B.tipoff).max().date()),
        "bookmaker margin %": round(100 * float((1 / B.over_bet + 1 / B.under_bet - 1).mean()), 1),
        "accuracy (Brier, lower=better)": {"model": R["Brier model"], "Stoiximan at bet time": R["Brier Stoiximan (no vig)"],
                                           "blend 55/45": R["Brier blend 55/45"], "coin flip": 0.25},
        "strategies": {"Top 10 per game (the paper strategy)": row(top10), "Gap of 5+ points": row(flag),
                       "Gap of 10+ points": row(B[B.edge >= 0.10]), "Gap of 15+ points": row(B[B.edge >= 0.15])},
        "by stat (gap 5+)": {X: row(v) for X, v in flag.groupby(flag.stat.map({"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "Threes",
                                                                               "pr": "Pts+Reb", "pa": "Pts+Ast", "pra": "Pts+Reb+Ast", "ra": "Reb+Ast"}))},
        "by side (gap 5+)": {k.title(): row(v) for k, v in flag.groupby("side")},
        "by week (top 10 per game)": {k: row(v) for k, v in top10.assign(week=B.week).groupby("week")},
        "always under ROI %": R["always under ROI%"], "always over ROI %": R["always over ROI%"],
        "calibration (gap 5+): model chance vs actual win rate": flag.assign(
            b=pd.cut(np.where(flag.side == "over", flag.model_p_over, 1 - flag.model_p_over), [.5, .6, .65, .7, .75, 1]))
            .groupby("b", observed=True).agg(n=("won", "size"), model=("model_p_over", lambda s: 0), won=("won", "mean"))
            .drop(columns="model").round(3).reset_index().astype({"b": str}).to_dict("records")}
json.dump(site, open(f"/home/claude/nba/nba_backtest_site{suf}.json", "w"), indent=1)
print(json.dumps({k: site[k] for k in ("strategies", "by week (top 10 per game)", "calibration (gap 5+): model chance vs actual win rate")}, indent=1))
