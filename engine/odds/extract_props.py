"""Stoiximan historical player props -> one row per (game, player, stat) main line.
bet price   = last price posted at least 6 hours before tip-off (when we'd realistically run the model)
close price = last price before tip-off
main line   = the line whose over/under odds were closest to each other at bet time"""
import json, glob, os, numpy as np, pandas as pd

mm = {str(x["marketId"]): x for x in json.load(open("/home/claude/odds/markets_basketball.json"))}
names = json.load(open("/home/claude/odds/player_names.json"))
fx = pd.read_parquet("/home/claude/odds/el_fixtures.parquet").set_index("fixtureId")
STAT = {"playertotals-points": "pts", "playertotals-rebounds": "reb", "playertotals-assists": "ast",
        "playertotals-3pointers": "fg3m", "playertotals-ptsreb": "pr", "playertotals-ptsass": "pa",
        "playertotals-ptsassreb": "pra", "playertotals-assreb": "ra"}


def price_at(hist, t):
    """last active price created at or before t"""
    ok = [h for h in hist if pd.Timestamp(h["createdAt"]) <= t]
    if not ok or not ok[-1].get("active", True):
        return np.nan
    return ok[-1]["price"]


rows = []
for p in glob.glob("/home/claude/odds/hist/*.json"):
    f = os.path.basename(p)[:-5]
    j = json.load(open(p))
    mk = (j.get("bookmakers") or {}).get("stoiximan", {}).get("markets", {})
    tip = fx.loc[f, "startTime"]
    bet_t = tip - pd.Timedelta(hours=6)
    for m, v in mk.items():
        d = mm.get(m, {})
        st = STAT.get(d.get("marketType"))
        if not st:
            continue
        over_id, under_id = str(d["outcomes"][0]["outcomeId"]), str(d["outcomes"][1]["outcomeId"])
        ov = v["outcomes"].get(over_id, {}).get("players", {})
        un = v["outcomes"].get(under_id, {}).get("players", {})
        for pid in set(ov) & set(un):
            o_h, u_h = ov[pid], un[pid]
            first = max(pd.Timestamp(o_h[0]["createdAt"]), pd.Timestamp(u_h[0]["createdAt"]))
            t_bet = bet_t if first <= bet_t else first          # line posted late: bet when it appears
            if t_bet >= tip:
                continue
            rows.append({"fixtureId": f, "tipoff": tip, "player_oid": pid, "player_name": names.get(pid),
                         "stat": st, "line": d["handicap"],
                         "over_bet": price_at(o_h, t_bet), "under_bet": price_at(u_h, t_bet),
                         "over_close": price_at(o_h, tip - pd.Timedelta(minutes=1)),
                         "under_close": price_at(u_h, tip - pd.Timedelta(minutes=1)),
                         "bet_time": t_bet, "posted_late": first > bet_t})
L = pd.DataFrame(rows).dropna(subset=["over_bet", "under_bet"])
L["gap"] = (L.over_bet - L.under_bet).abs()
main = L.sort_values("gap").groupby(["fixtureId", "player_oid", "stat"]).head(1)
main.to_parquet("/home/claude/odds/stoiximan_main_lines.parquet", index=False)
L.to_parquet("/home/claude/odds/stoiximan_all_lines.parquet", index=False)
print("all lines:", len(L), "| main lines:", len(main), "| games:", main.fixtureId.nunique())
print("named players:", round(main.player_name.notna().mean(), 3))
print(main.stat.value_counts().to_string())
print("avg bookmaker margin:", round(float((1 / main.over_bet + 1 / main.under_bet - 1).mean()), 4))
print("posted later than 6h before tip-off:", round(main.posted_late.mean(), 3))
