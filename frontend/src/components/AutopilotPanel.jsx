import { useState, useEffect, useRef } from "react"
import ReactMarkdown from "react-markdown"
import "./AutopilotPanel.css"

const API = import.meta.env.VITE_API_URL || "/api"

const TOOL_LABELS = {
  buscar_poliza:             "Buscando póliza...",
  ontologia_reglas:          "Validando reglas...",
  ontologia_diferenciadores: "Analizando diferenciadores...",
  analizar_documento:        "Analizando documento...",
}

function ScoreBar({ score }) {
  const pct = (score / 10) * 100
  const color = score >= 8 ? "#22c55e" : score >= 6 ? "#f59e0b" : "#ef4444"
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="score-num" style={{ color }}>{score}/10</span>
    </div>
  )
}

function RoleAvatar({ role }) {
  if (role === "asistente") return <div className="ap-avatar agent">SR</div>
  if (role === "cliente")   return <div className="ap-avatar client">CL</div>
  return null
}

export default function AutopilotPanel({ onLoadingChange }) {
  // Opciones del formulario
  const [opciones, setOpciones]     = useState({ polizas: [], motivos: [], personalidades: [] })
  const [poliza, setPoliza]         = useState("")
  const [motivo, setMotivo]         = useState("")
  const [personalidad, setPersona]  = useState("")


  // Estado de la sesión activa
  const [caso, setCaso]             = useState(null)
  const [running, setRunning]       = useState(false)
  const [turns, setTurns]           = useState([])
  const [agentBuffer, setAgentBuf]  = useState("")
  const [toolStatus, setToolStatus] = useState("")
  const [evaluating, setEvaluating] = useState(false)
  const [evaluation, setEvaluation] = useState(null)
  const [expandedRec, setExpanded]  = useState(null)
  const [traceEvents, setTrace]     = useState([])     // eventos internos del agente

  const abortRef   = useRef(null)
  const bottomRef  = useRef(null)
  const traceRef   = useRef(null)

  // Cargar opciones al montar
  useEffect(() => {
    fetch(`${API}/autopilot/opciones`)
      .then(r => r.json())
      .then(setOpciones)
      .catch(console.error)
  }, [])

  // Scroll automático
  useEffect(() => {
    if (evaluation) bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [evaluation])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [turns, agentBuffer, evaluating])


  function launchRandom() { launch("random") }
  function launchManual()  { launch("manual") }

  async function launch(mode) {
    // Abortar stream anterior si existe
    abortRef.current?.abort()
    abortRef.current = null

    setTurns([])
    setAgentBuf("")
    setEvaluation(null)
    setToolStatus("")
    setEvaluating(false)
    setCaso(null)
    setTrace([])

    const body = mode === "random" ? {} : {
      numero_poliza: poliza || undefined,
      motivo:        motivo || undefined,
      personalidad:  personalidad || undefined,
    }

    let casoData
    try {
      const r = await fetch(`${API}/autopilot/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      casoData = await r.json()
      if (casoData.error) { alert(casoData.error); return }
    } catch (e) {
      alert("Error al iniciar: " + e.message)
      return
    }

    setCaso(casoData)
    setRunning(true)
    onLoadingChange?.(true)

    const params = new URLSearchParams({
      numero_poliza: casoData.numero_poliza,
      ramo:          casoData.ramo,
      rentabilidad:  casoData.rentabilidad,
      cliente:       casoData.cliente,
      motivo:        casoData.motivo,
      personalidad:  casoData.personalidad,
    })

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch(`${API}/autopilot/run/${casoData.session_id}?${params}`, {
        signal: controller.signal,
      })

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer    = ""
      let agentAcc  = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const raw = line.slice(6)
          if (raw === "[DONE]") break

          let ev
          try { ev = JSON.parse(raw) } catch { continue }

          switch (ev.type) {
            case "turn":
              // flush buffer si lo hay — capturar valor antes del reset
              if (agentAcc) {
                const flushContent = agentAcc
                setTurns(prev => {
                  const copy = [...prev]
                  const last = copy[copy.length - 1]
                  if (last?.role === "asistente") copy[copy.length - 1] = { role: "asistente", content: flushContent }
                  return copy
                })
                agentAcc = ""
                setAgentBuf("")
              }
              setToolStatus("")
              setTurns(prev => [...prev, { role: ev.role, content: ev.content }])
              break

            case "tool":
              setToolStatus(TOOL_LABELS[ev.name] || "Procesando...")
              break

            case "agent_token":
              agentAcc += ev.token
              // Capturar valor antes de que React ejecute el callback de forma diferida
              const snapshot = agentAcc
              setAgentBuf(snapshot)
              setTurns(prev => {
                const last = prev[prev.length - 1]
                if (last?.role === "asistente" && last._streaming) {
                  const copy = [...prev]
                  copy[copy.length - 1] = { ...last, content: snapshot }
                  return copy
                }
                return [...prev, { role: "asistente", content: snapshot, _streaming: true }]
              })
              break

            case "agent_end":
              // Capturar valor antes de resetear
              const finalContent = agentAcc
              setTurns(prev => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last?.role === "asistente") copy[copy.length - 1] = { role: "asistente", content: finalContent }
                return copy
              })
              agentAcc = ""
              setAgentBuf("")
              setToolStatus("")
              break

            case "evaluating":
              setEvaluating(true)
              break

            case "evaluation":
              setEvaluating(false)
              console.log("[evaluation]", JSON.stringify(ev.data))
              setEvaluation(ev.data)
              break

            case "trace":
              console.log("[trace]", ev.event, "ts:", ev.ts)
              setTrace(prev => {
                const last = prev[prev.length - 1]
                const delta = (last?.ts != null && ev.ts != null) ? ev.ts - last.ts : null
                return [...prev, { ...ev, delta }]
              })
              break

            case "error":
              setTurns(prev => [...prev, { role: "error", content: ev.message }])
              break
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setTurns(prev => [...prev, { role: "error", content: e.message }])
      }
    } finally {
      setRunning(false)
      onLoadingChange?.(false)
      abortRef.current = null
    }
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const hasStarted = caso !== null

  return (
    <div className="autopilot-panel">

      {/* ── Config (arriba, siempre visible) ── */}
      <div className="ap-config">
        <div className="ap-config-title">Configuración del caso</div>
        <div className="ap-config-fields">
          <div className="ap-field">
            <label>Póliza</label>
            <select value={poliza} onChange={e => setPoliza(e.target.value)} disabled={running}>
              <option value="">Aleatoria</option>
              {opciones.polizas.map(p => (
                <option key={p.numero_poliza} value={p.numero_poliza}>
                  {p.numero_poliza} — {p.ramo} ({p.rentabilidad})
                </option>
              ))}
            </select>
          </div>
          <div className="ap-field">
            <label>Motivo de cancelación</label>
            <select value={motivo} onChange={e => setMotivo(e.target.value)} disabled={running}>
              <option value="">Aleatorio</option>
              {opciones.motivos.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div className="ap-field">
            <label>Personalidad del cliente</label>
            <select value={personalidad} onChange={e => setPersona(e.target.value)} disabled={running}>
              <option value="">Aleatoria</option>
              {opciones.personalidades.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        </div>

        <div className="ap-actions">
          {!running ? (
            <>
              <button className="ap-btn-launch" onClick={launchManual}>
                Lanzar
              </button>
            </>
          ) : (
            <button className="ap-btn-stop" onClick={handleStop}>
              Detener
            </button>
          )}
        </div>
      </div>

      {/* ── Caso activo ── */}
      {caso && (
        <div className="ap-case-bar">
          <span className="ap-case-item"><b>Póliza:</b> {caso.numero_poliza}</span>
          <span className="ap-sep">·</span>
          <span className="ap-case-item"><b>Cliente:</b> {caso.cliente}</span>
          <span className="ap-sep">·</span>
          <span className="ap-case-item"><b>Ramo:</b> {caso.ramo}</span>
          <span className="ap-sep">·</span>
          <span className={`ap-badge rent-${caso.rentabilidad?.toLowerCase()}`}>{caso.rentabilidad}</span>
          <span className="ap-sep">·</span>
          <span className="ap-case-item ap-motivo">{caso.motivo}</span>
        </div>
      )}

      {/* ── Cuerpo principal: transcript + trace ── */}
      {hasStarted && (
      <div className="ap-body">

      {/* ── Transcripción ── */}
        <div className="ap-transcript">
          {turns.map((t, i) => (
            <div key={i} className={`ap-turn ap-turn-${t.role}`}>
              {t.role === "ejecutivo" && (
                <div className="ap-turn-header">
                  <span className="ap-role-label exec">Ejecutivo → Agente</span>
                </div>
              )}
              {t.role === "cliente" && (
                <div className="ap-turn-header">
                  <RoleAvatar role="cliente" />
                  <span className="ap-role-label client">Cliente</span>
                </div>
              )}
              {t.role === "asistente" && (
                <div className="ap-turn-header">
                  <RoleAvatar role="asistente" />
                  <span className="ap-role-label agent">Asistente SR</span>
                </div>
              )}
              {t.role === "error" && (
                <div className="ap-turn-header">
                  <span className="ap-role-label error">Error</span>
                </div>
              )}
              <div className="ap-turn-body">
                {t.role === "asistente"
                  ? <ReactMarkdown>{t.content}</ReactMarkdown>
                  : <span>{t.content}</span>
                }
              </div>
            </div>
          ))}

          {/* Status mientras el agente trabaja */}
          {running && toolStatus && (
            <div className="ap-status-row">
              <span className="pulse-dot" />
              <span>{toolStatus}</span>
            </div>
          )}
          {running && !toolStatus && agentBuffer === "" && (
            <div className="ap-status-row">
              <span className="pulse-dot" />
              <span>Pensando...</span>
            </div>
          )}

          {evaluating && (
            <div className="ap-status-row evaluating">
              <span className="pulse-dot" />
              <span>Evaluando conversación con GPT-4o...</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* ── Panel de Trace (columna derecha fija) ── */}
        <div className="ap-trace" ref={traceRef}>
          <div className="ap-trace-title">Traza del agente SR</div>
          <div className="ap-trace-legend">
            <span><span className="ap-trace-dot dot-think" />Razonando</span>
            <span><span className="ap-trace-dot dot-tool" />Tool call</span>
            <span><span className="ap-trace-dot dot-result" />Resultado</span>
            <span><span className="ap-trace-dot dot-response" />Respuesta</span>
          </div>
          {traceEvents.length === 0 && running && (
            <div className="ap-trace-empty">Esperando eventos...</div>
          )}
          {[...traceEvents].filter(ev => {
              if (ev.event === "tool_call" && !ev.tool) return false
              if (ev.event === "tool_result" && !ev.tool) return false
              return true
            }).reverse().map((ev, i, arr) => {
            const isLast = i === arr.length - 1
            let dotClass = "", label = "", sub = ""
            if (ev.event === "thinking") {
              dotClass = "dot-think"; label = "Razonando"
            } else if (ev.event === "tool_call") {
              dotClass = "dot-tool"; label = ev.tool
              sub = ev.args && Object.keys(ev.args).length > 0
                ? Object.values(ev.args).join(", ") : ""
            } else if (ev.event === "tool_result") {
              dotClass = "dot-result"; label = `↳ ${ev.tool}`
              sub = ev.preview
            } else if (ev.event === "agent_response") {
              dotClass = "dot-response"; label = "Respuesta SR"
              sub = `${ev.chars} chars`
            }
            return (
              <div key={i} className={`ap-trace-row${isLast ? " ap-trace-last" : ""}`}>
                <div className="ap-trace-graph">
                  <div className={`ap-trace-dot ${dotClass}`} />
                </div>
                <span className="ap-trace-turno-tag">{ev.turno}</span>
                {ev.delta != null && <span className="ap-trace-delta">+{ev.delta}ms</span>}
                <span className="ap-trace-main">{label}</span>
                {sub && <span className="ap-trace-sub">{sub}</span>}
              </div>
            )})}
        </div>

      </div>
      )}

      {/* ── Evaluación — banda fija debajo del body ── */}
      {hasStarted && (evaluating || evaluation) && (
        <div className="ap-eval-section">
          {evaluating && !evaluation && (
            <div className="ap-status-row evaluating" style={{padding: "12px 20px"}}>
              <span className="pulse-dot" />
              <span>Evaluando conversación con GPT-4o...</span>
            </div>
          )}
          {evaluation && (() => {
            const dec = evaluation.decision || evaluation.resultado || "indeciso"
            return (
              <div className="ap-evaluation">
                <div className="ap-eval-header">
                  <div className={`ap-resultado res-${dec}`}>
                    {dec === "retenido"  && "✓ RETENIDO"}
                    {dec === "cancelado" && "✗ CANCELADO"}
                    {dec === "indeciso"  && "— INDECISO"}
                  </div>
                  <div className="ap-global-score">
                    Score global <strong>{evaluation.score_global}/10</strong>
                  </div>
                </div>
                {evaluation.analisis && (
                  <p className="ap-analisis">{evaluation.analisis}</p>
                )}
                <div className="ap-niveles">
                  {[
                    { key: "system_prompt",            label: "System Prompt" },
                    { key: "ontologia_reglas",          label: "Reglas de Retención" },
                    { key: "ontologia_diferenciadores", label: "Diferenciadores" },
                  ].map(({ key, label }) => {
                    const nivel = evaluation.niveles?.[key]
                    if (!nivel) return null
                    const isOpen = expandedRec === key
                    return (
                      <div key={key} className={`ap-nivel ${isOpen ? "open" : ""}`}>
                        <div className="ap-nivel-header" onClick={() => setExpanded(isOpen ? null : key)}>
                          <span className="ap-nivel-label">{label}</span>
                          <ScoreBar score={nivel.score} />
                          <span className="ap-nivel-chevron">{isOpen ? "▲" : "▼"}</span>
                        </div>
                        {isOpen && (
                          <div className="ap-nivel-detail">
                            {nivel.problemas?.length > 0 && (
                              <div className="ap-problemas">
                                <strong>Problemas detectados:</strong>
                                <ul>{nivel.problemas.map((p, i) => <li key={i}>{p}</li>)}</ul>
                              </div>
                            )}
                            {nivel.recomendacion && (
                              <div className="ap-recomendacion">
                                <strong>Recomendación:</strong>
                                <p>{nivel.recomendacion}</p>
                              </div>
                            )}
                            {!nivel.problemas?.length && !nivel.recomendacion && (
                              <p className="ap-ok">Sin observaciones.</p>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })()}
        </div>
      )}

      {!hasStarted && (
        <div className="ap-empty">
          <div className="ap-empty-icon">⚡</div>
          <p>Configura el caso y presiona <strong>Iniciar</strong> para lanzar una prueba automática.</p>
          <p className="ap-empty-sub">Dejá campos en blanco para generarlos aleatoriamente.</p>
        </div>
      )}
    </div>
  )
}
