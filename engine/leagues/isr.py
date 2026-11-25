"""Israel - Winner League (Ligat HaAl). Source: basket.co.il (English pages, lang=en)."""
import html as H
import re
from datetime import datetime

from common import get

LEAGUE = "ISR"


def _decode(r):
    return r.content.decode("utf-8", "ignore")


def list_games(season):
    # cYear is the year the season ends: 2026-27 -> 2027
    h = _decode(get(f"https://basket.co.il/results.asp?cYear={season + 1}&lang=en"))
    ids = sorted(set(re.findall(r"game-zone\.asp\?GameId=(\d+)", h)), key=int)
    return [{"game_id": i} for i in ids]


def _cells(row):
    return [re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[hd][^>]*>.*?</t[hd]>", row, re.S)]


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _ma(v):
    try:
        m, a = v.split("/")
        return int(m), int(a)
    except (AttributeError, ValueError):
        return None, None


def fetch_game(game, season):
    h = _decode(get(f"https://basket.co.il/game-zone.asp?GameId={game['game_id']}&lang=en"))
    box = []
    for t in re.findall(r"<table.*?</table>", h, re.S):
        rows = re.findall(r"<tr.*?</tr>", t, re.S)
        if len(rows) > 4 and "Player Name" in _cells(rows[2]):
            box.append(rows)
    if len(box) < 2:
        return None, []
    dm = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", h)
    date = (datetime(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))).strftime("%Y-%m-%d")
            if dm else None)

    players, teams, totals = [], [], []
    for rows, is_home in ((box[0], 1), (box[1], 0)):
        team = re.sub(r"\s*\(Coach:.*", "", _cells(rows[0])[0]).strip()
        teams.append(team)
        total = None
        for r in rows[3:]:
            c = _cells(r)
            if len(c) < 23:
                continue
            if c[1] == "Total":
                total = _int(c[4])
                continue
            if c[1] in ("Team", ""):
                continue
            pid = re.search(r"PlayerId=(\d+)", r)
            f2m, f2a = _ma(c[5]); f3m, f3a = _ma(c[7]); ftm, fta = _ma(c[9])
            players.append({
                "league": LEAGUE, "season": season, "team": team, "is_home": is_home,
                "player_id": pid.group(1) if pid else f"{team}|{c[1]}",
                "player_name": c[1], "first_name": c[1].split(" ", 1)[0],
                "last_name": c[1].split(" ", 1)[1] if " " in c[1] else c[1],
                "starter": int(c[2] == "*"), "minutes": float(_int(c[3]) or 0),
                "points": _int(c[4]), "fg2m": f2m, "fg2a": f2a, "fg3m": f3m, "fg3a": f3a,
                "ftm": ftm, "fta": fta, "dreb": _int(c[11]), "oreb": _int(c[12]), "reb": _int(c[13]),
                "pf": _int(c[14]), "pf_drawn": _int(c[15]), "stl": _int(c[16]), "tov": _int(c[17]),
                "ast": _int(c[18]), "blk": _int(c[19]), "rating": _int(c[21]), "plus_minus": _int(c[22]),
            })
        totals.append(total)
    if totals[0] is None or (totals[0] == 0 and totals[1] == 0):
        return None, []
    game_row = {"league": LEAGUE, "season": season, "game_id": game["game_id"], "date": date,
                "home_team": teams[0], "away_team": teams[1],
                "home_score": totals[0], "away_score": totals[1], "phase": None}
    return game_row, players
