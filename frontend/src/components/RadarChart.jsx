import { useState, useEffect, useRef } from "react"
import "./RadarChart.css"

const DIMS = [
  { key: "precio",      label: "Precio" },
  { key: "competencia", label: "Competencia" },
  { key: "experiencia", label: "Experiencia" },
  { key: "valor",       label: "Valor" },
  { key: "situacion",   label: "Situación" },
  { key: "vinculacion", label: "Vinculación" },
]

const N = DIMS.length
const CX = 150, CY = 150, R = 85, LEVELS = 4

function polar(index, value) {
  const a = (Math.PI * 2 / N) * index - Math.PI / 2
  const d = (value / 100) * R
  return [CX + d * Math.cos(a), CY + d * Math.sin(a)]
}

function hexPts(radius) {
  return Array.from({ length: N }, (_, i) => {
    const a = (Math.PI * 2 / N) * i - Math.PI / 2
    return `${CX + radius * Math.cos(a)},${CY + radius * Math.sin(a)}`
  }).join(" ")
}

const LABEL_POS = DIMS.map((_, i) => {
  const a = (Math.PI * 2 / N) * i - Math.PI / 2
  const d = R + 24
  const x = CX + d * Math.cos(a)
  const y = CY + d * Math.sin(a)
  const anchor = (i === 1 || i === 2) ? "start" : (i === 4 || i === 5) ? "end" : "middle"
  const dy = i === 0 ? -8 : i === 3 ? 14 : 4
  return { x, y: y + dy, anchor }
})

export default function RadarChart({ data }) {
  const [anim, setAnim] = useState({})
  const prevRef = useRef({})
  const rafRef = useRef(null)

  useEffect(() => {
    if (!data) return
    const from = { ...prevRef.current }
    const to = { ...data }
    const t0 = performance.now()

    function tick(now) {
      const p = Math.min((now - t0) / 800, 1)
      const e = 1 - Math.pow(1 - p, 3)
      const cur = {}
      DIMS.forEach(d => {
        cur[d.key] = (from[d.key] || 0) + ((to[d.key] || 0) - (from[d.key] || 0)) * e
      })
      setAnim(cur)
      if (p < 1) rafRef.current = requestAnimationFrame(tick)
      else prevRef.current = to
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [data])

  const hasData = data && Object.values(data).some(v => v > 0)
  const pts = DIMS.map((d, i) => polar(i, anim[d.key] || 0))
  const polyStr = pts.map(([x, y]) => `${x},${y}`).join(" ")

  return (
    <div className="radar-chart">
      <div className="radar-header">
        <span className="radar-title">Perfil de riesgo</span>
        {!hasData && <span className="radar-waiting">Esperando conversación</span>}
      </div>
      <svg viewBox="0 0 300 300" className="radar-svg">
        {/* Grid hexagons */}
        {Array.from({ length: LEVELS }, (_, i) => (
          <polygon key={i} points={hexPts(R * (i + 1) / LEVELS)} className="radar-grid" />
        ))}
        {/* Axis lines */}
        {DIMS.map((_, i) => {
          const [ex, ey] = polar(i, 100)
          return <line key={i} x1={CX} y1={CY} x2={ex} y2={ey} className="radar-axis" />
        })}
        {/* Data fill */}
        {hasData && <polygon points={polyStr} className="radar-fill" />}
        {/* Data stroke */}
        {hasData && <polygon points={polyStr} className="radar-stroke" />}
        {/* Dots */}
        {hasData && pts.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={2.5} className="radar-dot" />
        ))}
        {/* Labels */}
        {DIMS.map((d, i) => {
          const { x, y, anchor } = LABEL_POS[i]
          const val = Math.round(anim[d.key] || 0)
          return (
            <text key={i} x={x} y={y} textAnchor={anchor} className={`radar-label ${val > 60 ? "hot" : ""}`}>
              {d.label}
            </text>
          )
        })}
      </svg>
      {/* Legend values */}
      {hasData && (
        <div className="radar-legend">
          {DIMS.map(d => {
            const val = Math.round(anim[d.key] || 0)
            return (
              <div key={d.key} className="radar-legend-row">
                <span className="radar-legend-label">{d.label}</span>
                <div className="radar-legend-bar-track">
                  <div
                    className={`radar-legend-bar-fill ${val > 60 ? "high" : val > 30 ? "mid" : ""}`}
                    style={{ width: `${val}%` }}
                  />
                </div>
                <span className="radar-legend-val">{val}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
