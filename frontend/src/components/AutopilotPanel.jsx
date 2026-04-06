import { useState, useEffect, useRef } from "react"
import ReactMarkdown from "react-markdown"
import { EvaluationModal } from "./EvaluationCard"
import RadarChart from "./RadarChart"
import RetentionGauge from "./RetentionGauge"
import SentimentLine from "./SentimentLine"
import "./AutopilotPanel.css"

const API = import.meta.env.VITE_API_URL || "/api"

const TOOL_LABELS = {
  buscar_poliza:             "Buscando póliza...",
  ontologia_reglas:          "Validando reglas...",
  ontologia_diferenciadores: "Analizando diferenciadores...",
  analizar_documento:        "Analizando documento...",
}

function formatAssistantMsg(text) {
  return text.replace(/[""\u00ab]([^""\u00bb]{30,})[""\u00bb]/g, (_, quoted) => {
    return '\n\n> 💬 *' + quoted.trim() + '*\n\n'
  })
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
  const [showOptPrompt, setShowOptPrompt] = useState(false)
  const [riskProfile, setRiskProfile]     = useState(null)
  const [retention, setRetention]         = useState(null)
  const [sentimentPts, setSentimentPts]   = useState([])
  const convDataRef = useRef(null)

  const abortRef   = useRef(null)
  const bottomRef  = useRef(null)

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
    setRiskProfile(null)
    setRetention(null)
    setSentimentPts([])

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

            case "risk_profile":
              setRiskProfile(ev.data)
              if (ev.data.retencion != null) setRetention(ev.data.retencion)
              if (ev.data.sentimiento != null) setSentimentPts(prev => [...prev, ev.data.sentimiento])
              break

            case "done_conversation":
              convDataRef.current = {
                transcripcion: ev.transcripcion,
                decision: ev.decision,
              }
              setShowOptPrompt(true)
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

  async function handleOptimize() {
    setShowOptPrompt(false)
    const data = convDataRef.current
    if (!data || !caso) return
    setEvaluating(true)
    try {
      const r = await fetch(`${API}/autopilot/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcripcion: data.transcripcion,
          caso,
          decision: data.decision,
        }),
      })
      const ev = await r.json()
      if (ev.error) throw new Error(ev.error)
      setEvaluation(ev)
    } catch (e) {
      console.error("[autopilot evaluate]", e)
      setEvaluation({ error: e.message, score_global: 0, analisis: "Error al evaluar.", niveles: {} })
    } finally {
      setEvaluating(false)
    }
  }

  function handleSkipOptimize() {
    setShowOptPrompt(false)
    convDataRef.current = null
    // Reset todo para nuevo caso
    setCaso(null)
    setTurns([])
    setAgentBuf("")
    setEvaluation(null)
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const hasStarted = caso !== null

  return (
    <div className="autopilot-panel">

      {/* ── Config (arriba, siempre visible) ── */}
      <div className="ap-config">
        <div className="ap-config-row">
          <div className="ap-field-inline">
            <label>Póliza</label>
            <select value={poliza} onChange={e => setPoliza(e.target.value)} disabled={running} title="Selecciona una póliza concreta de la base de datos para la simulación, o deja en 'Aleatoria' para que el sistema elija una al azar. La póliza determina el perfil del cliente (ramo, antigüedad, rentabilidad, siniestralidad) que el asistente SR usará para adaptar su estrategia de retención según las ontologías.">
              <option value="">Aleatoria</option>
              {opciones.polizas.map(p => (
                <option key={p.numero_poliza} value={p.numero_poliza}>
                  {p.numero_poliza} — {p.ramo} ({p.rentabilidad})
                </option>
              ))}
            </select>
          </div>
          <div className="ap-field-inline">
            <label>Motivo</label>
            <select value={motivo} onChange={e => setMotivo(e.target.value)} disabled={running} title="Motivo de cancelación que el cliente simulado planteará al asistente. Permite probar cómo las ontologías manejan distintos escenarios: precio alto, mala experiencia, competencia, falta de uso, situación económica, etc. Dejar en 'Aleatorio' genera variedad en las pruebas.">
              <option value="">Aleatorio</option>
              {opciones.motivos.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div className="ap-field-inline">
            <label>Persona</label>
            <select value={personalidad} onChange={e => setPersona(e.target.value)} disabled={running} title="Personalidad del cliente IA que participa en la simulación. Cada perfil (agresivo, indeciso, racional, emocional, etc.) pone a prueba diferentes aspectos de las ontologías: manejo de objeciones, empatía, argumentación técnica y estrategias de retención.">
              <option value="">Aleatoria</option>
              {opciones.personalidades.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="ap-field ap-field-action">
            {!running ? (
              <button className="ap-btn-launch" onClick={launchManual} title="Lanzar la simulación completa: un cliente IA conversará con el asistente SR usando las ontologías activas. Al finalizar, el evaluador analizará la conversación en tres niveles y propondrá mejoras a las ontologías que podrás aplicar automáticamente.">
                Iniciar
              </button>
            ) : (
              <button className="ap-btn-stop" onClick={handleStop} title="Detener la simulación en curso. La conversación generada hasta este punto se conserva pero no se evaluará automáticamente. Útil si detectas un problema evidente en las ontologías y quieres corregirlo antes de gastar otra ejecución.">
                Detener
              </button>
            )}
          </div>
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

      {/* ── Cuerpo principal ── */}
      {hasStarted && (
      <div className="ap-body">

      {/* ── Transcripción ── */}
        <div className="ap-transcript">
          <div className="ap-transcript-inner">
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
                  ? <ReactMarkdown>{formatAssistantMsg(t.content)}</ReactMarkdown>
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
              <span>Evaluando las respuestas para poder optimizar...</span>
            </div>
          )}

          <div ref={bottomRef} />
          </div>
        </div>

        {/* ── Panel derecho: Radar ── */}
        <div className="ap-radar-panel">
          <RadarChart data={riskProfile} />
          <RetentionGauge value={retention} />
          <SentimentLine points={sentimentPts} />
        </div>

      </div>
      )}

      {/* ── Prompt optimizador ── */}
      {showOptPrompt && (
        <div className="ap-opt-overlay">
          <div className="ap-opt-dialog">
            <div className="ap-opt-icon">&#9881;</div>
            <h3>Conversación finalizada</h3>
            <p>¿Deseas ejecutar el agente optimizador para analizar la conversación y sugerir mejoras a la ontología?</p>
            <div className="ap-opt-actions">
              <button className="ap-opt-yes" onClick={handleOptimize} title="Ejecutar el agente optimizador: analizará los problemas detectados por el evaluador y reescribirá las secciones débiles de las ontologías (prompt, reglas o diferenciadores) para mejorar las respuestas del asistente en futuras conversaciones.">Sí, optimizar</button>
              <button className="ap-opt-no" onClick={handleSkipOptimize} title="Omitir la optimización automática y pasar directamente a un nuevo caso de prueba. Útil si la evaluación fue satisfactoria o si prefieres ajustar las ontologías manualmente desde el panel de administración.">No, nuevo caso</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal de evaluación ── */}
      {(evaluating || evaluation) && (
        <EvaluationModal
          evaluation={evaluation}
          evaluating={evaluating}
          onClose={() => {
            setEvaluation(null)
            setEvaluating(false)
            convDataRef.current = null
            setCaso(null)
            setTurns([])
            setAgentBuf("")
          }}
        />
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
