"""Italy - LBA Serie A. Source: legabasket.it internal API (same domain)."""
from common import get

LEAGUE = "LBA"
BASE = "https://www.legabasket.it/api/championships"
_comps = None


def competitions():
    """{season_start_year: [competition ids (regular season + playoffs)]}"""
    global _comps
    if _comps is None:
        d = get(f"{BASE}/get-championships?items=1000&cs_id=1").json()
        rows = d.get("competitions", d if isinstance(d, list) else [])
        _comps = {}
        for c in rows:
            if c.get("ctype_code") in ("RS", "PO"):
                _comps.setdefault(c["year"], []).append((c["id"], c["ctype_code"]))
    return _comps


def list_games(season):
    games = {}
    for cid, phase in competitions().get(season, []):
        cal = get(f"{BASE}/get-championships-calendar-by-id?id={cid}").json()
        filters = cal.get("filters") or {}
        queries = [f"&ph_id={p['id']}" for p in filters.get("phases") or []]
        queries += [f"&d={d['id']}" for d in filters.get("days") or []]
        for q in queries or [""]:
            d = get(f"{BASE}/get-championships-calendar-by-id?id={cid}{q}").json()
            for m in d.get("matches") or []:
                games[str(m["id"])] = {"game_id": str(m["id"]), "phase": phase}
    return list(games.values())


def fetch_game(game, season):
    d = get(f"{BASE}/get-championships-matches-by-id?id={game['game_id']}").json()
    m = d.get("match") or {}
    if str(m.get("game_status")) != "2" or not d.get("scores"):
        return None, []
    game_row = {
        "league": LEAGUE, "season": season, "game_id": game["game_id"],
        "date": (m.get("match_datetime") or "")[:10],
        "home_team": m.get("h_team_name"), "away_team": m.get("v_team_name"),
        "home_score": m.get("home_final_score"), "away_score": m.get("visitor_final_score"),
        "phase": game.get("phase"),
    }
    players = []
    for side, is_home, tname in (("ht", 1, m.get("h_team_name")), ("vt", 0, m.get("v_team_name"))):
        for p in (d["scores"].get(side) or {}).get("rows") or []:
            secs = p.get("sec")
            players.append({
                "league": LEAGUE, "season": season, "team": tname, "is_home": is_home,
                "player_id": str(p.get("player_id")),
                "player_name": f"{(p.get('player_name') or '').strip()} {(p.get('player_surname') or '').strip().title()}".strip(),
                "first_name": p.get("player_name"), "last_name": (p.get("player_surname") or "").title(),
                "starter": int(str(p.get("sf")) == "1"),
                "minutes": (secs / 60.0) if isinstance(secs, (int, float)) else float(p.get("min") or 0),
                "points": p.get("pun"),
                "fg2m": p.get("t2_r"), "fg2a": p.get("t2_t"),
                "fg3m": p.get("t3_r"), "fg3a": p.get("t3_t"),
                "ftm": p.get("tl_r"), "fta": p.get("tl_t"),
                "oreb": p.get("rimbalzi_o"), "dreb": p.get("rimbalzi_d"), "reb": p.get("rimbalzi_t"),
                "ast": p.get("ass"), "stl": p.get("palle_r"), "tov": p.get("palle_p"),
                "blk": p.get("stoppate_dat"), "pf": p.get("falli_c"), "pf_drawn": p.get("falli_sf"),
                "plus_minus": p.get("plus_minus"), "rating": p.get("val_lega"),
            })
    return game_row, players
