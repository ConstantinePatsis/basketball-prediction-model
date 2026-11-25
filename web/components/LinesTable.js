"use client";
import { useMemo, useState } from "react";
const pct = (x) => (x == null ? "–" : `${Math.round(100 * x)}%`);
export default function LinesTable({ lines, compact = false }) {
  const [stat, setStat] = useState("All");
  const [onlyPicks, setOnlyPicks] = useState(compact);
  const [q, setQ] = useState("");
  const stats = useMemo(() => ["All", ...Array.from(new Set(lines.map((l) => l.stat_label)))], [lines]);
  const rows = lines
    .filter((l) => stat === "All" || l.stat_label === stat)
    .filter((l) => !onlyPicks || l.pick)
    .filter((l) => !q || l.player.toLowerCase().includes(q.toLowerCase()))
    .slice(0, compact ? 10 : 1000);
  return (
    <div>
      {!compact && (
        <div className="controls">
          <select value={stat} onChange={(e) => setStat(e.target.value)}>{stats.map((s) => <option key={s}>{s}</option>)}</select>
          <input placeholder="Player…" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="muted" style={{ alignSelf: "center" }}>
            <input type="checkbox" checked={onlyPicks} onChange={(e) => setOnlyPicks(e.target.checked)} /> picks only
          </label>
        </div>
      )}
      <div className="tablewrap"><table>
        <thead><tr><th>Player</th><th>Bet</th><th className="num">Odds</th><th className="num">Model expects</th>
          <th className="num">Model %</th><th className="num">Stoiximan %</th><th>Gap</th><th className="num">Min</th></tr></thead>
        <tbody>{rows.map((l, i) => (
          <tr key={i} style={{ opacity: l.pick ? 1 : 0.55 }}>
            <td>{l.player} <span className="muted">{l.team}</span>{l.status === "GTD" || l.status === "LIKELY_OUT" ? <span className="pill gtd" style={{ marginLeft: 6 }}>doubtful</span> : null}</td>
            <td><span className={`side ${l.side}`}>{l.side === "OVER" ? "Over" : "Under"}</span> {l.line} {l.stat_label}</td>
            <td className="num">{l.odds?.toFixed(2)}</td>
            <td className="num">{l.model_mean?.toFixed(1)}</td>
            <td className="num">{pct(l.model_p)}</td>
            <td className="num">{pct(l.book_p)}</td>
            <td><div className="bar"><i style={{ width: `${Math.max(0, Math.min(100, (l.edge / 0.35) * 100))}%`, opacity: l.pick ? 1 : 0.35 }} /></div></td>
            <td className="num muted">{l.expected_minutes?.toFixed(0)}</td>
          </tr>))}</tbody>
      </table></div>
    </div>
  );
}
