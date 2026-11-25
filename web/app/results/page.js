import { results, eur, when } from "@/lib";
function Chart({ points }) {
  if (!points?.length) return null;
  const W = 900, H = 200, P = 12, vals = points.map((p) => p.profit_eur), mx = Math.max(0, ...vals), mn = Math.min(0, ...vals);
  const x = (i) => (points.length === 1 ? W / 2 : (i / (points.length - 1)) * W), y = (v) => P + (H - 2 * P) - ((v - mn) / (mx - mn || 1)) * (H - 2 * P);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.profit_eur).toFixed(1)}`).join(" ");
  return (<svg viewBox={`0 0 ${W} ${H + 20}`} style={{ width: "100%" }}>
    <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="#262c36" />
    <path d={d} fill="none" stroke="#f0883e" strokeWidth="2.5" />
    {points.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.profit_eur)} r="3.5" fill="#f0883e" />)}
    <text x="0" y={H + 16} fill="#8b949e" fontSize="12">{points[0].date}</text>
    <text x={W} y={H + 16} fill="#8b949e" fontSize="12" textAnchor="end">{points.at(-1).date}</text>
  </svg>);
}
function Split({ title, rows }) {
  return (<><h2>{title}</h2><div className="tablewrap"><table><thead><tr><th></th><th className="num">Bets</th><th className="num">Win %</th>
    <th className="num">Break-even %</th><th className="num">Profit</th><th className="num">ROI</th></tr></thead><tbody>
    {Object.entries(rows || {}).map(([k, v]) => (<tr key={k}><td>{k}</td><td className="num">{v.bets}</td><td className="num">{v.win_pct}%</td>
      <td className="num muted">{v.breakeven_pct}%</td><td className={`num ${v.profit_eur >= 0 ? "pos" : "neg"}`}>{eur(v.profit_eur)}</td>
      <td className={`num ${v.roi_pct >= 0 ? "pos" : "neg"}`}>{v.roi_pct}%</td></tr>))}</tbody></table></div></>);
}
export default function Results() {
  const o = results.overall || {}, a = results.accuracy || {};
  return (<>
    <h1>Paper results</h1>
    <p className="sub">Every flagged pick, €{results.stake_eur} paper stake each, graded with official box scores. Voids (player didn't play) excluded.</p>
    <div className="grid">
      <div className="card kpi"><div className={`v ${o.profit_eur >= 0 ? "pos" : "neg"}`}>{eur(o.profit_eur)}</div><div className="l">Paper profit</div></div>
      <div className="card kpi"><div className="v">{o.roi_pct ?? "–"}%</div><div className="l">Return per bet</div></div>
      <div className="card kpi"><div className="v">{o.wins ?? 0}–{o.losses ?? 0}</div><div className="l">Won–lost ({o.win_pct ?? "–"}%, break-even {o.breakeven_pct ?? "–"}%)</div></div>
      <div className="card kpi"><div className="v">{a.brier_model ?? "–"} <span className="muted" style={{ fontSize: 15 }}>vs {a.brier_stoiximan ?? "–"}</span></div><div className="l">Accuracy, model vs Stoiximan (lower is better, {a.lines ?? 0} lines)</div></div>
    </div>
    <div className="note">{o.bets < 300 ? `${o.bets} settled bets is a small sample. Results mean little before a few hundred.` : "Sample is getting meaningful; keep watching the trend, not single nights."} {results.pending ? `${results.pending} picks waiting for results.` : ""}</div>
    <h2>Cumulative paper profit</h2><div className="card"><Chart points={results.cumulative} /></div>
    <Split title="By size of disagreement (points)" rows={results.by_edge} />
    <Split title="Over vs under" rows={results.by_side} />
    <Split title="By stat" rows={results.by_stat} />
    <Split title="By situation" rows={results.by_tag} />
    <h2>Latest graded picks</h2>
    <div className="tablewrap"><table><thead><tr><th>Game</th><th>Player</th><th>Bet</th><th className="num">Odds</th><th className="num">Actual</th><th>Result</th><th className="num">€</th></tr></thead>
      <tbody>{(results.recent || []).map((r, i) => (<tr key={i}><td className="muted">{r.game}</td><td>{r.player}</td>
        <td><span className={`side ${r.side}`}>{r.side === "OVER" ? "Over" : "Under"}</span> {r.line} {r.stat_label}</td>
        <td className="num">{r.bet_odds?.toFixed(2)}</td><td className="num">{r.actual}</td>
        <td className={r.result}>{r.result}</td><td className={`num ${r.profit_eur >= 0 ? "pos" : "neg"}`}>{eur(r.profit_eur)}</td></tr>))}</tbody></table></div>
  </>);
}
