import { backtest } from "@/lib";
export default function Backtest() {
  const b = backtest || {}, acc = b["accuracy (Brier, lower=better)"] || {};
  const rows = [["Gap of 5+ points", b["BETS: model edge >= 5 pts"]], ["Gap of 10+ points", b["BETS: model edge >= 10 pts"]], ["Model and Stoiximan blended, later rounds", b["BETS on later rounds using the blend, edge >= 3 pts"]]];
  return (<>
    <h1>Backtest against Stoiximan</h1>
    <p className="lede">{b["lines graded"]} real Stoiximan player-prop lines from {b.games} games this season, priced 6 hours before tip-off. The model only used information available before each game.</p>
    <div className="board"><table><thead><tr><th></th><th className="n">Picks</th><th className="n">Win rate</th><th className="n">Needed</th><th className="n">Return per pick</th><th className="n">Likely range</th></tr></thead>
      <tbody>{rows.map(([k, v = {}]) => (<tr key={k}><td><b>{k}</b></td><td className="n">{v.bets}</td><td className="n">{v["win %"]}%</td><td className="n dim">{v["break-even win %"]}%</td>
        <td className="n pos">+{v["ROI %"]}%</td><td className="n dim">{v["ROI 95% range %"]?.map((x) => `${x > 0 ? "+" : ""}${x}%`).join(" to ")}</td></tr>))}</tbody></table></div>
    <h2>Accuracy score (lower is better)</h2>
    <div className="stats">
      <div className="stat"><strong>{acc.model}</strong><span>model</span></div>
      <div className="stat"><strong>{acc["Stoiximan at bet time"]}</strong><span>Stoiximan</span></div>
      <div className="stat"><strong>{acc["coin flip"]}</strong><span>coin flip</span></div>
    </div>
    <div className="note">Checks passed: it isn't just betting unders (blind unders lose 1.2%), it still makes about +9% with no injury news at all, and it was positive in every month. Limits: one bookmaker and about 2.5 months of games.</div>
  </>);
}
