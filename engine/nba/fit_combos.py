"""Fit the pts/reb/ast copula correlation and combo-market calibration on the 2024-25 validation season."""
import pickle
import sys

import numpy as np
import pandas as pd
from scipy.stats import nbinom, norm
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, "/home/claude/nba")
import nba_engine as E

d = pd.read_parquet("/home/claude/nba/nba_dataset.parquet")
v = d[(d.season == 2024) & (d["min"] > 0)].copy()
v = E.add_predictions(v)
cal = E.models()["cal"]
# correlation of PIT residuals given actual minutes
z = []
for s in ("pts", "reb", "ast"):
    lam = np.exp(v[f"lr_{s}"] + np.log(v["min"]))
    k = cal[s]["k"]
    u = (nbinom.cdf(v[s] - 1, k, k / (k + lam)) + nbinom.cdf(v[s], k, k / (k + lam))) / 2
    z.append(norm.ppf(np.clip(u, 1e-4, 1 - 1e-4)))
corr = np.corrcoef(np.vstack(z))
print("copula correlation pts/reb/ast:\n", corr.round(3))
cc = {"corr": corr}
pickle.dump(cc, open("/home/claude/nba/nba_calibration_combos.pkl", "wb"))
E._M.clear()
v = v.sample(min(len(v), 12000), random_state=1).reset_index(drop=True)
sims = E.simulate(v, N=3000)
for c, parts in E.COMBO.items():
    act = sum(v[p] for p in parts).to_numpy()
    mean = sims[c].mean(1)
    line = np.floor(mean + np.random.default_rng(2).normal(0, 1.5, len(v))) + 0.5   # lines around the expectation
    p = (sims[c] > line[:, None]).mean(1)
    o = (act > line).astype(int)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(p, o)
    cc[c] = iso
    print(c, "Brier raw", round(float(np.mean((p - o) ** 2)), 4), "calibrated", round(float(np.mean((iso.predict(p) - o) ** 2)), 4))
pickle.dump(cc, open("/home/claude/nba/nba_calibration_combos.pkl", "wb"))
