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
      title="Aplicar automáticamente esta recomendación: el sistema reescribirá la ontología correspondiente (prompt, reglas o diferenciadores) incorporando la mejora sugerida por el evaluador. Se crea una nueva versión, preservando la anterior por si necesitas revertir."
    >
      {status === "loading" ? "Aplicando..." : "Aplicar cambio"}
    </button>
  )
}

function EvaluationCard({ evaluation, autoApply = false, onApplyingChange }) {
  const [expanded, setExpanded] = useState(null)
  const [applying, setApplying] = useState({})

  const applyRecommendation = useCallback(async (nivel, recomendacion) => {
    setApplying(prev => { const next = { ...prev, [nivel]: "loading" }; onApplyingChange?.(Object.values(next).some(v => v === "loading")); return next })
    try {
      const r = await fetch(`${API}/autopilot/apply-recommendation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nivel, recomendacion }),
      })
      const data = await r.json()
      if (!r.ok || data.error) throw new Error(data.error || "Error")
      setApplying(prev => { const next = { ...prev, [nivel]: "ok" }; onApplyingChange?.(Object.values(next).some(v => v === "loading")); return next })
      window.dispatchEvent(new CustomEvent("ontologia-updated", { detail: { nombre: data.nombre } }))
    } catch {
      setApplying(prev => { const next = { ...prev, [nivel]: "error" }; onApplyingChange?.(Object.values(next).some(v => v === "loading")); return next })
    }
  }, [onApplyingChange])

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
  const [applying, setApplying] = useState(false)
  // Bloquear scroll del body mientras el modal está abierto
  useEffect(() => {
    document.body.style.overflow = "hidden"
    return () => { document.body.style.overflow = "" }
  }, [])

  // Cerrar con Escape solo si ya hay resultado (no mientras evalúa)
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape" && evaluation && !evaluating) onClose() }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose, evaluation, evaluating])

  return (
    <div className="ec-overlay">
      <div className="ec-dialog" onClick={e => e.stopPropagation()}>

        <div className="ec-dialog-header">
          <span className="ec-dialog-title">Evaluación de la conversación</span>
        </div>

        <div className="ec-dialog-body">
          {evaluating && !evaluation ? (
            <div className="ec-loading">
              <div className="ec-iso-stack">
                {/* Capa 3 — Diferenciadores (arriba) */}
                <div className="ec-iso-layer ec-layer-3">
                  <div className="ec-iso-plate">
                    <div className="ec-iso-nodes">
                      <div className="ec-node sm" /><div className="ec-node lg" /><div className="ec-node sm" />
                      <div className="ec-node md" /><div className="ec-node sm" /><div className="ec-node md" />
                    </div>
                  </div>
                  <div className="ec-iso-scan" />
                </div>
                {/* Capa 2 — Reglas (medio) */}
                <div className="ec-iso-layer ec-layer-2">
                  <div className="ec-iso-plate">
                    <div className="ec-iso-grid">
                      {Array.from({length: 12}).map((_, i) => <div key={i} className="ec-grid-cell" />)}
                    </div>
                  </div>
                  <div className="ec-iso-scan" />
                </div>
                {/* Capa 1 — Prompt (abajo) */}
                <div className="ec-iso-layer ec-layer-1">
                  <div className="ec-iso-plate">
                    <div className="ec-iso-lines">
                      <div className="ec-line-row" style={{width:'75%'}} />
                      <div className="ec-line-row" style={{width:'90%'}} />
                      <div className="ec-line-row" style={{width:'55%'}} />
                      <div className="ec-line-row" style={{width:'80%'}} />
                    </div>
                  </div>
                  <div className="ec-iso-scan" />
                </div>
              </div>
              <div className="ec-loading-labels">
                <span className="ec-loading-text">Analizando ontologías</span>
                <span className="ec-loading-sub">Prompt · Reglas · Diferenciadores</span>
              </div>
            </div>
          ) : evaluation ? (
            <EvaluationCard evaluation={evaluation} autoApply={autoApply} onApplyingChange={setApplying} />
          ) : null}
        </div>

        <div className="ec-dialog-footer">
          <button className="ec-btn-ok" onClick={onClose} disabled={(evaluating && !evaluation) || applying} title="Cerrar la ventana de evaluación. Si se aplicaron cambios a las ontologías, ya estarán activos para la próxima conversación. Si no aplicaste ninguna recomendación, las ontologías permanecen sin cambios.">
            {applying ? "Aplicando cambios..." : "Aceptar"}
          </button>
        </div>

      </div>
    </div>
  )
}
