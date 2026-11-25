"""Greece - GBL (Basket League). Source: esake.gr results (by round) + game page mode=1 box score."""
import html as H
import re

from common import get, mmss_to_min

LEAGUE = "GBL"
CHAMP = {2016: "44323D2A", 2017: "42C43378", 2018: "A12E05CD", 2019: "49EEB365",
         2020: "03FFA3AC", 2021: "8C367D67", 2022: "DC917125", 2023: "C1AF5EF5",
         2024: "4820C134", 2025: "44B80BEB", 2026: "184645B9"}
PHASES = {"00000001": "RS", "00000002": "PO"}
GR_MONTHS = {"ιαν": 1, "φεβ": 2, "μαρ": 3, "απρ": 4, "μαι": 5, "μαΐ": 5, "μαϊ": 5, "ιουν": 6,
             "ιουλ": 7, "αυγ": 8, "σεπ": 9, "οκτ": 10, "νοε": 11, "δεκ": 12}
BASE = "https://www.esake.gr/el/action"


def list_games(season):
    games = {}
    for pid, phase in PHASES.items():
        empty = 0
        for rnd in range(1, 45):
            h = get(f"{BASE}/EsakeResults?idchampionship={CHAMP[season]}&idteam=&idseason={pid}"
                    f"&series={rnd:02d}").text
            ids = set(re.findall(r"idgame=([0-9A-F]{8})", h))
            new = ids - set(games)
            if not ids:
                empty += 1
                if empty >= 2:
                    break
                continue
            empty = 0
            for i in new:
                games[i] = {"game_id": i, "phase": phase}
    return list(games.values())


def _cells(row):
    return [re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[hd][^>]*>.*?</t[hd]>", row, re.S)]


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _ma(v):
    try:
        m, a = [int(x) for x in v.replace(" ", "").split("-")]
        return m, a
    except (AttributeError, ValueError):
        return None, None


def _date(h, season):
    m = re.search(r"<span>[Α-Ωα-ωάέήίόύώ]{2,4}\s+(\d{1,2})\s+([Α-Ωα-ωάέήίόύώΐΰϊϋ]{3,4})</span>", h)
    if not m:
        return None
    mon = GR_MONTHS.get(m.group(2).lower().replace("ά", "α").replace("ί", "ι")[:4]) or \
        GR_MONTHS.get(m.group(2).lower().replace("ά", "α").replace("ί", "ι")[:3])
    if not mon:
        return None
    year = season if mon >= 8 else season + 1
    return f"{year}-{mon:02d}-{int(m.group(1)):02d}"


def fetch_game(game, season):
    h = get(f"{BASE}/EsakegameView?idgame={game['game_id']}&mode=1").content.decode("utf-8", "ignore")
    sc = re.search(r'esake-pgame-view-final-score.*?<span>([^<]+)</span>.*?<span>(\d+)&nbsp;<span>vs</span>&nbsp;(\d+)</span>'
                   r'.*?class="img-responsive"><span>([^<]+)</span>', h, re.S)
    if not sc:
        return None, []
    home_team, hs, as_, away_team = H.unescape(sc.group(1)).strip(), int(sc.group(2)), int(sc.group(3)), H.unescape(sc.group(4)).strip()
    box = []
    for t in re.findall(r"<table.*?</table>", h, re.S):
        rows = re.findall(r"<tr.*?</tr>", t, re.S)
        if len(rows) > 3 and "TIM.PL." in _cells(rows[1]):
            box.append(rows)
    if len(box) < 2:
        return None, []
    players = []
    for rows, team, is_home in ((box[0], home_team, 1), (box[1], away_team, 0)):
        for r in rows[2:]:
            c = _cells(r)
            if len(c) < 17 or c[0].startswith("ΣΥΝΟΛΟ") or not c[0].startswith("#"):
                continue
            pid = re.search(r"idplayer=([0-9A-F]+)", r)
            name = re.sub(r"^#\S+\s*", "", c[0]).strip()          # "LAST FIRST"
            last, _, first = name.partition(" ")
            f2m, f2a = _ma(c[2]); f3m, f3a = _ma(c[3]); ftm, fta = _ma(c[4])
            players.append({
                "league": LEAGUE, "season": season, "team": team, "is_home": is_home,
                "player_id": pid.group(1) if pid else f"{team}|{name}",
                "player_name": f"{first.title()} {last.title()}".strip(),
                "first_name": first.title(), "last_name": last.title(), "starter": None,
                "minutes": mmss_to_min(c[15]), "points": _int(c[1]),
                "fg2m": f2m, "fg2a": f2a, "fg3m": f3m, "fg3a": f3a, "ftm": ftm, "fta": fta,
                "reb": _int(c[5]), "dreb": _int(c[6]), "oreb": _int(c[7]), "ast": _int(c[8]),
                "blk": _int(c[9]), "pf_drawn": _int(c[11]), "pf": _int(c[12]),
                "stl": _int(c[13]), "tov": _int(c[14]), "rating": _int(c[16]), "plus_minus": None,
            })
    game_row = {"league": LEAGUE, "season": season, "game_id": game["game_id"],
                "date": _date(h, season), "home_team": home_team, "away_team": away_team,
                "home_score": hs, "away_score": as_, "phase": game.get("phase")}
    return game_row, players
