"""Lithuania - LKL. Source: lkl.lt game pages (date, teams) + lkl.lt/api/livestream/boxscore/{id}.

Game IDs are not grouped by season, so the first call scans every ID once and caches
id -> (date, home, away) in lkl_index.json. Includes KMT cup games played on lkl.lt.
"""
import json
import os
import re
import html as H
from concurrent.futures import ThreadPoolExecutor

from common import SESSION, get, mmss_to_min

LEAGUE = "LKL"
INDEX = "/home/claude/leagues/lkl_index.json"
MAX_ID = 11900
MONTHS = {"sausio": 1, "vasario": 2, "kovo": 3, "balandžio": 4, "gegužės": 5, "birželio": 6,
          "liepos": 7, "rugpjūčio": 8, "rugsėjo": 9, "spalio": 10, "lapkričio": 11, "gruodžio": 12}


def _page_info(i):
    try:
        r = SESSION.get(f"https://lkl.lt/rungtynes/{i}", timeout=30)
        if r.status_code != 200:
            return i, None
        h = r.text
        d = re.search(r"(\d{4})\s+m\.\s+(\S+)\s+(\d+)\s+d\.", h)
        t = re.search(r"<title>(.*?)</title>", h, re.S)
        if not d or not t:
            return i, None
        mon = MONTHS.get(d.group(2).lower())
        if not mon:
            return i, None
        title = H.unescape(t.group(1)).replace(" - LKL.LT", "").strip()
        home, _, away = title.partition(" - ")
        return i, {"date": f"{d.group(1)}-{mon:02d}-{int(d.group(3)):02d}",
                   "home": home.strip(), "away": away.strip()}
    except Exception:
        return i, None


_cache = None


def build_index():
    """Full scan on first run; afterwards only scans IDs above the highest known one."""
    global _cache
    if _cache is not None:
        return _cache
    idx = json.load(open(INDEX)) if os.path.exists(INDEX) else {}
    start = max((int(i) for i in idx), default=0) + 1 if idx else 1
    end = start + 300 if idx else MAX_ID
    with ThreadPoolExecutor(8) as pool:
        for i, info in pool.map(_page_info, range(start, end + 1)):
            if info:
                idx[str(i)] = info
    json.dump(idx, open(INDEX, "w"))
    _cache = idx
    return idx


def season_of(date):
    y, m = int(date[:4]), int(date[5:7])
    return y if m >= 8 else y - 1


def list_games(season):
    idx = build_index()
    return [{"game_id": i, **v} for i, v in idx.items() if season_of(v["date"]) == season]


def _v(d, k):
    x = d.get(k) or {}
    return x.get("value") if isinstance(x, dict) else x


def _ma(v):
    try:
        m, a = str(v).split("/")
        return int(m), int(a)
    except ValueError:
        return None, None


def fetch_game(game, season):
    r = get(f"https://lkl.lt/api/livestream/boxscore/{game['game_id']}",
            headers={"Accept": "application/json"})
    d = r.json()
    box = d.get("boxscore") or {}
    if not box.get("home") or not box["home"].get("players"):
        return None, []
    scores = {}
    players = []
    for side, is_home, team in (("home", 1, game["home"]), ("away", 0, game["away"])):
        part = box.get(side) or {}
        scores[side] = _v(part.get("team") or {}, "points")
        for p in part.get("players") or []:
            f2m, f2a = _ma(_v(p, "fg2")); f3m, f3a = _ma(_v(p, "fg3")); ftm, fta = _ma(_v(p, "ft"))
            name = _v(p, "name") or ""
            slug = p.get("slug") or ""
            players.append({
                "league": LEAGUE, "season": season, "team": team, "is_home": is_home,
                "player_id": slug or f"{team}|{name}", "player_name": name,
                "first_name": None, "last_name": name.split(". ", 1)[-1],
                "starter": int(bool(p.get("is_starter"))), "minutes": mmss_to_min(_v(p, "time")),
                "points": _v(p, "points"), "fg2m": f2m, "fg2a": f2a, "fg3m": f3m, "fg3a": f3a,
                "ftm": ftm, "fta": fta, "oreb": _v(p, "offensive_rebounds"),
                "dreb": _v(p, "defensive_rebounds"), "reb": _v(p, "total_rebounds"),
                "ast": _v(p, "assists"), "stl": _v(p, "steals"), "tov": _v(p, "turnovers"),
                "blk": _v(p, "blocks"), "pf": _v(p, "fouls"), "pf_drawn": _v(p, "fouls_on"),
                "plus_minus": _v(p, "plus_minus"), "rating": _v(p, "efficiency"),
            })
    if not scores.get("home"):
        return None, []
    game_row = {"league": LEAGUE, "season": season, "game_id": game["game_id"], "date": game["date"],
                "home_team": game["home"], "away_team": game["away"],
                "home_score": scores["home"], "away_score": scores["away"], "phase": None}
    return game_row, players
