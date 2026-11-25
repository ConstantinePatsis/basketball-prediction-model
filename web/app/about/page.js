export default function About() {
  const steps = [
    ["Collect history", "10 seasons of EuroLeague box scores plus 8 domestic leagues (~23,000 games), linked player by player."],
    ["Read injury news", "The official EuroLeague report (via Eurohoops) is parsed each game day: players ruled out are removed, returning players added back."],
    ["Predict minutes", "A model trained on 2016–2023 predicts each player's minutes and a realistic low/high range."],
    ["Predict per-minute production", "Points, rebounds, assists and threes per minute from recent and long-term form, matchup and opponent."],
    ["Simulate 8,000 games", "Each run draws minutes and stats; counting the runs gives the chance of every over/under line."],
    ["Compare with Stoiximan", "Odds are turned into Stoiximan's chance with its margin removed. A gap of 5+ points is flagged as a pick."],
    ["Record and grade", "Picks are logged with a timestamp before tip-off and graded automatically from the official box score."],
  ];
  return (<><h1>How it works</h1><p className="sub">Runs automatically on GitHub Actions each game day; this site rebuilds after every run.</p>
    {steps.map(([t, d], i) => (<div className="card" key={t} style={{ marginBottom: 10 }}><b>{i + 1}. {t}</b><div className="muted">{d}</div></div>))}
    <div className="note">Research and paper trading only.</div></>);
}
