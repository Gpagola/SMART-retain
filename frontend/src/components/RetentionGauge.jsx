import { useState, useEffect, useRef } from "react"
import "./RetentionGauge.css"

export default function RetentionGauge({ value }) {
  const [anim, setAnim] = useState(0)
  const prevRef = useRef(0)
  const rafRef = useRef(null)

  useEffect(() => {
    if (value == null) return
    const from = prevRef.current
    const to = Math.max(0, Math.min(100, value))
    const t0 = performance.now()

    function tick(now) {
      const p = Math.min((now - t0) / 800, 1)
      const e = 1 - Math.pow(1 - p, 3)
      setAnim(from + (to - from) * e)
      if (p < 1) rafRef.current = requestAnimationFrame(tick)
      else prevRef.current = to
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [value])

  const hasData = value != null
  // Needle: 0% → points left (180°), 50% → points up (270°), 100% → points right (360°)
  const angleDeg = 180 + (anim / 100) * 180
  const rad = (angleDeg * Math.PI) / 180
  const needleLen = 52
  const cx = 80, cy = 75
  const nx = cx + needleLen * Math.cos(rad)
  const ny = cy + needleLen * Math.sin(rad)

  // Arc: semicircle from left to right, radius 62
  const R = 62
  const arcLen = Math.PI * R // ~194.8

  const label = anim >= 70 ? "Alta" : anim >= 40 ? "Media" : "Baja"

  return (
    <div className="gauge-chart" title="Probabilidad de retención: estima en tiempo real las posibilidades de que el cliente mantenga su póliza, calculada a partir del tono de la conversación, los argumentos del asistente y la receptividad del cliente. Un indicador clave para evaluar si las ontologías están generando respuestas persuasivas y efectivas.">
      <span className="gauge-title">Prob. retención</span>
      <svg viewBox="0 0 160 90" className="gauge-svg">
        {/* Background arc */}
        <path
          d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`}
          fill="none"
          stroke="var(--border)"
          strokeWidth="6"
          strokeLinecap="round"
        />
        {/* Value arc */}
        {hasData && (
          <path
            d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`}
            fill="none"
            stroke="var(--text)"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${(anim / 100) * arcLen} ${arcLen}`}
          />
        )}
        {/* Needle */}
        {hasData && (
          <>
            <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--text)" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx={cx} cy={cy} r="3.5" fill="var(--text)" />
          </>
        )}
        {/* Value text */}
        {hasData && (
          <text x={cx} y={cy - 18} textAnchor="middle" className="gauge-value">
            {Math.round(anim)}%
          </text>
        )}
      </svg>
      {hasData && <span className="gauge-label">{label}</span>}
      {!hasData && <span className="gauge-waiting">—</span>}
    </div>
  )
}
