"""Live Stoiximan player-prop main lines for given fixtures -> runner/lines.csv (1 API request per fixture)."""
import json, sys, requests, pandas as pd
import os; K = os.environ.get("ODDSPAPI_KEY") or open("/home/claude/odds/.oddspapi_key").read().strip(); B = "https://api.oddspapi.io/v4"
mm = {str(x["marketId"]): x for x in json.load(open("/home/claude/odds/markets_basketball.json"))}
STAT = {"playertotals-points": "pts", "playertotals-rebounds": "reb", "playertotals-assists": "ast", "playertotals-3pointers": "fg3m",
        "playertotals-ptsreb": "pr", "playertotals-ptsass": "pa", "playertotals-ptsassreb": "pra", "playertotals-assreb": "ra"}
rows = []
for f in sys.argv[1:]:
    j = requests.get(f"{B}/odds", params={"apiKey": K, "fixtureId": f, "bookmakers": "stoiximan"}, timeout=60).json()
    json.dump(j, open(f"/home/claude/odds/live_{f}.json", "w"))
    for m, v in j["bookmakerOdds"]["stoiximan"]["markets"].items():
        d = mm.get(m, {}); st = STAT.get(d.get("marketType"))
        if not st: continue
        o_id, u_id = str(d["outcomes"][0]["outcomeId"]), str(d["outcomes"][1]["outcomeId"])
        ov = v["outcomes"].get(o_id, {}).get("players", {}); un = v["outcomes"].get(u_id, {}).get("players", {})
        for pid in set(ov) & set(un):
            o, u = ov[pid], un[pid]
            if o.get("active") and u.get("active"):
                rows.append({"player": o["playerName"], "stat": st, "line": d["handicap"], "over_odds": o["price"], "under_odds": u["price"], "book": "Stoiximan"})
L = pd.DataFrame(rows)
L["gap"] = (L.over_odds - L.under_odds).abs()
L = L.sort_values("gap").groupby(["player", "stat"]).head(1).drop(columns="gap").sort_values(["player", "stat"])
L.to_csv("/home/claude/runner/lines.csv", index=False)
print(len(L), "main lines"); print(L.to_string(index=False))
