"""Shared helpers for domestic-league collectors.

Every league module provides:
    LEAGUE = "ACB"
    list_games(season:int) -> list[dict]   # each dict has at least 'game_id'
    fetch_game(game:dict, season:int) -> (game_row:dict, player_rows:list[dict])

Rows are written to domestic.db:
    dom_games : league, season, game_id, date, home_team, away_team, home_score, away_score, phase
    dom_box   : league, season, game_id, team, is_home, player_id, player_name,
                first_name, last_name, starter, minutes, points, fg2m, fg2a, fg3m, fg3a,
                ftm, fta, oreb, dreb, reb, ast, stl, tov, blk, pf, pf_drawn, plus_minus, rating
"""
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

DB_DIR = "/home/claude/dbs"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en,es;q=0.8"})

BOX_COLS = ["league", "season", "game_id", "team", "is_home", "player_id", "player_name",
            "first_name", "last_name", "starter", "minutes", "points", "fg2m", "fg2a",
            "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "tov",
            "blk", "pf", "pf_drawn", "plus_minus", "rating"]
GAME_COLS = ["league", "season", "game_id", "date", "home_team", "away_team",
             "home_score", "away_score", "phase"]


def get(url, tries=3, **kw):
    last = None
    for a in range(tries):
        try:
            r = SESSION.get(url, timeout=40, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404):
                break
        except Exception as e:
            last = repr(e)
        time.sleep(2 * (a + 1))
    raise RuntimeError(f"{url}: {last}")


def mmss_to_min(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if ":" in v:
        parts = v.split(":")
        try:
            if len(parts) == 3:          # HH:MM:SS
                return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
            return int(parts[0]) + int(parts[1]) / 60
        except ValueError:
            return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def next_rsc(html):
    """Decode the Next.js App Router payload embedded in a page."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    return "".join(json.loads('"' + c + '"') for c in chunks)


def extract_json_object(s, start):
    """Return the JSON object beginning at s[start] == '{' (brace matching, string aware)."""
    depth, i, in_str, esc = 0, start, False, False
    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(s[start:i + 1])
        i += 1
    raise ValueError("unterminated object")


def init_db(league):
    import os
    os.makedirs(DB_DIR, exist_ok=True)
    con = sqlite3.connect(f"{DB_DIR}/{league}.db", timeout=60)
    con.execute(f"CREATE TABLE IF NOT EXISTS dom_games ({', '.join(GAME_COLS)}, "
                "PRIMARY KEY (league, season, game_id))")
    con.execute(f"CREATE TABLE IF NOT EXISTS dom_box ({', '.join(BOX_COLS)})")
    con.execute("CREATE INDEX IF NOT EXISTS ix_box ON dom_box (league, season, game_id)")
    con.execute("CREATE TABLE IF NOT EXISTS dom_failed (league, season, game_id, error)")
    con.commit()
    return con


def done_games(con, league):
    return set(con.execute("SELECT season, game_id FROM dom_games WHERE league=?",
                           (league,)).fetchall())


def save(con, game_row, players):
    con.execute(f"INSERT OR REPLACE INTO dom_games VALUES ({','.join('?' * len(GAME_COLS))})",
                [game_row.get(c) for c in GAME_COLS])
    con.execute("DELETE FROM dom_box WHERE league=? AND season=? AND game_id=?",
                (game_row["league"], game_row["season"], str(game_row["game_id"])))
    con.executemany(f"INSERT INTO dom_box VALUES ({','.join('?' * len(BOX_COLS))})",
                    [[p.get(c) for c in BOX_COLS] for p in players])
    con.commit()


def run(module, seasons, workers=6, log=print):
    lg = module.LEAGUE
    con = init_db(lg)
    done = done_games(con, lg)
    for season in seasons:
        try:
            games = module.list_games(season)
        except Exception as e:
            log(f"[{lg}] {season}: could not list games ({e})")
            continue
        todo = [g for g in games if (season, str(g["game_id"])) not in done]
        log(f"[{lg}] {season}-{str(season + 1)[-2:]}: {len(games)} games listed, {len(todo)} to fetch")
        ok = fail = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(module.fetch_game, g, season): g for g in todo}
            for fut in as_completed(futs):
                g = futs[fut]
                try:
                    game_row, players = fut.result()
                    if game_row is None:
                        continue               # not played / no stats
                    game_row["game_id"] = str(game_row["game_id"])
                    for p in players:
                        p["game_id"] = game_row["game_id"]
                    save(con, game_row, players)
                    ok += 1
                except Exception as e:
                    fail += 1
                    con.execute("INSERT INTO dom_failed VALUES (?,?,?,?)",
                                (lg, season, str(g["game_id"]), str(e)[:300]))
                    con.commit()
        log(f"[{lg}] {season}: saved {ok}, failed {fail}")
    con.close()
