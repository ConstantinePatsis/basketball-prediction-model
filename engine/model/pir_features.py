"""PIR per-minute rate features (EuroLeague Valuation + domestic efficiency ratings), prior games only."""
import bisect
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd


def add_pir_rates(df, db="/home/claude/basketball.db"):
    con = sqlite3.connect(db)
    g = pd.read_sql("SELECT Season, gameCode, date FROM el_games", con)
    g["gameCode"] = g.gameCode.astype(int)
    g["date"] = pd.to_datetime(g.date, format="%b %d, %Y")
    eb = pd.read_sql("SELECT Season, Gamecode, Player_ID, Minutes_float AS minutes, Valuation AS pir "
                     "FROM el_box", con).merge(g, left_on=["Season", "Gamecode"], right_on=["Season", "gameCode"])
    dg = pd.read_sql("SELECT league, season, game_id, date FROM dom_games", con)
    dbx = pd.read_sql("SELECT league, season, game_id, el_player_id AS Player_ID, minutes, rating AS pir "
                      "FROM dom_box WHERE el_player_id IS NOT NULL", con).merge(dg, on=["league", "season", "game_id"])
    dbx["date"] = pd.to_datetime(dbx.date, errors="coerce")
    dbx["pir"] = pd.to_numeric(dbx.pir, errors="coerce")
    dbx = dbx.dropna(subset=["date", "pir"])
    hist = defaultdict(dict)
    for src, d in (("EL", eb[eb.minutes.notna()]), ("DOM", dbx)):
        for pid, grp in d.sort_values("date").groupby("Player_ID"):
            hist[pid][src] = (grp.date.values.astype("datetime64[D]").astype(np.int64).tolist(),
                              grp[["minutes", "pir"]].to_numpy(float))

    def rate(pid, day, src, n):
        e = hist.get(pid, {}).get(src)
        if not e:
            return np.nan
        i = bisect.bisect_left(e[0], day)
        w = e[1][max(0, i - n):i]
        return w[:, 1].sum() / w[:, 0].sum() if len(w) and w[:, 0].sum() >= 1 else np.nan

    day = pd.to_datetime(df.date).values.astype("datetime64[D]").astype(np.int64)
    for src, n, tag in (("EL", 5, "el5"), ("EL", 15, "el15"), ("EL", 60, "el60"), ("DOM", 10, "dom10")):
        df[f"r_pir_{tag}"] = [rate(p, d, src, n) for p, d in zip(df.Player_ID, day)]
    return df
