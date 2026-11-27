const sign = (x) => (x == null ? "–" : `${x > 0 ? "+" : ""}${x}%`);
function Table({ rows }) {
  return (<div className="board"><table><thead><tr><th></th><th className="n">Picks</th><th className="n">Win rate</th><th className="n">Needed</th><th className="n">Return per pick</th><th className="n">Likely range</th></tr></thead>
    <tbody>{Object.entries(rows || {}).map(([k, v]) => (<tr key={k}><td><b>{k}</b></td><td className="n">{v.bets}</td><td className="n">{v["win %"]}%</td>
      <td className="n dim">{v["break-even win %"]}%</td><td className={`n ${v["ROI %"] >= 0 ? "pos" : "neg"}`}>{sign(v["ROI %"])}</td>
      <td className="n dim">{v["ROI 95% range %"]?.map(sign).join(" to ")}</td></tr>))}</tbody></table></div>);
}
export default function NbaBacktest({ b }) {
  if (!b || !b["lines graded"]) return (<><h1>NBA backtest</h1><p className="lede">The backtest appears here once it has run.</p></>);
  const acc = b["accuracy (Brier, lower=better)"] || {};
  return (<>
    <h1>NBA backtest against Stoiximan</h1>
    <p className="lede">{b["lines graded"].toLocaleString("en-GB")} real Stoiximan NBA player-prop lines from {b.games} games ({b.from} to {b.to}), priced 6 hours before tip-off. Stoiximan's average margin on these lines is {b["bookmaker margin %"]}%. The model only used information available before each game.</p>
    <Table rows={b.strategies} />
    <h2>Accuracy score (lower is better)</h2>
    <div className="stats">
      <div className="stat"><strong>{acc.model}</strong><span>model</span></div>
      <div className="stat"><strong>{acc["Stoiximan at bet time"]}</strong><span>Stoiximan</span></div>
      <div className="stat"><strong>{acc["blend 55/45"]}</strong><span>model and Stoiximan blended</span></div>
      <div className="stat"><strong>{acc["coin flip"]}</strong><span>coin flip</span></div>
    </div>
    <h2>Week by week (top 10 per game)</h2><Table rows={b["by week (top 10 per game)"]} />
    <h2>By stat (gap 5+)</h2><Table rows={b["by stat (gap 5+)"]} />
    <h2>Over or under (gap 5+)</h2><Table rows={b["by side (gap 5+)"]} />
    <div className="note">Blind bets lose: always under {sign(b["always under ROI %"])}, always over {sign(b["always over ROI %"])}. The likely range resamples whole games, because lines in the same game tend to win or lose together. Without injury news (assuming everyone from the last three games plays) the top-10 strategy still returned about +16%. The model is overconfident at the extremes: when it says 75%+, those picks won about 60%. Points and points-combo lines roughly break even; the gains come from assists, rebounds and threes. Limits: one bookmaker and five weeks of one season, so treat the paper log as the real test.</div>
  </>);
}
