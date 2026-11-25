import { results, eur } from "@/lib";
function Chart({ points }) {
  if (!points || points.length < 2) return <p className="dim">The chart starts after the first graded night.</p>;
  const W = 900, H = 220, P = 18, v = points.map((p) => p.profit_eur), mx = Math.max(0, ...v), mn = Math.min(0, ...v);
  const x = (i) => P + (i / (points.length - 1)) * (W - 2 * P), y = (val) => P + (H - 2 * P) * (1 - (val - mn) / (mx - mn || 1));
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.profit_eur).toFixed(1)}`).join(" ");
  return (<svg viewBox={`0 0 ${W} ${H + 18}`} width="100%" role="img" aria-label="Cumulative paper profit">
    <line x1={P} x2={W - P} y1={y(0)} y2={y(0)} stroke="#D9DEE5" strokeWidth="1.5" />
    <text x={P} y={y(0) - 6} fontSize="12" fill="#5D6B7E">€0</text>
    <path d={d} fill="none" stroke="#E2611B" strokeWidth="3" strokeLinejoin="round" />
    {points.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.profit_eur)} r="4" fill="#E2611B" />)}
    <text x={W - P} y={y(v.at(-1)) - 10} textAnchor="end" fontSize="16" fontWeight="700" fill="#13233F" fontFamily="Barlow Condensed">{eur(v.at(-1))}</text>
    <text x={P} y={H + 14} fontSize="12" fill="#5D6B7E">{points[1].date}</text>
    <text x={W - P} y={H + 14} fontSize="12" fill="#5D6B7E" textAnchor="end">{points.at(-1).date}</text>
  </svg>);
}
function Split({ title, rows }) {
  return (<><h2>{title}</h2><div className="board"><table><thead><tr><th></th><th className="n">Picks</th><th className="n">Won</th><th className="n">Win rate</th>
    <th className="n">Needed to break even</th><th className="n">Paper profit</th><th className="n">Return per pick</th></tr></thead><tbody>
    {Object.entries(rows || {}).map(([k, s]) => (<tr key={k}><td><b>{k}</b></td><td className="n">{s.bets}</td><td className="n">{s.wins}</td><td className="n">{s.win_pct}%</td>
      <td className="n dim">{s.breakeven_pct}%</td><td className={`n ${s.profit_eur >= 0 ? "pos" : "neg"}`}>{eur(s.profit_eur)}</td>
      <td className={`n ${s.roi_pct >= 0 ? "pos" : "neg"}`}>{s.roi_pct}%</td></tr>))}</tbody></table></div></>);
}
const TAGS = { injury: "Team missing a regular", after_hot_game: "After a big game", after_cold_game: "After a quiet game", plain: "No special situation" };
export default function Results() {
  const o = results.overall || {}, a = results.accuracy || {};
  return (<>
    <h1>Paper results</h1>
    <p className="lede">Every pick is logged before tip-off with a €{results.stake_eur} paper stake and graded from the official box score. Players who don't play are void.</p>
    <div className="stats">
      <div className="stat"><strong className={o.profit_eur >= 0 ? "pos" : "neg"}>{eur(o.profit_eur)}</strong><span>paper profit on {o.bets} picks</span></div>
      <div className="stat"><strong>{o.win_pct ?? "–"}%</strong><span>won ({o.wins}–{o.losses}); {o.breakeven_pct}% needed to break even</span></div>
      <div className="stat"><strong>{o.roi_pct ?? "–"}%</strong><span>return per pick</span></div>
      <div className="stat"><strong>{a.brier_model ?? "–"}</strong><span>model accuracy score vs Stoiximan's {a.brier_stoiximan ?? "–"} (lower is better)</span></div>
    </div>
    <div className="note">{o.bets < 300 ? `${o.bets} graded picks is still a small sample; a few hundred are needed before the numbers mean much.` : "The sample is getting meaningful. Watch the trend, not single nights."}{results.pending ? ` ${results.pending} picks are waiting for their games.` : ""}</div>
    <h2>Paper profit over time</h2><div className="stat"><Chart points={results.cumulative} /></div>
    <Split title="By size of the gap (points)" rows={results.by_edge} />
    <Split title="Over or under" rows={results.by_side} />
    <Split title="By stat" rows={results.by_stat} />
    <Split title="By situation" rows={Object.fromEntries(Object.entries(results.by_tag || {}).map(([k, v]) => [TAGS[k] || k, v]))} />
    <h2>Latest graded picks</h2>
    <div className="board"><table><thead><tr><th>Game</th><th>Player</th><th>Pick</th><th className="n">Odds</th><th className="n">Actual</th><th>Result</th><th className="n">Paper €</th></tr></thead>
      <tbody>{(results.recent || []).map((r, i) => (<tr key={i}><td className="dim">{r.game}</td><td><b>{r.player}</b></td>
        <td><span className={`side ${r.side}`}>{r.side === "OVER" ? "Over" : "Under"}</span> {r.line} {r.stat_label}</td>
        <td className="n">{r.bet_odds?.toFixed(2)}</td><td className="n">{r.actual}</td><td className={r.result}>{r.result === "win" ? "Won" : "Lost"}</td>
        <td className={`n ${r.profit_eur >= 0 ? "pos" : "neg"}`}>{eur(r.profit_eur)}</td></tr>))}</tbody></table></div>
  </>);
}
