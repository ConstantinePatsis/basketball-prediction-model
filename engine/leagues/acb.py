"""Spain - Liga Endesa (ACB). Source: acb.com calendar + live.acb.com match pages."""
import re

from common import get, next_rsc, extract_json_object, mmss_to_min

LEAGUE = "ACB"
# acb.com season ids: 81 = 2016-17 ... 91 = 2026-27
SEASON_ID = {y: 81 + (y - 2016) for y in range(2016, 2027)}


def list_games(season):
    html = get(f"https://acb.com/es/liga/calendario?temporada={SEASON_ID[season]}").text
    ids = {}
    for slug, gid in re.findall(r'live\.acb\.com/(?:es/)?partidos/([a-z0-9-]+)-(\d+)/', html):
        ids[gid] = slug
    return [{"game_id": gid, "slug": slug} for gid, slug in ids.items()]


def fetch_game(game, season):
    html = get(f"https://live.acb.com/partidos/{game['slug']}-{game['game_id']}/estadisticas").text
    s = next_rsc(html)
    i = s.find('"initialMatchHeader":')
    if i < 0:
        return None, []
    head = extract_json_object(s, s.index("{", i))
    if head.get("status") != "FINALIZED":
        return None, []
    j = s.find('"initialStatistics":')
    if j < 0:
        return None, []
    stats = extract_json_object(s, s.index("{", j))

    home_id = head["teams"]["home"]["id"]
    game_row = {
        "league": LEAGUE, "season": season, "game_id": game["game_id"],
        "date": head.get("start", "")[:10],
        "home_team": head["teams"]["home"]["fullName"],
        "away_team": head["teams"]["away"]["fullName"],
        "home_score": head.get("currentHomeScore"),
        "away_score": head.get("currentAwayScore"),
        "phase": None,
    }
    players = []
    for tb in stats.get("teamBoxscores", []):
        team = tb["team"]
        periods = {p["quarter"]: p for p in tb.get("statsByPeriods", [])}
        total = periods.get(0)            # quarter 0 = whole game
        if not total:
            continue
        for p in total["stats"].get("players", []):
            pl = p.get("player") or {}
            players.append({
                "league": LEAGUE, "season": season,
                "team": team.get("fullName"), "is_home": int(team["id"] == home_id),
                "player_id": str(pl.get("id")),
                "player_name": f"{pl.get('firstName', '')} {pl.get('lastName', '')}".strip(),
                "first_name": pl.get("firstName"), "last_name": pl.get("lastName"),
                "starter": int(bool(p.get("isStarted"))),
                "minutes": mmss_to_min(p.get("playTime")),
                "points": p.get("points"),
                "fg2m": p.get("twoPointersMade"), "fg2a": p.get("twoPointersAttempted"),
                "fg3m": p.get("threePointersMade"), "fg3a": p.get("threePointersAttempted"),
                "ftm": p.get("freeThrowsMade"), "fta": p.get("freeThrowsAttempted"),
                "oreb": p.get("offRebounds"), "dreb": p.get("defRebounds"),
                "reb": p.get("totalRebounds"), "ast": p.get("assists"),
                "stl": p.get("steals"), "tov": p.get("turnovers"), "blk": p.get("blocks"),
                "pf": p.get("personalFouls"), "pf_drawn": p.get("foulsDrawn"),
                "plus_minus": p.get("plusMinus"), "rating": p.get("rating"),
            })
    return game_row, players
