// Last-10-games bars against the line (oldest left). Green = this pick would have won, red = lost.
export default function LogChart({ logs, line, sideName, projection }) {
  if (!logs?.length) return <p className="dim">No games yet this season.</p>;
  const g = [...logs].reverse(), W = 380, G = 70, H = 150, top = 14, bottom = 30, n = g.length;
  const max = Math.max(line * 1.6, projection || 0, ...g.map((x) => x.value), 1);
  const y = (v) => top + (H - top - bottom) * (1 - v / max), bw = ((W - G) / n) * 0.62, x = (i) => ((W - G) / n) * i + ((W - G) / n - bw) / 2;
  const won = (v) => (sideName === "OVER" ? v > line : v < line);
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Last ${n} games against the line of ${line}`}>
        {g.map((d, i) => (
          <g key={i}>
            <rect x={x(i)} y={y(d.value)} width={bw} height={Math.max(1.5, y(0) - y(d.value))} rx="3" fill={won(d.value) ? "#2E7D4F" : "#C2414B"} opacity="0.9" />
            <text x={x(i) + bw / 2} y={y(d.value) - 4} textAnchor="middle" fontSize="11" fill="#13233F" fontFamily="Barlow Condensed">{d.value}</text>
            <text x={x(i) + bw / 2} y={H - 14} textAnchor="middle" fontSize="10" fill="#5D6B7E">{d.opp}</text>
            <text x={x(i) + bw / 2} y={H - 3} textAnchor="middle" fontSize="9" fill="#8A96A6">{Math.round(d.min)}′</text>
          </g>))}
        <line x1="0" x2={W - G + 4} y1={y(line)} y2={y(line)} stroke="#13233F" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x={W - G + 8} y={y(line) + 4} fontSize="11" fill="#13233F" fontWeight="600">line {line}</text>
        {projection != null && <><line x1="0" x2={W - G + 4} y1={y(projection)} y2={y(projection)} stroke="#E2611B" strokeWidth="2" opacity="0.85" />
          <text x={W - G + 8} y={y(projection) + (Math.abs(y(projection) - y(line)) < 12 ? (projection > line ? -6 : 14) : 4)} fontSize="11" fill="#E2611B" fontWeight="600">model {projection.toFixed(1)}</text></>}
      </svg>
      <figcaption className="chart-cap">Last {n} games, oldest first. Dashed: Stoiximan line. Orange: model projection ({projection?.toFixed(1)}). Small numbers: minutes played.</figcaption>
    </figure>
  );
}
