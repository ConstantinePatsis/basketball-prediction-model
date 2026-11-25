"use client";
import { useMemo, useState } from "react";
const pct = (x) => (x == null ? "–" : `${Math.round(100 * x)}%`);
const gap = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(Math.round(100 * x))}`;
const mins = (l) => (l.expected_minutes == null ? "–" : `${Math.round(l.expected_minutes)}${l.min_low != null ? ` (${Math.round(l.min_low)}–${Math.round(l.min_high)})` : ""}`);
export default function LinesTable({ lines, showGame = false }) {
  const [stat, setStat] = useState("All");
  const [picks, setPicks] = useState(false);
  const [q, setQ] = useState("");
  const stats = useMemo(() => ["All", ...new Set(lines.map((l) => l.stat_label))], [lines]);
  const rows = lines.filter((l) => (stat === "All" || l.stat_label === stat) && (!picks || l.pick) && (!q || l.player.toLowerCase().includes(q.toLowerCase())));
  return (<>
    <div className="controls">
      <select aria-label="Stat" value={stat} onChange={(e) => setStat(e.target.value)}>{stats.map((s) => <option key={s}>{s}</option>)}</select>
      <input type="search" aria-label="Search player" placeholder="Search player" value={q} onChange={(e) => setQ(e.target.value)} />
      <label className="chk"><input type="checkbox" checked={picks} onChange={(e) => setPicks(e.target.checked)} /> Picks only</label>
    </div>
    <div className="board"><table>
      <thead><tr>{showGame && <th>Game</th>}<th>Player</th><th>Model side</th><th className="n">Odds</th><th className="n">Projection</th>
        <th className="n">Model</th><th className="n">Stoiximan</th><th className="n">Gap</th><th className="n">Minutes</th><th className="n">L10</th></tr></thead>
      <tbody>{rows.map((l, i) => (
        <tr key={i} style={{ opacity: l.pick ? 1 : 0.6 }}>
          {showGame && <td className="dim">{l.game}</td>}
          <td className="who"><b>{l.player}</b><small>{l.team}</small></td>
          <td><span className={`side ${l.side}`}>{l.side === "OVER" ? "Over" : "Under"}</span> {l.line} {l.stat_label}</td>
          <td className="n">{l.odds?.toFixed(2)}</td>
          <td className="n">{l.model_mean?.toFixed(1)}</td>
          <td className="n">{pct(l.model_p)}</td><td className="n dim">{pct(l.book_p)}</td>
          <td className="n"><span className={`gap ${l.edge >= 0.15 ? "big" : ""}`}>{gap(l.edge)}</span></td>
          <td className="n">{mins(l)}</td>
          <td className="n">{l.n_l10 ? `${l.hit_l10}/${l.n_l10}` : "–"}</td>
        </tr>))}</tbody>
    </table></div>
  </>);
}
