import { backtest } from "@/lib";
export default function Backtest() {
  const b = backtest || {}, acc = b["accuracy (Brier, lower=better)"] || {}, e5 = b["BETS: model edge >= 5 pts"] || {}, e10 = b["BETS: model edge >= 10 pts"] || {};
  const rows = [["Model gap ≥ 5 points", e5], ["Model gap ≥ 10 points", e10], ["Blend of model + Stoiximan, later rounds", b["BETS on later rounds using the blend, edge >= 3 pts"] || {}]];
  return (<>
    <h1>Backtest against Stoiximan</h1>
    <p className="sub">{b["lines graded"]} real Stoiximan player-prop lines from {b.games} EuroLeague games (2026-27, rounds 1–13). Price taken 6 hours before tip-off; model used only pre-game information.</p>
    <div className="tablewrap card"><table><thead><tr><th></th><th className="num">Bets</th><th className="num">Win %</th><th className="num">Break-even %</th><th className="num">ROI</th><th className="num">95% range</th></tr></thead>
      <tbody>{rows.map(([k, v]) => (<tr key={k}><td>{k}</td><td className="num">{v.bets}</td><td className="num">{v["win %"]}%</td><td className="num muted">{v["break-even win %"]}%</td>
        <td className="num pos">{v["ROI %"]}%</td><td className="num muted">{v["ROI 95% range %"]?.join("% to ")}%</td></tr>))}</tbody></table></div>
    <h2>Accuracy (Brier score, lower is better)</h2>
    <div className="grid">{Object.entries(acc).map(([k, v]) => (<div className="card kpi" key={k}><div className="v">{v}</div><div className="l">{k}</div></div>))}</div>
    <div className="note">Checks passed: not just betting unders (blind unders lose 1.2%), still +9% with no injury knowledge, positive in every month. Limits: one bookmaker, ~2.5 months; real bookmakers limit winning accounts.</div>
  </>);
}
