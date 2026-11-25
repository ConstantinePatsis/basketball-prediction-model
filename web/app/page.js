import Link from "next/link";
import { slate, pct, gap, ev, mins, side, time, day } from "@/lib";
export default function Today() {
  const games = slate.games || [];
  if (!games.length) return (<><h1>No games on the slate</h1><p className="lede">The next EuroLeague games appear here on game-day morning, after the 10:15 run.</p></>);
  const all = games.flatMap((g) => g.lines.filter((l) => l.pick).map((l) => ({ ...l, gid: g.id, game: `${g.home_name} – ${g.away_name}` })));
  const best = all.sort((a, b) => b.edge - a.edge).slice(0, 15);
  return (<>
    <h1>{day(games[0].tipoff)}</h1>
    <p className="lede">Round {slate.round}. {games.length} games, {all.length} lines where the model's chance beats Stoiximan's by at least 5 points. Pick a game to see the reasoning behind each pick.</p>
    <div className="strip">
      {games.map((g) => {
        const p = g.lines.filter((l) => l.pick), out = [...(g.injuries[g.home] || []), ...(g.injuries[g.away] || [])].filter((x) => x.status === "OUT").length;
        return (<Link className="tile" href={`/game/${g.id}`} key={g.id}>
          <div className="time">{time(g.tipoff)} Athens</div>
          <div className="teams">{g.home_name}<span>vs</span>{g.away_name}</div>
          <div className="facts"><span><strong>{p.length}</strong>picks</span><span><strong>{p.length ? gap(p[0].edge) : "–"}</strong>top gap</span><span><strong>{out}</strong>out</span></div>
        </Link>);
      })}
    </div>
    <h2>Biggest disagreements today</h2>
    <div className="board"><table>
      <thead><tr><th>Player</th><th>Pick</th><th className="n">Odds</th><th className="n">Projection</th><th className="n">Model</th><th className="n">Stoiximan</th>
        <th className="n">Gap</th><th className="n">EV</th><th className="n">Minutes</th><th className="n">L10</th><th></th></tr></thead>
      <tbody>{best.map((l, i) => (
        <tr key={i}>
          <td className="who"><Link href={`/game/${l.gid}`}><b>{l.player}</b><small>{l.team}</small></Link></td>
          <td><span className={`side ${l.side}`}>{side(l.side)}</span> {l.line} {l.stat_label}</td>
          <td className="n">{l.odds.toFixed(2)}</td><td className="n">{l.model_mean.toFixed(1)}</td>
          <td className="n">{pct(l.model_p)}</td><td className="n dim">{pct(l.book_p)}</td>
          <td className="n"><span className={`gap ${l.edge >= 0.15 ? "big" : ""}`}>{gap(l.edge)}</span></td>
          <td className="n">{ev(l.ev)}</td><td className="n">{mins(l)}</td>
          <td className="n">{l.n_l10 ? `${l.hit_l10}/${l.n_l10}` : "–"}</td>
          <td>{l.tier && <span className={`tier ${l.tier}`}>{l.tier}</span>}</td>
        </tr>))}</tbody>
    </table></div>
    <p className="disclaimer">Gap: model's chance minus Stoiximan's, in percentage points. EV: expected return per bet if the model is right. Minutes: expected, with normal range. L10: how often this pick would have won in his last 10 games. Paper trading only.</p>
  </>);
}
