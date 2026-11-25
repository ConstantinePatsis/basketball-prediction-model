"""
Collect EuroLeague games and player box scores into a local SQLite database.

Usage (on your laptop):
    pip install euroleague-api pandas
    python collect_euroleague.py                 # seasons 2016-17 to the current one
    python collect_euroleague.py --start 2016 --end 2026

Safe to stop and re-run: games already in the database are skipped.
Output: euroleague.db with three tables
    games             one row per game (date, round, teams, score)
    player_boxscores  one row per player per game (minutes, points, rebounds, assists, ...)
    failed            games that could not be fetched (re-run the script to retry them)
"""

import argparse
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from euroleague_api.boxscore_data import BoxScoreData

DB_PATH = "euroleague.db"
WORKERS = 6                  # parallel requests (kept modest to be polite to the API)
COMPETITION = "E"            # "E" = EuroLeague, "U" = EuroCup


# ---------- database helpers ----------

def existing_columns(con, table):
    rows = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [r[1] for r in rows]


def append_df(con, df, table):
    """Append a dataframe, adding any columns the table doesn't have yet
    (the API's columns vary slightly between seasons)."""
    if df.empty:
        return
    cols = [c.lower() for c in existing_columns(con, table)]
    if cols:
        for c in df.columns:
            if c.lower() not in cols:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}"')
    df.to_sql(table, con, if_exists="append", index=False)


def already_done(con):
    if "player_boxscores" not in [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]:
        return set()
    return set(con.execute(
        "SELECT DISTINCT Season, Gamecode FROM player_boxscores").fetchall())


# ---------- cleaning ----------

def minutes_to_float(value):
    """'27:45' -> 27.75 ; 'DNP' / None -> 0.0"""
    if not isinstance(value, str) or ":" not in value:
        return 0.0
    m, s = value.split(":")[:2]
    try:
        return int(m) + int(s) / 60
    except ValueError:
        return 0.0


def clean_boxscore(df):
    # drop the 'Team' and 'Total' summary rows; keep players only
    df = df[~df["Player"].isin(["Team", "Total"])].copy()
    if "Minutes" in df.columns:
        df["Minutes_float"] = df["Minutes"].apply(minutes_to_float)
    return df


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2016,
                        help="first season start year (2016 = 2016-17)")
    parser.add_argument("--end", type=int, default=2026,
                        help="last season start year (2026 = 2026-27)")
    args = parser.parse_args()

    api = BoxScoreData(COMPETITION)
    con = sqlite3.connect(DB_PATH)
    done = already_done(con)
    print(f"{len(done)} games already in {DB_PATH}")

    for season in range(args.start, args.end + 1):
        print(f"\n=== Season {season}-{str(season + 1)[-2:]} ===")
        try:
            schedule = api.get_gamecodes_season(season)
        except Exception as e:
            print(f"  could not get schedule: {e}")
            continue

        schedule = schedule[schedule["played"] == True].copy()  # noqa: E712
        # SQLite column names are case-insensitive: 'gamecode' clashes with 'gameCode'
        schedule = schedule.rename(columns={"gamecode": "game_id"})
        schedule.insert(0, "Season", season)

        # store/refresh this season's game list
        con.execute("CREATE TABLE IF NOT EXISTS games (Season INTEGER)")
        con.execute("DELETE FROM games WHERE Season = ?", (season,))
        append_df(con, schedule.astype(str).assign(Season=season), "games")
        con.commit()

        todo = [g for g in schedule["gameCode"].tolist()
                if (season, int(g)) not in done]
        print(f"  {len(schedule)} played games, {len(todo)} to fetch")

        def fetch(gamecode):
            last = None
            for attempt in range(3):
                try:
                    return gamecode, clean_boxscore(
                        api.get_players_boxscore_stats(season, int(gamecode))), None
                except Exception as e:
                    last = e
                    time.sleep(3 * (attempt + 1))
            return gamecode, None, last

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(fetch, g) for g in todo]
            for i, fut in enumerate(as_completed(futures), 1):
                gamecode, box, err = fut.result()
                if box is not None:
                    append_df(con, box, "player_boxscores")
                else:
                    print(f"  game {gamecode}: failed ({err})")
                    con.execute("CREATE TABLE IF NOT EXISTS failed "
                                "(Season INTEGER, Gamecode INTEGER, error TEXT)")
                    con.execute("INSERT INTO failed VALUES (?, ?, ?)",
                                (season, int(gamecode), str(err)[:200]))
                con.commit()
                if i % 50 == 0:
                    print(f"  {i}/{len(todo)} done")

    # summary
    print("\n=== Summary ===")
    print(pd.read_sql(
        "SELECT Season, COUNT(DISTINCT Gamecode) AS games, COUNT(*) AS player_rows "
        "FROM player_boxscores GROUP BY Season ORDER BY Season", con).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
