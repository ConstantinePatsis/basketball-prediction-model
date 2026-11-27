export default function About() {
  const steps = [
    ["Collect the history", "Ten seasons of EuroLeague box scores plus eight domestic leagues, about 23,000 games, linked player by player."],
    ["Read the injury news", "Each game day the official injury report is read automatically. Players ruled out are removed and their minutes go to their usual replacements."],
    ["Predict minutes", "A model trained on 2016–2023 predicts each player's minutes and a normal range."],
    ["Predict production per minute", "Points, rebounds, assists and threes per minute from recent and long-term form, the opponent and the game situation."],
    ["Play the game 8,000 times", "Each run draws realistic minutes and stats. Counting the runs gives the chance of every over and under."],
    ["Compare with Stoiximan", "Odds become Stoiximan's chance with its margin removed. When the model's chance is 5+ points higher, the line becomes a pick."],
    ["Log and grade", "Picks are saved before tip-off and graded from the official box score after the game."],
  ];
  const nba = [
    ["Ten seasons of NBA box scores", "About 12,600 games since 2016–17 from ESPN's public feed, updated every morning."],
    ["Injury statuses", "Before each run the model reads every player's status. Players ruled out are removed and their minutes go to the usual replacements; game-time decisions get no pick."],
    ["Same engine, trained on NBA", "Minutes and per-minute models trained on 2016–2023, tuned on 2024–25 and tested on 2025–26. Rest, back-to-backs and travel were tested and added nothing, so they're left out."],
    ["Top 10 per game", "Each night the 10 biggest gaps per game are logged with a €10 paper stake, then graded the next morning."],
  ];
  return (<><h1>How it works</h1><p className="lede">The EuroLeague engine runs by itself on game days every two hours from 09:07 and grades results at 00:41 (Athens time). The NBA engine runs at 19:17 and 00:17 and grades at 10:17.</p>
    <ol className="steps">{steps.map(([t, d]) => <li key={t}><b>{t}</b><span className="dim">{d}</span></li>)}</ol>
    <h2>NBA differences</h2>
    <ol className="steps">{nba.map(([t, d]) => <li key={t}><b>{t}</b><span className="dim">{d}</span></li>)}</ol>
    <p className="disclaimer">Research and paper trading only.</p></>);
}
