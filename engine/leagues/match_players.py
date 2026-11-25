"""Link domestic-league player records to EuroLeague Player_IDs.

1. Team mapping: each EuroLeague (season, team) is mapped to the domestic (league, season, team)
   whose roster shares the most players (key = surname + first initial).
2. Player mapping: within each mapped team-season, players are matched on surname + first
   initial, falling back to surname alone when it is unique on both rosters.
Output tables in /home/claude/basketball.db:
    player_xwalk(league, dom_player_id, el_player_id, el_player, matched_seasons)
    team_xwalk(season, el_team, league, dom_team, overlap)
    dom_games, dom_box (all leagues stacked) with el_player_id attached to dom_box
"""
import glob
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict

import pandas as pd

OUT = "/home/claude/basketball.db"


GREEK = [("ου", "ou"), ("μπ", "b"), ("ντ", "d"), ("γκ", "g"), ("τζ", "tz"), ("τσ", "ts"),
         ("αι", "ai"), ("ει", "ei"), ("οι", "oi"), ("θ", "th"), ("χ", "ch"), ("ψ", "ps"),
         ("α", "a"), ("β", "v"), ("γ", "g"), ("δ", "d"), ("ε", "e"), ("ζ", "z"), ("η", "i"),
         ("ι", "i"), ("κ", "k"), ("λ", "l"), ("μ", "m"), ("ν", "n"), ("ξ", "x"), ("ο", "o"),
         ("π", "p"), ("ρ", "r"), ("σ", "s"), ("ς", "s"), ("τ", "t"), ("υ", "y"), ("φ", "f"),
         ("ω", "o")]


def translit(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    for g, l in GREEK:
        s = s.replace(g, l)
    return s


def norm(s):
    s = translit(str(s or ""))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).strip()


def el_key(player):                     # "SLOUKAS, KOSTAS" -> ("sloukas", "k")
    last, _, first = str(player).partition(",")
    last, first = norm(last), norm(first)
    return last.split()[-1] if last else "", first[:1]


def dom_key(row):
    first, last = norm(row.first_name), norm(row.last_name)
    name = norm(row.player_name)
    if row.league == "ABA":             # "Jones C."
        parts = name.split()
        return (parts[-2] if len(parts) >= 2 else name), (parts[-1][:1] if len(parts) >= 2 else "")
    if row.league == "LKL":             # "P. Petrilevičius" (slug has full name)
        parts = name.split()
        return (parts[-1] if parts else ""), (parts[0][:1] if parts else "")
    if not last:
        parts = name.split()
        last, first = (parts[-1] if parts else ""), (parts[0] if parts else "")
    return last.split()[-1] if last else "", first[:1]


def main():
    el = pd.read_sql("SELECT DISTINCT Season AS season, Team AS el_team, Player_ID AS el_player_id, "
                     "Player AS el_player FROM player_boxscores WHERE Minutes_float > 0",
                     sqlite3.connect("/home/claude/euroleague.db"))
    el[["last", "init"]] = el.el_player.apply(lambda p: pd.Series(el_key(p)))

    games, box = [], []
    for f in sorted(glob.glob("/home/claude/dbs/*.db")):
        con = sqlite3.connect(f)
        games.append(pd.read_sql("SELECT * FROM dom_games", con))
        box.append(pd.read_sql("SELECT * FROM dom_box", con))
    games, box = pd.concat(games), pd.concat(box)
    # forfeits / empty box scores out
    games = games[(games.home_score.fillna(0) + games.away_score.fillna(0)) > 40]
    keys = box.apply(dom_key, axis=1, result_type="expand")
    box["last"], box["init"] = keys[0], keys[1]

    dom_roster = box[box.minutes > 0].groupby(["league", "season", "team"])
    dom_sets = {k: set(zip(g["last"], g["init"])) for k, g in dom_roster}
    el_sets = {k: set(zip(g["last"], g["init"])) for k, g in el.groupby(["season", "el_team"])}

    team_rows = []
    for (season, team), s in el_sets.items():
        best = max(((len(s & ds), k) for k, ds in dom_sets.items() if k[1] == season),
                   default=(0, None))
        if best[0] >= 4:
            team_rows.append({"season": season, "el_team": team, "league": best[1][0],
                              "dom_team": best[1][2], "overlap": best[0]})
    team_x = pd.DataFrame(team_rows)

    links = defaultdict(Counter)
    names = {}
    for t in team_x.itertuples():
        e = el[(el.season == t.season) & (el.el_team == t.el_team)]
        d = box[(box.league == t.league) & (box.season == t.season) & (box.team == t.dom_team)][
            ["player_id", "last", "init"]].drop_duplicates()
        for p in e.itertuples():
            cand = d[(d["last"] == p.last) & (d["init"] == p.init)]
            if len(cand) != 1:
                c2 = d[d["last"] == p.last]
                cand = c2 if len(c2) == 1 and (e["last"] == p.last).sum() == 1 else cand.iloc[0:0]
            if len(cand) == 1:
                links[(t.league, cand.player_id.iloc[0])][p.el_player_id] += 1
                names[p.el_player_id] = p.el_player
    xw = []
    for (lg, pid), cnt in links.items():
        el_id, n = cnt.most_common(1)[0]
        xw.append({"league": lg, "dom_player_id": pid, "el_player_id": el_id,
                   "el_player": names[el_id], "matched_seasons": n})
    xw = pd.DataFrame(xw)

    box = box.merge(xw[["league", "dom_player_id", "el_player_id"]],
                    left_on=["league", "player_id"], right_on=["league", "dom_player_id"], how="left")
    box = box.drop(columns=["dom_player_id", "last", "init"])
    box = box.merge(games[["league", "season", "game_id"]], on=["league", "season", "game_id"])

    out = sqlite3.connect(OUT)
    games.to_sql("dom_games", out, if_exists="replace", index=False)
    box.to_sql("dom_box", out, if_exists="replace", index=False)
    xw.to_sql("player_xwalk", out, if_exists="replace", index=False)
    team_x.to_sql("team_xwalk", out, if_exists="replace", index=False)
    out.execute("CREATE INDEX IF NOT EXISTS ix_dbox_el ON dom_box (el_player_id)")
    out.commit()

    # coverage report: share of EuroLeague player-seasons (on teams with a domestic league)
    el_ps = el.merge(team_x[["season", "el_team", "league"]], on=["season", "el_team"])
    linked = set(xw.el_player_id)
    el_ps["linked"] = el_ps.el_player_id.isin(linked)
    print("Team-seasons mapped:", len(team_x), "of", len(el_sets))
    print(team_x.groupby("league").size().to_string())
    print("\nEuroLeague player-seasons on mapped teams that are linked:")
    print(el_ps.groupby("league").linked.mean().round(3).to_string())
    print("\nPlayers linked:", xw.el_player_id.nunique())


if __name__ == "__main__":
    main()
