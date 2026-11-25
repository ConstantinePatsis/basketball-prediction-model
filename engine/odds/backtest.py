"""Backtest the model against Stoiximan's real player-prop lines, 2026-27 rounds 1-13.
For each main line: model P(over) (same engine as predict_round: minutes range x per-minute rates x 8000 sims,
copula for pts/reb/ast, isotonic calibration) vs Stoiximan's no-vig probability at bet time (6h before tip-off).
Bets: model beats the no-vig price by >= EDGE. Graded with official box scores. Paper money only."""
import json, pickle, re, sqlite3, sys, unicodedata
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import nbinom, norm

rng = np.random.default_rng(11)
MODEL = "/home/claude/model"
L = pd.read_parquet("/home/claude/odds/stoiximan_main_lines.parquet")
fx = pd.read_parquet("/home/claude/odds/el_fixtures.parquet").set_index("fixtureId")

def toks(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return set(w for w in re.sub(r"[^A-Z ]", " ", s).split() if len(w) > 1)

# ---- fixture -> EuroLeague gamecode (same date, best team-name overlap)
con = sqlite3.connect("/home/claude/euroleague.db")
g = pd.read_sql("SELECT gameCode, date, hometeam, awayteam, homecode, awaycode FROM games WHERE Season = 2026", con)
g["d"] = pd.to_datetime(g.date, format="%b %d, %Y", errors="coerce").dt.date
ALIAS = {"OLYMPIAKOS": "OLYMPIACOS", "MILANO": "MILAN", "FENERBAHCE": "FENERBAHCE", "ZVEZDA": "ZVEZDA", "TEL": "TEL", "AVIV": "AVIV"}
fmap = {}
for f in L.fixtureId.unique():
    r = fx.loc[f]; d = r.startTime.date()
    a = {ALIAS.get(w, w) for w in toks(r.participant1Name)}; b = {ALIAS.get(w, w) for w in toks(r.participant2Name)}
    best, sc = None, 0
    for x in g[g.d == d].itertuples():
        s = len(a & toks(x.hometeam)) + len(b & toks(x.awayteam))
        if s > sc: best, sc = x, s
    if best is not None and sc >= 2:
        fmap[f] = int(best.gameCode)
L["Gamecode"] = L.fixtureId.map(fmap)
print("fixtures matched:", L.dropna(subset=["Gamecode"]).fixtureId.nunique(), "/", L.fixtureId.nunique())

# ---- model inputs for those games (pre-game features)
d = pd.read_parquet(f"{MODEL}/rates_dataset.parquet")
d = d[d.Season == 2026].copy(); d["round"] = pd.to_numeric(d["round"], errors="coerce"); d["starter_rate"] = d.season_start_rate
d["Player_ID"] = d.Player_ID.astype(str).str.strip()
sys.path.insert(0, MODEL)
from pir_features import add_pir_rates  # noqa
import os
if os.environ.get("NAIVE") == "1":
    # pessimistic: the model does NOT know who dressed; rotation = everyone who played in the team's last 3 games
    md = pd.read_parquet(f"{MODEL}/minutes_dataset.parquet"); md = md[md.Season == 2026].copy()
    md["Player_ID"] = md.Player_ID.astype(str).str.strip(); md = md.sort_values("date")
    md["avg5_now"] = md.groupby("Player_ID").minutes.transform(lambda x: x.shift().rolling(5, 1).mean()).fillna(0)
    played = md[md.minutes > 0].groupby(["Team", "Gamecode"]).Player_ID.apply(set).to_dict()
    tgs = md[["Team", "Gamecode", "date"]].drop_duplicates().sort_values("date")
    hist = {p: x[["date", "minutes"]].values for p, x in md.groupby("Player_ID")}
    def a5(p, day):
        h = hist.get(p); 
        if h is None: return 0.0
        h = h[h[:, 0] < day][-5:, 1]; return float(np.mean(h)) if len(h) else 0.0
    naive = {}
    for t, x in tgs.groupby("Team"):
        codes, dates = list(x.Gamecode), list(x.date)
        for i, (gc, day) in enumerate(zip(codes, dates)):
            if i >= 3:
                rot = set().union(*[played.get((t, c), set()) for c in codes[i-3:i]])
                naive[(t, gc)] = sum(a5(p, day) for p in rot)
    tma = [naive.get((t, gc), np.nan) for t, gc in zip(d.Team, d.Gamecode)]
    d["team_min_available"] = pd.Series(tma, index=d.index).fillna(d.team_min_available)
    d["teammate_min_share"] = d.el_avg5 / d.team_min_available.replace(0, np.nan)
for q in ("median", "q10", "q90"):
    m = lgb.Booster(model_file=f"{MODEL}/minutes_{q}.txt"); d[f"m_{q}"] = m.predict(d[m.feature_name()])
for s in ("pts", "reb", "ast", "fg3m"):
    m = lgb.Booster(model_file=f"{MODEL}/rate_{s}.txt"); d[f"lr_{s}"] = m.predict(d[m.feature_name()], raw_score=True)
calib = pickle.load(open(f"{MODEL}/calibration.pkl", "rb")); cc = pickle.load(open(f"{MODEL}/calibration_combos.pkl", "rb"))
box = pd.read_sql("SELECT Gamecode, Player_ID, Player, Minutes_float, Points, TotalRebounds, Assistances, FieldGoalsMade3 "
                  "FROM player_boxscores WHERE Season = 2026", con)
box["Player_ID"] = box.Player_ID.str.strip()

# ---- player name matching within the game (bookmaker 'Surname, First' vs EuroLeague 'SURNAME, FIRST')
def match(name, cands):
    if not isinstance(name, str) or not name: return None
    k = toks(name.split(",")[0]); full = toks(name)
    hits = [c for c in cands if k and k <= toks(c[1].split(",")[0])]
    if len(hits) > 1: hits = [c for c in hits if full <= toks(c[1])] or hits[:0]
    return hits[0][0] if len(hits) == 1 else None

COMBO = {"pr": ("pts", "reb"), "pa": ("pts", "ast"), "pra": ("pts", "reb", "ast"), "ra": ("reb", "ast")}
N = 8000
out = []
for gc, lines in L.dropna(subset=["Gamecode"]).groupby("Gamecode"):
    gd = d[d.Gamecode == gc]
    cands = list(zip(gd.Player_ID, gd.Player))
    lines = lines.assign(Player_ID=[match(n, cands) for n in lines.player_name])
    lines = lines.dropna(subset=["Player_ID"])
    if lines.empty: continue
    gd = gd[gd.Player_ID.isin(lines.Player_ID)].reset_index(drop=True)
    sd = np.clip((gd.m_q90 - gd.m_q10).to_numpy() / 2.563, 1, None)
    mins = np.clip(gd.m_median.to_numpy()[:, None] + sd[:, None] * rng.standard_normal((len(gd), N)), 1, 48)
    zz = rng.standard_normal((len(gd), N, 3)) @ np.linalg.cholesky(cc["corr"]).T
    sims = {}
    for s in ("pts", "reb", "ast", "fg3m"):
        lam = np.exp(gd[f"lr_{s}"].to_numpy()[:, None] + np.log(mins)); k = calib[s]["k"]
        if s in ("pts", "reb", "ast"):
            sims[s] = nbinom.ppf(norm.cdf(zz[:, :, ("pts", "reb", "ast").index(s)]), k, k / (k + lam))
        else:
            sims[s] = rng.negative_binomial(k, k / (k + lam)) if k < 1e5 else rng.poisson(lam)
    for c, parts in COMBO.items():
        sims[c] = sum(sims[p] for p in parts)
    idx = {p: i for i, p in enumerate(gd.Player_ID)}
    bx = box[box.Gamecode == gc].set_index("Player_ID")
    for r in lines.itertuples():
        i = idx[r.Player_ID]
        p_raw = float((sims[r.stat][i] > r.line).mean())
        iso = calib[r.stat]["iso"] if r.stat in calib else cc[r.stat]
        p = float(np.clip(iso.predict([p_raw])[0], 0.01, 0.99))
        if r.Player_ID in bx.index and bx.loc[r.Player_ID, "Minutes_float"] > 0:
            b = bx.loc[r.Player_ID]
            vals = {"pts": b.Points, "reb": b.TotalRebounds, "ast": b.Assistances, "fg3m": b.FieldGoalsMade3}
            actual = sum(vals[x] for x in COMBO.get(r.stat, (r.stat,)))
        else:
            actual = np.nan                                     # did not play -> bet void
        out.append({**r._asdict(), "model_p_over": p, "model_mean": float(sims[r.stat][i].mean()),
                    "exp_minutes": float(gd.m_median[i]), "actual": actual})
B = pd.DataFrame(out).drop(columns=["Index"])
B.to_parquet("/home/claude/odds/backtest_lines" + ("_naive" if os.environ.get("NAIVE") == "1" else "") + ".parquet", index=False)
print("lines scored:", len(B), "| players matched:", round(len(B) / len(L), 3))
