import { useState, useEffect, useCallback } from "react"
import "./EvaluationCard.css"

const API = import.meta.env.VITE_API_URL || "/api"

function ScoreBar({ score }) {
  const pct = (score / 10) * 100
  const color = score >= 8 ? "#22c55e" : score >= 6 ? "#f59e0b" : "#ef4444"
  return (
    <div className="ec-score-wrap">
      <div className="ec-score-track">
        <div className="ec-score-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="ec-score-num" style={{ color }}>{score}/10</span>
    </div>
  )
}

function ApplyButton({ nivel, recomendacion, status, onApply }) {
  if (status === "ok")    return <span className="ec-apply-ok">✓ Aplicado</span>
  if (status === "error") return <span className="ec-apply-err">✗ Error</span>
  return (
    <button
      className="ec-btn-apply"
      disabled={status === "loading"}
      onClick={() => onApply(nivel, recomendacion)}
    >
      {status === "loading" ? "Aplicando..." : "Aplicar cambio"}
    </button>
  )
}

function EvaluationCard({ evaluation, autoApply = false }) {
  const [expanded, setExpanded] = useState(null)
  const [applying, setApplying] = useState({})

  const applyRecommendation = useCallback(async (nivel, recomendacion) => {
    setApplying(prev => ({ ...prev, [nivel]: "loading" }))
    try {
      const r = await fetch(`${API}/autopilot/apply-recommendation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nivel, recomendacion }),
      })
      const data = await r.json()
      if (!r.ok || data.error) throw new Error(data.error || "Error")
      setApplying(prev => ({ ...prev, [nivel]: "ok" }))
      window.dispatchEvent(new CustomEvent("ontologia-updated", { detail: { nombre: data.nombre } }))
    } catch {
      setApplying(prev => ({ ...prev, [nivel]: "error" }))
    }
  }, [])

  // Auto-aplicar todas las recomendaciones si autoApply está activo
  useEffect(() => {
    if (!autoApply || !evaluation?.niveles) return
    const niveles = ["system_prompt", "ontologia_reglas", "ontologia_diferenciadores"]
    niveles.forEach(key => {
      const rec = evaluation.niveles[key]?.recomendacion
      if (rec) applyRecommendation(key, rec)
    })
  }, [autoApply, evaluation, applyRecommendation])

  const dec = evaluation.decision || evaluation.resultado || "indeciso"

  return (
    <div className="ec-card">
      <div className="ec-header">
        <div className={`ec-resultado ec-res-${dec}`}>
          {dec === "retenido"  && "✓ RETENIDO"}
          {dec === "cancelado" && "✗ CANCELADO"}
          {dec === "indeciso"  && "— INDECISO"}
        </div>
        <div className="ec-global-score">
          Score global <strong>{evaluation.score_global}/10</strong>
        </div>
      </div>

      {evaluation.analisis && (
        <p className="ec-analisis">{evaluation.analisis}</p>
      )}

      <div className="ec-niveles">
        {[
          { key: "system_prompt",            label: "System Prompt" },
          { key: "ontologia_reglas",          label: "Reglas de Retención" },
          { key: "ontologia_diferenciadores", label: "Diferenciadores" },
        ].map(({ key, label }) => {
          const nivel = evaluation.niveles?.[key]
          if (!nivel) return null
          const isOpen = expanded === key
          return (
            <div key={key} className={`ec-nivel${isOpen ? " open" : ""}`}>
              <div className="ec-nivel-hdr" onClick={() => setExpanded(isOpen ? null : key)}>
                <span className="ec-nivel-label">{label}</span>
                <ScoreBar score={nivel.score} />
                <span className="ec-chevron">{isOpen ? "▲" : "▼"}</span>
              </div>
              {isOpen && (
                <div className="ec-nivel-body">
                  {nivel.problemas?.length > 0 && (
                    <div className="ec-problemas">
                      <strong>Problemas detectados:</strong>
                      <ul>{nivel.problemas.map((p, i) => <li key={i}>{p}</li>)}</ul>
                    </div>
                  )}
                  {nivel.recomendacion && (
                    <div className="ec-rec">
                      <div className="ec-rec-hdr">
                        <strong>Recomendación:</strong>
                        <ApplyButton
                          nivel={key}
                          recomendacion={nivel.recomendacion}
                          status={applying[key]}
                          onApply={applyRecommendation}
                        />
                      </div>
                      <p>{nivel.recomendacion}</p>
                    </div>
                  )}
                  {!nivel.problemas?.length && !nivel.recomendacion && (
                    <p className="ec-ok">Sin observaciones.</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default EvaluationCard

// ── Modal wrapper ────────────────────────────────────────────────────────────

export function EvaluationModal({ evaluation, evaluating, autoApply = false, onClose }) {
  // Bloquear scroll del body mientras el modal está abierto
  useEffect(() => {
    document.body.style.overflow = "hidden"
    return () => { document.body.style.overflow = "" }
  }, [])

  // Cerrar con Escape
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div className="ec-overlay" onClick={onClose}>
      <div className="ec-dialog" onClick={e => e.stopPropagation()}>

        <div className="ec-dialog-header">
          <span className="ec-dialog-title">Evaluación de la conversación</span>
        </div>

        <div className="ec-dialog-body">
          {evaluating && !evaluation ? (
            <div className="ec-loading">
              <span className="ec-loading-dot" />
              <span>Evaluando conversación con GPT-4o...</span>
            </div>
          ) : evaluation ? (
            <EvaluationCard evaluation={evaluation} autoApply={autoApply} />
          ) : null}
        </div>

        <div className="ec-dialog-footer">
          <button className="ec-btn-ok" onClick={onClose} disabled={evaluating && !evaluation}>
            Aceptar
          </button>
        </div>

      </div>
    </div>
  )
}
