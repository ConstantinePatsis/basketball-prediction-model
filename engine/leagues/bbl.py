"""Germany - BBL. Source: public easycredit-bbl.de game pages (server-rendered __NEXT_DATA__).

The league's JSON API needs an auth key, so it is not used. Season game lists are built by
crawling: each game page links ~27 other games (recent/upcoming of both teams), so a
breadth-first walk from a few seed games covers every season. Index cached in bbl_index.json.
"""
import json
import os
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from common import SESSION, get

LEAGUE = "BBL"
INDEX = "/home/claude/leagues/bbl_index.json"
SEASONS = range(2016, 2027)


def _page(i):
    try:
        r = SESSION.get(f"https://www.easycredit-bbl.de/spiele/{i}", timeout=40)
        if r.status_code != 200:
            return None
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        return json.loads(m.group(1))["props"]["pageProps"] if m else None
    except Exception:
        return None


def _info(pp):
    gd = (pp or {}).get("initialGameData") or {}
    if not gd.get("seasonId"):
        return None
    nbrs = set()
    for lst in ((pp.get("initialRecentGames") or {}).values()):
        for g in lst or []:
            if g.get("id"):
                nbrs.add(str(g["id"]))
    return {"season": int(gd["seasonId"]), "competition": gd.get("competition"),
            "stage": gd.get("stage"), "date": (gd.get("scheduledTime") or "")[:10]}, nbrs


def build_index():
    if os.path.exists(INDEX):
        return json.load(open(INDEX))
    seeds = list(range(15000, 29001, 150)) + list(range(2000000, 2007600, 300))
    idx, seen = {}, set()
    queue = deque()
    with ThreadPoolExecutor(8) as pool:
        for i, pp in zip(seeds, pool.map(_page, seeds)):
            seen.add(str(i))
            inf = _info(pp)
            if inf and inf[0]["season"] in SEASONS:
                idx[str(i)] = inf[0]
                queue.extend(n for n in inf[1] if n not in seen)
        while queue:
            batch = []
            while queue and len(batch) < 32:
                n = queue.popleft()
                if n not in seen:
                    seen.add(n)
                    batch.append(n)
            for n, pp in zip(batch, pool.map(_page, batch)):
                inf = _info(pp)
                if inf and inf[0]["season"] in SEASONS:
                    idx[n] = inf[0]
                    queue.extend(x for x in inf[1] if x not in seen)
    json.dump(idx, open(INDEX, "w"))
    return idx


# Game-ID blocks per season, mapped by sampling (IDs are not contiguous across seasons).
RANGES = {2016: [(19400, 20900)], 2017: [(20800, 22150)], 2018: [(22000, 23560)],
          2019: [(23950, 25560)], 2020: [(25480, 26000)], 2021: [(25920, 27520)],
          2022: [(27440, 28360), (30400, 30600)], 2023: [(32600, 34600)],
          2024: [(2002960, 2006760)], 2025: [(2003960, 2006760)], 2026: [(2006600, 2007100)]}


def list_games(season):
    """Scan the season's ID range, skipping games already saved. For the current season the upper end is
    taken from the newest game IDs linked on the league homepage (IDs are not in date order: cup games
    and placeholders sit above regular-season games)."""
    import re, sqlite3, requests
    ranges = list(RANGES[season])
    try:
        h = requests.get("https://www.easycredit-bbl.de/", headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
        live = [int(x) for x in re.findall(r"/spiele/(\d{7})", h)]
        if live and season == max(RANGES):
            ranges = [(a, max(b, max(live) + 80)) for a, b in ranges]
    except Exception:
        pass
    ids = {i for a, b in ranges for i in range(a, b + 1)}
    try:
        con = sqlite3.connect("/home/claude/dbs/BBL.db")
        ids -= {int(r[0]) for r in con.execute("SELECT game_id FROM dom_games")}
        ids -= {int(r[0]) for r in con.execute("SELECT game_id FROM dom_failed")}
    except Exception:
        pass
    return [{"game_id": str(i)} for i in sorted(ids)]


def _team_name(t):
    return (t or {}).get("name") or (t or {}).get("nameFull") or (t or {}).get("tlc")


def fetch_game(game, season):
    pp = _page(game["game_id"])
    if not pp:
        return None, []                      # gap in the ID range
    gd, gs = pp.get("initialGameData") or {}, pp.get("initialGameStats") or {}
    if str(gd.get("seasonId")) != str(season):
        return None, []
    res = gd.get("result") or {}
    if gd.get("status") not in ("OFFICIAL", "FINISHED", "ENDED") and not gs.get("homeTeam"):
        return None, []
    teams = {"homeTeam": _team_name(gd.get("homeTeam")), "guestTeam": _team_name(gd.get("guestTeam"))}
    players, scores = [], {}
    for side, is_home in (("homeTeam", 1), ("guestTeam", 0)):
        t = gs.get(side) or {}
        scores[side] = (t.get("gameStat") or {}).get("points")
        for p in t.get("playerStats") or []:
            sp = p.get("seasonPlayer") or {}
            players.append({
                "league": LEAGUE, "season": season, "team": teams[side], "is_home": is_home,
                "player_id": str(sp.get("realPlayerId") or sp.get("playerId")),
                "player_name": f"{sp.get('firstName', '')} {sp.get('lastName', '')}".strip(),
                "first_name": sp.get("firstName"), "last_name": sp.get("lastName"),
                "starter": int(bool(p.get("isStartingFive"))),
                "minutes": float(p.get("secondsPlayed") or 0) / 60.0, "points": p.get("points"),
                "fg2m": p.get("twoPointShotsMade"), "fg2a": p.get("twoPointShotsAttempted"),
                "fg3m": p.get("threePointShotsMade"), "fg3a": p.get("threePointShotsAttempted"),
                "ftm": p.get("freeThrowsMade"), "fta": p.get("freeThrowsAttempted"),
                "oreb": p.get("offensiveRebounds"), "dreb": p.get("defensiveRebounds"),
                "reb": p.get("totalRebounds"), "ast": p.get("assists"), "stl": p.get("steals"),
                "tov": p.get("turnovers"), "blk": p.get("blocks"), "pf": p.get("foulsCommitted"),
                "pf_drawn": p.get("foulsReceived"), "plus_minus": p.get("plusMinus"),
                "rating": p.get("efficiency"),
            })
    if not players or scores.get("homeTeam") is None:
        return None, []
    game_row = {"league": LEAGUE, "season": season, "game_id": game["game_id"],
                "date": (gd.get("scheduledTime") or "")[:10],
                "home_team": teams["homeTeam"], "away_team": teams["guestTeam"],
                "home_score": scores["homeTeam"], "away_score": scores["guestTeam"],
                "phase": f"{gd.get('competition')}/{gd.get('stage')}"}
    return game_row, players
