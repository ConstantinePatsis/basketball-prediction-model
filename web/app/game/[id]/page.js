import Link from "next/link";
import { notFound } from "next/navigation";
import { slate, pct, gap, ev, mins, side, time, day } from "@/lib";
import LogChart from "@/components/LogChart";
import LinesTable from "@/components/LinesTable";
export function generateStaticParams() { return (slate.games || []).map((g) => ({ id: g.id })); }
export default async function Game({ params }) {
  const { id } = await params;
  const g = (slate.games || []).find((x) => x.id === id);
  if (!g) notFound();
  const picks = g.lines.filter((l) => l.pick).slice(0, 10);
  const inj = [...(g.injuries[g.home] || []).map((x) => ({ ...x, t: g.home_name })), ...(g.injuries[g.away] || []).map((x) => ({ ...x, t: g.away_name }))];
  const label = { OUT: "out", GTD: "doubtful", LIKELY_OUT: "likely out" };
  return (<>
    <p className="dim" style={{ margin: "0 0 6px" }}><Link href="/">Today</Link> / {g.home_name} vs {g.away_name}</p>
    <div className="matchup"><h1>{g.home_name}<span>vs</span>{g.away_name}</h1><span className="dim">{day(g.tipoff)}, {time(g.tipoff)} Athens</span></div>
    {inj.length > 0 && <div className="chips">{inj.map((x, i) => <span key={i} className={`chip ${x.status}`}>{x.t}: {x.player} {label[x.status]}{x.min ? ` (${Math.round(x.min)} min/game)` : ""}</span>)}</div>}
    <h2>The model's {picks.length} strongest picks, and why</h2>
    {picks.map((l, i) => (
      <article className="card" key={i}>
        <div>
          <div className="player">{l.player}<small>{l.team}</small></div>
          <div className="pick"><span className={`side ${l.side}`}>{side(l.side)}</span> {l.line} {l.stat_label} <span className="dim" style={{ fontWeight: 500 }}>at {l.odds.toFixed(2)}</span></div>
          {l.tier && <span className={`tier ${l.tier}`}>{l.tier}</span>}
          <div className="nums">
            <div><strong className="hot">{gap(l.edge)}</strong>gap (points)</div>
            <div><strong>{ev(l.ev)}</strong>expected return</div>
            <div><strong>{pct(l.model_p)}</strong>model's chance</div>
            <div><strong>{pct(l.book_p)}</strong>Stoiximan's chance</div>
            <div><strong>{l.model_mean.toFixed(1)}</strong>projection vs {l.line}</div>
            <div><strong>{mins(l)}</strong>expected minutes</div>
          </div>
        </div>
        <LogChart logs={l.logs} line={l.line} sideName={l.side} projection={l.model_mean} />
        <ul className="reasons">{l.reasons.map((r, j) => <li key={j}>{r}</li>)}</ul>
      </article>))}
    <details className="all"><summary>All {g.lines.length} Stoiximan lines for this game</summary>
      <LinesTable lines={g.lines} />
    </details>
  </>);
}
