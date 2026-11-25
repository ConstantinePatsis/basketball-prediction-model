"""France - LNB Pro A / Betclic Élite.

Schedule: api-prod.lnb.fr with the anonymous token lnb.fr issues to every visitor (user-approved).
Box scores: the Sportradar/Atrium embed API used by lnb.fr's match centre (website id 12).
"""
import re
import threading
import time

import requests

from common import UA, get

LEAGUE = "LNB"
API = "https://api-prod.lnb.fr/"
EMBED = "https://embed-api.eui.connect.sportradar.com/v1/embed/12/fixture_detail?fixtureId="
_lock = threading.Lock()
_tok = {"t": None, "at": 0}


def _api():
    with _lock:
        if not _tok["t"] or time.time() - _tok["at"] > 600:        # token lasts ~15 min
            _tok["t"] = requests.get("https://lnb.fr/api/token", headers={"User-Agent": UA},
                                     timeout=30).json()["token"]
            _tok["at"] = time.time()
        return {"User-Agent": UA, "device_type": "web", "language_code": "fr",
                "Authorization": f"Bearer {_tok['t']}"}


def _competitions(season):
    d = requests.get(API + f"competition/getDivisionCompetitionByYear?year={season}&division_external_id=1",
                     headers=_api(), timeout=30).json()["data"]
    out = []
    for c in d:
        ab = (c.get("competition_abbrev") or "").upper()
        if ab.startswith("PROA") or "ELITE" in ab or "ÉLITE" in (c.get("competition_name") or "").upper():
            out.append((c["external_id"], "PO" if "PO" in ab.split() or "PLAYOFF" in ab else "RS"))
    return out


def list_games(season):
    games = {}
    for cid, phase in _competitions(season):
        rounds = requests.get(API + f"competition/getCompetitionRounds?competition_external_id={cid}",
                              headers=_api(), timeout=30).json().get("data") or []
        for rn in sorted({r["round_number"] for r in rounds}):
            d = requests.post(API + "match/getMatchesByCompetitionAndRound",
                              json={"competition_external_id": cid, "round_number": rn},
                              headers=_api(), timeout=30).json().get("data") or {}
            for m in d.get("matches") or []:
                if m.get("match_status") == "COMPLETE":
                    games[m["match_id"]] = {"game_id": m["match_id"], "phase": phase,
                                            "date": m.get("match_date")}
    return list(games.values())


def _mins(v):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", v or "")
    if not m:
        return 0.0
    h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    return h * 60 + mi + s / 60


def fetch_game(game, season):
    d = get(EMBED + game["game_id"], headers={"Origin": "https://lnb.fr", "Referer": "https://lnb.fr/"}).json()["data"]
    fx = d.get("fixture") or {}
    comps = {("home" if c.get("isHome") else "away"): c for c in fx.get("competitors") or []}
    base = ((d.get("statistics") or {}).get("data") or {}).get("base") or {}
    if not base or "home" not in comps:
        return None, []
    players = []
    for side, is_home in (("home", 1), ("away", 0)):
        team = comps[side].get("name")
        for blk in (base.get(side) or {}).get("persons") or []:
            for p in blk.get("rows") or []:
                s = p.get("statistics") or {}
                name = p.get("personName") or ""
                first, _, last = name.partition(" ")
                players.append({
                    "league": LEAGUE, "season": season, "team": team, "is_home": is_home,
                    "player_id": p.get("personId"), "player_name": name,
                    "first_name": first, "last_name": last or first,
                    "starter": int(bool(p.get("starter"))), "minutes": _mins(s.get("minutes")),
                    "points": s.get("points"), "fg2m": s.get("pointsTwoMade"), "fg2a": s.get("pointsTwoAttempted"),
                    "fg3m": s.get("pointsThreeMade"), "fg3a": s.get("pointsThreeAttempted"),
                    "ftm": s.get("freeThrowsMade"), "fta": s.get("freeThrowsAttempted"),
                    "oreb": s.get("reboundsOffensive"), "dreb": s.get("reboundsDefensive"),
                    "reb": s.get("rebounds"), "ast": s.get("assists"), "stl": s.get("steals"),
                    "tov": s.get("turnovers"), "blk": s.get("blocks"), "pf": s.get("foulsTotal"),
                    "pf_drawn": None, "plus_minus": s.get("plusMinus"), "rating": s.get("efficiency"),
                })
    try:
        hs, as_ = int(comps["home"].get("score")), int(comps["away"].get("score"))
    except (TypeError, ValueError):
        return None, []
    game_row = {"league": LEAGUE, "season": season, "game_id": game["game_id"],
                "date": (fx.get("startTimeLocal") or game.get("date") or "")[:10],
                "home_team": comps["home"].get("name"), "away_team": comps["away"].get("name"),
                "home_score": hs, "away_score": as_, "phase": game.get("phase")}
    return game_row, players
