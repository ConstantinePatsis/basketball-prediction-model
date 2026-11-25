"""Adriatic - ABA League. Source: aba-liga.com HTML (calendar + match Boxscore pages)."""
import html as H
import re
from datetime import datetime

from common import get, mmss_to_min

LEAGUE = "ABA"


def code(season):            # 2016-17 -> 16 ... 2026-27 -> 26
    return season - 2000


def list_games(season):
    h = get(f"https://www.aba-liga.com/calendar/{code(season)}/1/").text
    nums = sorted(set(int(n) for n in re.findall(rf'/match/(\d+)/{code(season)}/1/', h)))
    return [{"game_id": str(n)} for n in nums]


def _cells(row):
    return [re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[hd][^>]*>.*?</t[hd]>", row, re.S)]


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def fetch_game(game, season):
    h = get(f"https://www.aba-liga.com/match/{game['game_id']}/{code(season)}/1/Boxscore").text
    tables = re.findall(r"<table.*?</table>", h, re.S)
    if not tables:
        return None, []
    head = _cells(re.findall(r"<tr.*?</tr>", tables[0], re.S)[0])
    score = next((c for c in head if re.fullmatch(r"\d+ : \d+", c)), None)
    if not score:
        return None, []                       # not played yet
    home_team, away_team = head[1], head[3]
    hs, as_ = [int(x) for x in score.split(":")]
    dm = re.search(r"(\d{2}\.\d{2}\.\d{4}) \d{2}:\d{2}", h)
    date = datetime.strptime(dm.group(1), "%d.%m.%Y").strftime("%Y-%m-%d") if dm else None

    player_tables = []
    for t in tables:
        rows = re.findall(r"<tr.*?</tr>", t, re.S)
        if len(rows) > 4 and "Min" in _cells(rows[1]) and "Pts" in _cells(rows[1]):
            player_tables.append(rows)
        if len(player_tables) == 2:
            break
    if len(player_tables) < 2:
        return None, []

    players = []
    for rows, team, is_home in ((player_tables[0], home_team, 1), (player_tables[1], away_team, 0)):
        for r in rows[2:]:
            c = _cells(r)
            if len(c) < 25 or not re.search(r"[A-Za-zÀ-ž]", c[1]):
                continue
            name = c[1].replace("*", "").strip()
            players.append({
                "league": LEAGUE, "season": season, "team": team, "is_home": is_home,
                "player_id": f"{team}|{name}", "player_name": name,
                "first_name": None, "last_name": name.rsplit(" ", 1)[0] if " " in name else name,
                "starter": int("*" in c[1]),
                "minutes": mmss_to_min(c[2]), "points": _int(c[3]),
                "fg2m": _int(c[5]), "fg2a": _int(c[6]), "fg3m": _int(c[8]), "fg3a": _int(c[9]),
                "ftm": _int(c[11]), "fta": _int(c[12]),
                "dreb": _int(c[14]), "oreb": _int(c[15]), "reb": _int(c[16]),
                "ast": _int(c[17]), "stl": _int(c[18]), "tov": _int(c[19]), "blk": _int(c[20]),
                "pf": _int(c[22]), "pf_drawn": _int(c[23]),
                "plus_minus": _int(c[-2]), "rating": _int(c[-1]),
            })
    game_row = {"league": LEAGUE, "season": season, "game_id": game["game_id"], "date": date,
                "home_team": home_team, "away_team": away_team,
                "home_score": hs, "away_score": as_, "phase": None}
    return game_row, players
