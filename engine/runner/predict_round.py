"""Project the next EuroLeague round: minutes, stat distributions, P(over) for lines.

Usage:
    python3 predict_round.py                 # next unplayed round
    python3 predict_round.py --round 12
Inputs (optional, in /home/claude/runner):
    injuries_round{R}.csv  official EuroLeague injury report, parsed (fetched automatically)
    outs.csv   manual override, one player per line (name as on EuroLeague, e.g. "SLOUKAS"), players ruled out
    lines.csv  player,stat,line,over_odds,under_odds   (stat: pts|reb|ast|fg3m|pra|pr|pa|ra|pir, decimal odds)
Outputs:
    projections_round{R}.csv   per player: minutes range, mean/median per stat, fair lines
    lines_scored_round{R}.csv  per line: model P(over/under), vig-free book P, edge, flag
"""
import argparse
import os
import pickle
import re
import subprocess
import sys
import unicodedata

import lightgbm as lgb
import numpy as np
import pandas as pd
from euroleague_api.schedule import Schedule

RUN = "/home/claude/runner"
MODEL = "/home/claude/model"
TMP = f"{RUN}/tmp"
STATS = ["pts", "reb", "ast", "fg3m"]
COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
LABEL = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3m": "threes", "pra": "pts+reb+ast",
         "pr": "pts+reb", "pa": "pts+ast", "ra": "reb+ast", "pir": "PIR"}
EDGE_MIN = 0.05                     # flag only if model P exceeds the vig-free book P by 5+ points
rng = np.random.default_rng(11)

MIN_FEATS = ["home", "playoff", "round", "el_last1", "el_avg3", "el_avg5", "el_avg10", "el_std5",
             "el_games_career", "prev_season_avg", "season_games", "season_avg", "season_start_rate",
             "start_rate5", "last_start", "trend", "team_net10", "opp_net10", "exp_margin",
             "abs_exp_margin", "team_min_available", "teammate_min_share", "days_since_el",
             "days_since_any", "min_last3d", "min_last7d", "games_last7d", "min_last14d",
             "dom_avg5", "dom_games_last7d", "has_dom_data"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z ]", " ", s).split()


def name_key(s):
    """'SLOUKAS, KOSTAS' / 'Kostas Sloukas' / 'Sloukas' -> set of name tokens."""
    return set(norm(s.replace(",", " ")))


def build_future(season, rnd):
    import sqlite3
    sched = Schedule("E").get_schedule(season)
    sched["played"] = sched.played.astype(str).str.lower().isin(["true", "1"])
    sched["gameday"] = sched.gameday.astype(int)
    upcoming = sched[~sched.played]
    if upcoming.empty:
        sys.exit("No unplayed games in the schedule.")
    rnd = rnd or int(upcoming.gameday.min())
    games = sched[sched.gameday == rnd].copy()
    games = games[~games.played]
    fg = pd.DataFrame({"Season": season, "gameCode": games.game.astype(int), "date": games.date,
                       "Phase": games["round"], "Round": games.gameday.astype(str),
                       "homecode": games.homecode, "awaycode": games.awaycode,
                       "homescore": np.nan, "awayscore": np.nan, "startime": games.startime.values})

    con = sqlite3.connect("/home/claude/euroleague.db")
    box = pd.read_sql("SELECT Season, Gamecode, Team, Player_ID, Player, Minutes_float FROM player_boxscores "
                      "WHERE Season = ?", con, params=(season,))
    outs = []
    if os.path.exists(f"{RUN}/outs.csv"):
        outs = [name_key(l) for l in open(f"{RUN}/outs.csv") if l.strip()]

    # official injury report -> status per player (OUT / GTD / AVAILABLE / NO_REPORT / UNLISTED)
    import injuries
    teams = {**dict(zip(games.homecode, games.hometeam)), **dict(zip(games.awaycode, games.awayteam))}
    season_pool = box.drop_duplicates(["Team", "Player_ID"])
    rosters = {t: list(season_pool[season_pool.Team == t][["Player_ID", "Player"]].itertuples(index=False, name=None))
               for t in teams}
    status = {}
    if os.environ.get("NO_INJURIES") != "1":
        try:
            av, url = injuries.get_availability(season, rnd, teams, rosters)
            if url:
                av.to_csv(f"{RUN}/injuries_round{rnd}.csv", index=False)
                status = dict(zip(av.player_id, av.status))
                print(f"Injury report: {url}")
                print(av.status.value_counts().to_string())
            else:
                print("Injury report for this round not found - using last-3-games rosters only.")
        except Exception as e:
            print(f"Injury report unavailable ({e}) - using last-3-games rosters only.")

    rows = []
    for g in fg.itertuples():
        for team, home in ((g.homecode, 1), (g.awaycode, 0)):
            tb = box[box.Team == team]
            last3 = sorted(tb.Gamecode.unique())[-3:]
            roster = (tb[tb.Gamecode.isin(last3) & (tb.Minutes_float > 0)]
                      .drop_duplicates("Player_ID")[["Player_ID", "Player"]])
            # players the report says are back (returning from injury) join the rotation
            back = [pid for pid, st in status.items() if st == "AVAILABLE" and pid not in set(roster.Player_ID)]
            back = season_pool[(season_pool.Team == team) & season_pool.Player_ID.isin(back)][["Player_ID", "Player"]]
            roster = pd.concat([roster, back]).drop_duplicates("Player_ID")
            for p in roster.itertuples():
                st = status.get(p.Player_ID, "UNLISTED")
                if st == "OUT" or any(o and o <= name_key(p.Player) for o in outs):
                    continue
                rows.append({"Season": season, "Gamecode": g.gameCode, "Home": home, "Player_ID": p.Player_ID,
                             "IsStarter": np.nan, "Team": team, "Player": p.Player, "Minutes_float": np.nan,
                             "status": st})
    fb = pd.DataFrame(rows)
    # tag context: regular minutes lost to OUT / LIKELY_OUT players, per team
    avg_min = box[box.Minutes_float > 0].groupby("Player_ID").Minutes_float.mean()
    lost = {}
    for t in teams:
        ids = [pid for pid, _ in rosters[t] if status.get(pid) in ("OUT", "LIKELY_OUT")]
        lost[t] = float(avg_min.reindex(ids).fillna(0)[lambda s: s >= 12].sum())
    fb["team_min_lost"] = fb.Team.map(lost).fillna(0)
    pts = pd.read_sql("SELECT Season, Gamecode, Player_ID, Points, TotalRebounds, Assistances FROM player_boxscores "
                      "WHERE Season = ? AND Minutes_float > 0", con, params=(season,)).sort_values("Gamecode")
    last = pts.groupby("Player_ID").tail(1).set_index("Player_ID")
    mean = pts.groupby("Player_ID")[["Points"]].mean()
    fb["last_pts_vs_avg"] = fb.Player_ID.map((last.Points - mean.Points.reindex(last.index)).round(1))
    os.makedirs(TMP, exist_ok=True)
    fg.to_parquet(f"{TMP}/future_games.parquet", index=False)
    fb.drop(columns=["status", "team_min_lost", "last_pts_vs_avg"]).to_parquet(f"{TMP}/future_box.parquet", index=False)
    return rnd, fg, fb


def features():
    env = dict(os.environ, FUTURE_DIR=TMP, OUT_MIN=f"{TMP}/min.parquet", OUT_RATES=f"{TMP}/rates.parquet")
    for script in ("build_features.py", "build_rates.py"):
        r = subprocess.run([sys.executable, script], cwd=MODEL, env=env, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"{script} failed:\n{r.stderr[-2000:]}")
    return pd.read_parquet(f"{TMP}/rates.parquet")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--round", type=int)
    a = ap.parse_args()
    SEASON = a.season

    rnd, fg, fb = build_future(a.season, a.round)
    print(f"Round {rnd}: {len(fg)} games, {len(fb)} projected players")
    df = features()
    df = df[(df.Season == a.season) & df.Gamecode.isin(fg.gameCode) & df.minutes.isna()].copy()
    df["round"] = pd.to_numeric(df["round"], errors="coerce")
    df["starter_rate"] = df.season_start_rate
    df["status"] = df.Player_ID.map(dict(zip(fb.Player_ID, fb.status))).fillna("UNLISTED")
    df["team_min_lost"] = df.Player_ID.map(dict(zip(fb.Player_ID, fb.team_min_lost))).fillna(0)
    df["last_pts_vs_avg"] = df.Player_ID.map(dict(zip(fb.Player_ID, fb.last_pts_vs_avg)))
    # a teammate listed GTD or a team with no report yet makes everyone's minutes on that team less certain
    shaky = fb[fb.status.isin(["GTD", "LIKELY_OUT", "NO_REPORT"])].groupby("Team").status.apply(lambda s: ",".join(sorted(set(s))))
    df["team_uncertainty"] = df.Team.map(shaky).fillna("")

    mq = {n: lgb.Booster(model_file=f"{MODEL}/minutes_{n}.txt") for n in ("median", "q10", "q90")}
    for n, m in mq.items():
        df[f"m_{n}"] = m.predict(df[MIN_FEATS])
    calib = pickle.load(open(f"{MODEL}/calibration.pkl", "rb"))

    N = 8000
    sd = np.clip((df.m_q90 - df.m_q10).to_numpy() / 2.563, 1.0, None)
    sims_min = np.clip(df.m_median.to_numpy()[:, None] + sd[:, None] * rng.standard_normal((len(df), N)), 1, 48)
    sys.path.insert(0, MODEL)
    from pir_features import add_pir_rates
    from scipy.stats import nbinom, norm
    df = add_pir_rates(df)
    cc = pickle.load(open(f"{MODEL}/calibration_combos.pkl", "rb"))
    # points/rebounds/assists drawn jointly (shared minutes + fitted correlation); threes separately
    zz = rng.standard_normal((len(df), N, 3)) @ np.linalg.cholesky(cc["corr"]).T
    sims = {}
    for s in STATS:
        m = lgb.Booster(model_file=f"{MODEL}/rate_{s}.txt")
        lam = np.exp(m.predict(df[m.feature_name()], raw_score=True)[:, None] + np.log(sims_min))
        k = calib[s]["k"]
        if s in ("pts", "reb", "ast"):
            sims[s] = nbinom.ppf(norm.cdf(zz[:, :, ("pts", "reb", "ast").index(s)]), k, k / (k + lam))
        else:
            sims[s] = rng.negative_binomial(k, k / (k + lam)) if k < 1e5 else rng.poisson(lam)
    for c, parts in COMBOS.items():
        sims[c] = sum(sims[p] for p in parts)
    pm = lgb.Booster(model_file=f"{MODEL}/rate_pir.txt")
    a, b = cc["pir_ab"]
    sims["pir"] = (pm.predict(df[cc["pir_feats"]])[:, None] * sims_min
                   + np.sqrt(a * sims_min + b) * rng.standard_normal(sims_min.shape))
    ALL = STATS + list(COMBOS) + ["pir"]
    for s in ALL:
        df[f"{s}_mean"] = sims[s].mean(axis=1).round(2)
        # fair line: the x.5 line whose P(over) is closest to 50%
        med = np.floor(np.median(sims[s], axis=1))
        cands = np.stack([np.maximum(med - 0.5, 0.5) if s != "pir" else med - 0.5, med + 0.5], axis=1)
        p_over = np.stack([(sims[s] > cands[:, j][:, None]).mean(axis=1) for j in (0, 1)], axis=1)
        df[f"{s}_fair_line"] = cands[np.arange(len(df)), np.abs(p_over - 0.5).argmin(axis=1)]

    def calibrate(stat, p):
        iso = calib[stat]["iso"] if stat in calib else cc[stat]
        return float(np.clip(iso.predict([p])[0], 0.01, 0.99))

    gm = fg.set_index("gameCode")
    df["game"] = df.Gamecode.map(lambda c: f"{gm.loc[c, 'homecode']} vs {gm.loc[c, 'awaycode']}")
    df["date"] = df.Gamecode.map(lambda c: gm.loc[c, "date"])
    proj = df[["date", "game", "Team", "Player", "status", "team_uncertainty", "m_q10", "m_median", "m_q90"]
              + [f"{s}_{x}" for s in ALL for x in ("mean", "fair_line")]].copy()
    proj.columns = (["date", "game", "team", "player", "status", "team_uncertainty", "min_low", "min_expected", "min_high"]
                    + [f"{LABEL[s]}_{x}" for s in ALL for x in ("mean", "fair_line")])
    proj = proj.round(1).sort_values(["game", "team", "min_expected"], ascending=[True, True, False])
    proj.to_csv(f"{RUN}/projections_round{rnd}.csv", index=False)
    print(f"Saved projections_round{rnd}.csv")
    print(proj.head(12).to_string(index=False))

    # ---------- score bookmaker lines ----------
    if os.path.exists(f"{RUN}/lines.csv"):
        lines = pd.read_csv(f"{RUN}/lines.csv")
        keys = [name_key(p) for p in df.Player]
        out = []
        for L in lines.itertuples():
            lk = name_key(L.player)
            idx = [i for i, k in enumerate(keys) if lk and lk <= k]
            if len(idx) != 1:
                out.append({"player": L.player, "stat": L.stat, "line": L.line,
                            "note": "player not found" if not idx else "ambiguous name"})
                continue
            i = idx[0]
            p_raw = float((sims[L.stat][i] > L.line).mean())
            p_over = calibrate(L.stat, p_raw)
            io, iu = 1 / L.over_odds, 1 / L.under_odds
            book_over = io / (io + iu)                       # remove the bookmaker margin
            edge_o, edge_u = p_over - book_over, (1 - p_over) - (1 - book_over)
            side = "OVER" if edge_o >= EDGE_MIN else "UNDER" if edge_u >= EDGE_MIN else ""
            st, tu = df.status.iloc[i], df.team_uncertainty.iloc[i]
            caution = ("player is a game-time decision - no bet until confirmed" if st == "GTD" else
                       "report suggests he may still be out - no bet until confirmed" if st == "LIKELY_OUT" else
                       "team injury report not filed yet - re-run closer to tip-off" if "NO_REPORT" in tu else
                       "a teammate's status is uncertain - minutes may shift" if ("GTD" in tu or "LIKELY_OUT" in tu) else "")
            if st in ("GTD", "LIKELY_OUT"):
                side = ""
            lp = df.last_pts_vs_avg.iloc[i]
            tags = []
            if df.team_min_lost.iloc[i] >= 15:
                tags.append("injury")                       # his team is missing a regular
            if pd.notna(lp) and lp >= 8:
                tags.append("after_hot_game")
            if pd.notna(lp) and lp <= -6:
                tags.append("after_cold_game")
            gc = int(df.Gamecode.iloc[i])
            out.append({"season": SEASON, "round": rnd, "gamecode": gc, "game": df.game.iloc[i],
                        "tipoff": f"{gm.loc[gc, 'date']} {gm.loc[gc, 'startime']}",
                        "player_id": df.Player_ID.iloc[i], "book": getattr(L, "book", ""),
                        "tags": ",".join(tags) or "plain",
                        "player": df.Player.iloc[i], "team": df.Team.iloc[i], "stat": L.stat, "line": L.line,
                        "over_odds": L.over_odds, "under_odds": L.under_odds,
                        "model_P_over": round(p_over, 3), "book_P_over_novig": round(book_over, 3),
                        "edge_over": round(edge_o, 3), "edge_under": round(edge_u, 3),
                        "bookmaker_margin": round(io + iu - 1, 3), "flag": side, "status": st, "caution": caution,
                        "expected_minutes": round(df.m_median.iloc[i], 1),
                        "model_mean": round(float(sims[L.stat][i].mean()), 2),
                        "note": "model P above 70% runs overconfident; treat as ~65%" if max(p_over, 1 - p_over) > 0.7 else ""})
        sc = pd.DataFrame(out)
        sc.to_csv(f"{RUN}/lines_scored_round{rnd}.csv", index=False)
        print(f"\nSaved lines_scored_round{rnd}.csv — flagged: {int((sc.get('flag', pd.Series()) != '').sum())}")
        print(sc.to_string(index=False))


if __name__ == "__main__":
    main()
