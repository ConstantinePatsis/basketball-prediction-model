# EuroLeague player-prop model

A research model that predicts EuroLeague player stats (minutes, points, rebounds, assists, threes and combos),
turns them into over/under probabilities with 8,000 simulations per player, and compares them with Stoiximan's
player-prop lines. Picks are logged before tip-off and graded from official box scores. **Paper trading only.**

## Layout
- `engine/` – data collectors (EuroLeague + 8 domestic leagues), trained models, injury reader, odds feed, paper log
  - `runner/daily_run.py` – the autopilot (`picks` / `grade`)
  - `runner/export_site.py` – writes the website data
- `web/` – Next.js site (Vercel), password protected
- `data/seed/` – starting databases; later runs keep databases in the GitHub Actions cache
- `.github/workflows/model.yml` – schedule: 10:15 and 16:30 picks, 00:40 grading (Athens time)

## Setup
1. Repository secret `ODDSPAPI_KEY` (Settings → Secrets and variables → Actions).
2. Vercel: import the repo, set **Root Directory** to `web`, add environment variable `SITE_PASSWORD` (Production), then redeploy.
   Live at https://model.konstantinospatsis.com (user `konstantinos`).
3. Optional: add a custom domain in Vercel → Project → Settings → Domains.

## Results so far
Backtest vs 6,438 Stoiximan lines (2026-27 rounds 1–13): model gap ≥ 5 points → 57.7% wins, +9.8% ROI (95% range +6% to +14%).
One bookmaker and ~2.5 months: confirm with live paper results before trusting it.
