import json, numpy as np, pandas as pd
B = pd.read_parquet("/home/claude/odds/backtest_lines" + __import__("os").environ.get("SUFFIX", "") + ".parquet")
B = B.dropna(subset=["actual"])
B = B[B.actual != B.line]                                          # .5 lines never push, guard anyway
io, iu = 1 / B.over_bet, 1 / B.under_bet
B["book_p"] = io / (io + iu)
B["over"] = (B.actual > B.line).astype(int)
co, cu = 1 / B.over_close, 1 / B.under_close
B["close_p"] = co / (co + cu)
y = B.over
br = lambda p: float(np.mean((p - y) ** 2))
ll = lambda p: float(-np.mean(y * np.log(np.clip(p, .01, .99)) + (1 - y) * np.log(1 - np.clip(p, .01, .99))))
out = {"lines graded": len(B), "games": int(B.fixtureId.nunique()), "share of lines that went over": round(float(y.mean()), 3),
       "accuracy (Brier, lower=better)": {"model": round(br(B.model_p_over), 4), "Stoiximan at bet time": round(br(B.book_p), 4),
                                          "Stoiximan at close": round(br(B.close_p.fillna(B.book_p)), 4), "coin flip": 0.25},
       "log loss": {"model": round(ll(B.model_p_over), 4), "Stoiximan": round(ll(B.book_p), 4)},
       "avg P(over) model / Stoiximan / actual": [round(float(B.model_p_over.mean()), 3), round(float(B.book_p.mean()), 3), round(float(y.mean()), 3)]}
# accuracy by stat
out["Brier by stat (model vs Stoiximan)"] = {s: [round(float(np.mean((x.model_p_over - x.over) ** 2)), 4), round(float(np.mean((x.book_p - x.over) ** 2)), 4), len(x)]
                                             for s, x in B.groupby("stat")}
# blend, tested out-of-sample: fit weight on first half of season, test on second half
from scipy.special import logit, expit
B = B.sort_values("tipoff"); half = B.tipoff.quantile(0.5)
A, T = B[B.tipoff <= half], B[B.tipoff > half]
best = None
for w in np.linspace(0, 1, 21):
    p = expit(w * logit(A.model_p_over.clip(.01, .99)) + (1 - w) * logit(A.book_p))
    s = np.mean((p - A.over) ** 2)
    if best is None or s < best[1]: best = (w, s)
w = best[0]; pT = expit(w * logit(T.model_p_over.clip(.01, .99)) + (1 - w) * logit(T.book_p))
out["blend (weight on model fitted on rounds 1-7, tested on later rounds)"] = {"model weight": round(float(w), 2),
    "Brier blend": round(float(np.mean((pT - T.over) ** 2)), 4), "Brier Stoiximan": round(float(np.mean((T.book_p - T.over) ** 2)), 4),
    "Brier model": round(float(np.mean((T.model_p_over - T.over) ** 2)), 4)}

def bets(df, p_col, edge):
    e_o = df[p_col] - df.book_p; e_u = (1 - df[p_col]) - (1 - df.book_p)
    side = np.where(e_o >= edge, "OVER", np.where(e_u >= edge, "UNDER", ""))
    b = df[side != ""].copy(); b["side"] = side[side != ""]
    b["odds"] = np.where(b.side == "OVER", b.over_bet, b.under_bet)
    b["won"] = np.where(b.side == "OVER", b.over == 1, b.over == 0)
    b["profit"] = np.where(b.won, b.odds - 1, -1.0)
    b["clv"] = np.where(b.side == "OVER", b.close_p - b.book_p, b.book_p - b.close_p)
    return b
def summ(b):
    if len(b) == 0: return {"bets": 0}
    gid = b.fixtureId.values; ug, inv = np.unique(gid, return_inverse=True)
    ps, cs = np.bincount(inv, b.profit), np.bincount(inv)
    rng = np.random.default_rng(0)
    bs = [ps[i].sum() / cs[i].sum() for i in (rng.integers(0, len(ug), len(ug)) for _ in range(2000))]
    return {"bets": len(b), "win %": round(100 * b.won.mean(), 1), "break-even win %": round(100 * (1 / b.odds).mean(), 1),
            "profit (units)": round(float(b.profit.sum()), 1), "ROI %": round(100 * b.profit.mean(), 1),
            "ROI 95% range %": [round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1)],
            "avg CLV (pts)": round(100 * float(b.clv.mean()), 2), "share of bets where line moved our way": round(float((b.clv > 0).mean()), 3)}
out["BETS: model edge >= 5 pts"] = summ(bets(B, "model_p_over", .05))
out["BETS: model edge >= 10 pts"] = summ(bets(B, "model_p_over", .10))
b5 = bets(B, "model_p_over", .05)
out["edge>=5 by side"] = {s: summ(x) for s, x in b5.groupby("side")}
out["edge>=5 by stat"] = {s: summ(x) for s, x in b5.groupby("stat")}
out["BETS on later rounds using the blend, edge >= 3 pts"] = summ(bets(T.assign(blend=pT), "blend", .03))
print(json.dumps(out, indent=1, default=str)); json.dump(out, open("/home/claude/odds/backtest_results" + __import__("os").environ.get("SUFFIX", "") + ".json", "w"), indent=1, default=str)
B.to_csv("/home/claude/odds/backtest_lines_graded" + __import__("os").environ.get("SUFFIX", "") + ".csv", index=False)
