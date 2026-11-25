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
  return (<><h1>How it works</h1><p className="lede">The engine runs by itself on game days at 10:15 and 16:30, and grades results at 00:40 (Athens time).</p>
    <ol className="steps">{steps.map(([t, d]) => <li key={t}><b>{t}</b><span className="dim">{d}</span></li>)}</ol>
    <p className="disclaimer">Research and paper trading only.</p></>);
}
