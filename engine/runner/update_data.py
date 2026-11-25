"""Daily data refresh: EuroLeague + 8 domestic leagues (current season), then rebuild links.

Usage:  python3 update_data.py [--season 2026]
"""
import argparse
import subprocess
import sys
import time

LEAGUES = ["acb", "lba", "aba", "isr", "lkl", "gbl", "bbl", "lnb"]


def run(cmd, cwd, timeout=3600):
    t = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    last = (r.stdout.strip().splitlines() or [""])[-2:]
    status = "ok" if r.returncode == 0 else f"FAILED ({r.stderr.strip().splitlines()[-1:]})"
    print(f"  {' '.join(cmd[1:3])}: {status} in {time.time() - t:.0f}s  {' | '.join(last)}", flush=True)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()
    s = str(a.season)
    print("EuroLeague:", flush=True)
    run([sys.executable, "collect_euroleague.py", "--start", s, "--end", s], "/home/claude")
    print("Domestic leagues:", flush=True)
    procs = []
    for lg in LEAGUES:                      # leagues run in parallel; each writes its own database
        procs.append((lg, subprocess.Popen([sys.executable, "-u", "run_league.py", lg, s, s, "6"],
                                           cwd="/home/claude/leagues", stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)))
    for lg, p in procs:
        out, _ = p.communicate(timeout=7200)
        saved = [l for l in out.splitlines() if "saved" in l]
        print(f"  {lg.upper()}: {saved[-1] if saved else out.strip().splitlines()[-1:] }", flush=True)
    print("Copying EuroLeague tables into basketball.db (the model reads them from there):", flush=True)
    import sqlite3
    b = sqlite3.connect("/home/claude/basketball.db")
    b.execute("ATTACH '/home/claude/euroleague.db' AS el")
    for dst, src in (("el_box", "player_boxscores"), ("el_games", "games")):
        b.execute(f"DELETE FROM {dst}")
        b.execute(f"INSERT INTO {dst} SELECT * FROM el.{src}")
        print(f"  {dst}: {b.execute(f'SELECT COUNT(*) FROM {dst}').fetchone()[0]} rows", flush=True)
    b.commit(); b.close()
    print("Linking players across competitions:", flush=True)
    run([sys.executable, "match_players.py"], "/home/claude/leagues")
    print("Done.")


if __name__ == "__main__":
    main()
