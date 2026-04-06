import "./SentimentLine.css"

// Catmull-Rom → cubic bezier para curvas suaves tipo sinusoide
function catmullRomPath(xs, ys, tension = 0.35) {
  const n = xs.length
  if (n < 2) return ""
  if (n === 2) return `M${xs[0]},${ys[0]} L${xs[1]},${ys[1]}`

  let d = `M${xs[0]},${ys[0]}`
  for (let i = 0; i < n - 1; i++) {
    const p0x = xs[Math.max(i - 1, 0)],     p0y = ys[Math.max(i - 1, 0)]
    const p1x = xs[i],                        p1y = ys[i]
    const p2x = xs[i + 1],                    p2y = ys[i + 1]
    const p3x = xs[Math.min(i + 2, n - 1)],  p3y = ys[Math.min(i + 2, n - 1)]

    const cp1x = p1x + (p2x - p0x) * tension
    const cp1y = p1y + (p2y - p0y) * tension
    const cp2x = p2x - (p3x - p1x) * tension
    const cp2y = p2y - (p3y - p1y) * tension

    d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2x},${p2y}`
  }
  return d
}

export default function SentimentLine({ points }) {
  if (!points || points.length === 0) {
    return (
      <div className="sentiment-chart" title="Evolución del sentimiento: traza la curva emocional del cliente a lo largo de la conversación, desde negativo (frustración, enojo) hasta positivo (receptividad, satisfacción). Permite detectar en qué momento las ontologías logran girar el sentimiento y dónde fallan, orientando las mejoras del prompt y las reglas de retención.">
        <span className="sentiment-title">Sentimiento</span>
        <span className="sentiment-waiting">—</span>
      </div>
    )
  }

  const W = 220, H = 80, PAD_X = 20, PAD_TOP = 10, PAD_BOT = 14
  const plotW = W - PAD_X * 2
  const plotH = H - PAD_TOP - PAD_BOT
  const n = points.length
  const midY = PAD_TOP + plotH / 2

  const xs = points.map((_, i) => PAD_X + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW))
  // Escalar al rango real para maximizar la amplitud visual
  const maxAbs = Math.max(Math.abs(Math.max(...points)), Math.abs(Math.min(...points)), 20)
  const ys = points.map(v => PAD_TOP + plotH / 2 - (v / maxAbs) * (plotH / 2))

  const pathD = catmullRomPath(xs, ys)
  const fillD = `${pathD} L${xs[n - 1]},${midY} L${xs[0]},${midY} Z`

  const last = points[points.length - 1]
  const label = last > 10 ? "Positivo" : last < -10 ? "Negativo" : "Neutro"

  return (
    <div className="sentiment-chart" title="Evolución del sentimiento: traza la curva emocional del cliente a lo largo de la conversación, desde negativo (frustración, enojo) hasta positivo (receptividad, satisfacción). Permite detectar en qué momento las ontologías logran girar el sentimiento y dónde fallan, orientando las mejoras del prompt y las reglas de retención.">
      <span className="sentiment-title">Sentimiento</span>
      <svg viewBox={`0 0 ${W} ${H}`} className="sentiment-svg">
        {/* Y axis */}
        <line x1={PAD_X} y1={PAD_TOP} x2={PAD_X} y2={H - PAD_BOT} className="sentiment-axis" />
        {/* X axis (zero line) */}
        <line x1={PAD_X} y1={midY} x2={W - PAD_X} y2={midY} className="sentiment-axis" />
        {/* Labels */}
        <text x={PAD_X - 3} y={PAD_TOP + 4} textAnchor="end" className="sentiment-axis-label">+</text>
        <text x={PAD_X - 3} y={H - PAD_BOT} textAnchor="end" className="sentiment-axis-label">−</text>
        {/* Fill */}
        <path d={fillD} className="sentiment-fill" />
        {/* Curve */}
        <path d={pathD} fill="none" stroke="var(--text)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        {/* Dots */}
        {xs.map((x, i) => (
          <circle key={i} cx={x} cy={ys[i]} r={i === n - 1 ? 3 : 2} className={`sentiment-dot ${i === n - 1 ? "current" : ""}`} />
        ))}
      </svg>
      <span className="sentiment-label-value">{label}</span>
    </div>
  )
}
