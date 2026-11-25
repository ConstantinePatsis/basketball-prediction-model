import { slate, when } from "@/lib";
import LinesTable from "@/components/LinesTable";
const NAMES = { MUN: "Bayern", TEL: "Maccabi", PAM: "Valencia", PAN: "Panathinaikos", ASV: "ASVEL", MIL: "Milan", BAR: "Barcelona",
  ULK: "Fenerbahçe", DUB: "Dubai", PAR: "Partizan", OLY: "Olympiacos", HTA: "Hapoel Tel Aviv", BAS: "Baskonia", IST: "Anadolu Efes",
  MAD: "Real Madrid", ZAL: "Žalgiris", RED: "Crvena Zvezda", VIR: "Virtus", PRS: "Paris", BES: "Beşiktaş", MCO: "Monaco" };
const n = (c) => NAMES[c] || c;
export default function Today() {
  const games = slate.games || [];
  const picks = games.reduce((a, g) => a + g.lines.filter((l) => l.pick).length, 0);
  return (<>
    <h1>{games.length ? "Upcoming games" : "No upcoming games"}</h1>
    <p className="sub">{games.length ? `Round ${slate.round} · ${games.length} games · ${picks} picks where the model beats Stoiximan's price by 5+ points.` : "The next slate appears here on game day morning."}</p>
    <div className="note">Paper trading only. These are a model's estimates for research, recorded before tip-off and graded afterwards. Not betting advice.</div>
    {games.map((g) => (
      <section className="game card" key={g.game}>
        <div className="head"><h2>{n(g.home)} – {n(g.away)}</h2><span className="muted">{when(g.tipoff)}</span></div>
        <div style={{ margin: "8px 0 4px" }}>
          {[g.home, g.away].map((t) => (g.injuries[t] || []).map((p) => (
            <span key={t + p.player} className={`pill ${p.status === "OUT" ? "out" : "gtd"}`} style={{ marginRight: 6 }}>
              {n(t)}: {p.player} {p.status === "OUT" ? "out" : p.status === "GTD" ? "doubtful" : "likely out"}</span>)))}
        </div>
        <h3 className="muted" style={{ fontSize: 13, fontWeight: 500, margin: "14px 0 0" }}>Top 10 disagreements</h3>
        <LinesTable lines={g.lines} compact />
        <details><summary>All {g.lines.length} lines for this game</summary><LinesTable lines={g.lines} /></details>
      </section>))}
  </>);
}
