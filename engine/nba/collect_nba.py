"""Collect NBA box scores from ESPN's public feed into /home/claude/nba/nba.db (resumable).

  python3 collect_nba.py 2016 2026          # seasons by start year (2016 = 2016-17)
Season types kept: 2 regular season, 3 playoffs, 5 play-in.
"""
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

U = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
DB = "/home/claude/nba/nba.db"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
KEEP = {2, 3, 5}


def get(url, params, tries=4):
    for k in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    return None


def init():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS games (event_id TEXT PRIMARY KEY, season INT, season_type INT, date TEXT,
        home TEXT, away TEXT, home_score INT, away_score INT, neutral INT, venue TEXT, city TEXT, state TEXT);
    CREATE TABLE IF NOT EXISTS box (event_id TEXT, team TEXT, athlete_id TEXT, player TEXT, position TEXT,
        starter INT, dnp INT, dnp_reason TEXT, min REAL, pts INT, fgm INT, fga INT, fg3m INT, fg3a INT, ftm INT, fta INT,
        reb INT, ast INT, tov INT, stl INT, blk INT, oreb INT, dreb INT, pf INT, plus_minus INT);
    CREATE TABLE IF NOT EXISTS dates_done (d TEXT PRIMARY KEY, n INT);
    CREATE TABLE IF NOT EXISTS failed (event_id TEXT PRIMARY KEY);
    CREATE INDEX IF NOT EXISTS ix_box_ev ON box(event_id);
    """)
    return con


def pair(v):
    try:
        a, b = v.split("-")
        return int(a), int(b)
    except Exception:
        return None, None


def num(v):
    try:
        return int(str(v).replace("+", ""))
    except Exception:
        return None


def parse_summary(eid, j):
    rows = []
    for t in j.get("boxscore", {}).get("players", []):
        team = t["team"]["abbreviation"]
        for st in t.get("statistics", []):
            lab = st.get("labels", [])
            for a in st.get("athletes", []):
                ath = a.get("athlete", {})
                s = dict(zip(lab, a.get("stats", [])))
                fgm, fga = pair(s.get("FG", ""))
                f3m, f3a = pair(s.get("3PT", ""))
                ftm, fta = pair(s.get("FT", ""))
                mn = s.get("MIN")
                rows.append((eid, team, ath.get("id"), ath.get("displayName"), (ath.get("position") or {}).get("abbreviation"),
                             int(bool(a.get("starter"))), int(bool(a.get("didNotPlay"))), a.get("reason"),
                             float(mn) if mn not in (None, "", "--") and str(mn).replace(".", "").isdigit() else 0.0,
                             num(s.get("PTS")), fgm, fga, f3m, f3a, ftm, fta, num(s.get("REB")), num(s.get("AST")),
                             num(s.get("TO")), num(s.get("STL")), num(s.get("BLK")), num(s.get("OREB")), num(s.get("DREB")),
                             num(s.get("PF")), num(s.get("+/-"))))
    return rows


def season_dates(y):
    d, end = date(y, 10, 1), min(date(y + 1, 9, 30) if y != 2019 else date(2020, 10, 15), date.today() - timedelta(days=1))
    while d <= end:
        yield d
        d += timedelta(days=1)


def main(y0, y1):
    con = init()
    done_d = {r[0] for r in con.execute("SELECT d FROM dates_done")}
    have = {r[0] for r in con.execute("SELECT event_id FROM games")}
    boxed = {r[0] for r in con.execute("SELECT DISTINCT event_id FROM box")}
    recent = {(date.today() - timedelta(days=k)).strftime("%Y%m%d") for k in range(1, 4)}   # always re-check the last 3 days
    todo_d = [d for y in range(y0, y1 + 1) for d in season_dates(y) if d.strftime("%Y%m%d") not in done_d - recent]
    print(f"{len(todo_d)} dates to scan", flush=True)

    def scan(d):
        return d, get(f"{U}/scoreboard", {"dates": d.strftime("%Y%m%d"), "limit": 30})

    with ThreadPoolExecutor(8) as ex:
        for i, (d, j) in enumerate(ex.map(scan, todo_d), 1):
            if j is None:
                continue
            n = 0
            for e in j.get("events", []):
                stype = e.get("season", {}).get("type")
                comp = e["competitions"][0]
                if stype not in KEEP or comp.get("status", {}).get("type", {}).get("completed") is not True:
                    continue
                cs = {c["homeAway"]: c for c in comp["competitors"]}
                v = comp.get("venue", {}); addr = v.get("address", {})
                con.execute("INSERT OR IGNORE INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (e["id"], e["season"]["year"] - 1, stype, e["date"][:10],
                             cs["home"]["team"]["abbreviation"], cs["away"]["team"]["abbreviation"],
                             num(cs["home"].get("score")), num(cs["away"].get("score")), int(bool(comp.get("neutralSite"))),
                             v.get("fullName"), addr.get("city"), addr.get("state")))
                n += 1
            con.execute("INSERT OR REPLACE INTO dates_done VALUES (?,?)", (d.strftime("%Y%m%d"), n))
            if i % 100 == 0:
                con.commit(); print("dates", i, flush=True)
    con.commit()
    todo_e = [r[0] for r in con.execute("SELECT event_id FROM games WHERE season BETWEEN ? AND ?", (y0, y1)) if r[0] not in boxed]
    print(f"{len(todo_e)} box scores to fetch", flush=True)

    def summ(eid):
        return eid, get(f"{U}/summary", {"event": eid})

    t0 = time.time()
    with ThreadPoolExecutor(10) as ex:
        for i, (eid, j) in enumerate(ex.map(summ, todo_e), 1):
            rows = parse_summary(eid, j) if j else []
            if rows:
                con.executemany(f"INSERT INTO box VALUES ({','.join('?' * 25)})", rows)
            else:
                con.execute("INSERT OR IGNORE INTO failed VALUES (?)", (eid,))
            if i % 250 == 0:
                con.commit(); print("box", i, f"{time.time() - t0:.0f}s", flush=True)
    con.commit()
    print("done", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
