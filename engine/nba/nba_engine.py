"""Shared NBA simulation engine: minutes range x per-minute rates -> N simulated stat lines per player,
Gaussian copula linking points/rebounds/assists, isotonic calibration -> P(over line)."""
import json
import os
import pickle

import lightgbm as lgb
import numpy as np
from scipy.stats import nbinom, norm

D = os.environ.get("NBA_MODEL_DIR", "/home/claude/nba/")
COMBO = {"pr": ("pts", "reb"), "pa": ("pts", "ast"), "pra": ("pts", "reb", "ast"), "ra": ("reb", "ast")}
SINGLE = ("pts", "reb", "ast", "fg3m")
_M = {}


def models():
    if not _M:
        _M["min"] = {q: lgb.Booster(model_file=D + f"nba_minutes_{q}.txt") for q in ("median", "q10", "q90")}
        _M["rate"] = {s: lgb.Booster(model_file=D + f"nba_rate_{s}.txt") for s in SINGLE}
        _M["cal"] = pickle.load(open(D + "nba_calibration.pkl", "rb"))
        p = D + "nba_calibration_combos.pkl"
        _M["cc"] = pickle.load(open(p, "rb")) if os.path.exists(p) else {"corr": np.eye(3)}
    return _M


def add_predictions(d):
    M = models()
    for q, m in M["min"].items():
        d[f"m_{q}"] = m.predict(d[m.feature_name()])
    for s, m in M["rate"].items():
        d[f"lr_{s}"] = m.predict(d[m.feature_name()], raw_score=True)
    return d


def simulate(d, N=8000, rng=None, minutes_override=None):
    """d: rows with m_* and lr_* columns. Returns dict stat -> array (len(d), N)."""
    rng = rng or np.random.default_rng(11)
    M = models()
    med = d.m_median.to_numpy() if minutes_override is None else np.asarray(minutes_override, float)
    sd = np.clip((d.m_q90 - d.m_q10).to_numpy() / 2.563, 1, None)
    mins = np.clip(med[:, None] + sd[:, None] * rng.standard_normal((len(d), N)), 1, 48)
    zz = rng.standard_normal((len(d), N, 3)) @ np.linalg.cholesky(M["cc"]["corr"]).T
    sims = {"min": mins}
    for s in SINGLE:
        lam = np.exp(d[f"lr_{s}"].to_numpy()[:, None] + np.log(mins))
        k = M["cal"][s]["k"]
        if s in ("pts", "reb", "ast"):
            u = np.clip(norm.cdf(zz[:, :, ("pts", "reb", "ast").index(s)]), 1e-9, 1 - 1e-9)
            sims[s] = nbinom.ppf(u, k, k / (k + lam))
        else:
            sims[s] = rng.negative_binomial(k, k / (k + lam))
    for c, parts in COMBO.items():
        sims[c] = sum(sims[p] for p in parts)
    return sims


def p_over(sims, stat, i, line, raw=False):
    M = models()
    p = float((sims[stat][i] > line).mean())
    if raw:
        return p
    iso = M["cal"][stat]["iso"] if stat in M["cal"] else M["cc"].get(stat)
    return float(np.clip(iso.predict([p])[0], 0.01, 0.99)) if iso is not None else p
