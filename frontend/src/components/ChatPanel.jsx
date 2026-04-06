import { useState, useEffect, useRef } from "react"
import ReactMarkdown from "react-markdown"
import { EvaluationModal } from "./EvaluationCard"
import RadarChart from "./RadarChart"
import RetentionGauge from "./RetentionGauge"
import SentimentLine from "./SentimentLine"
import "./ChatPanel.css"

const API = import.meta.env.VITE_API_URL || "/api"

const ACCEPTED = ".pdf,.jpg,.jpeg,.png,.webp"


export default function ChatPanel({ onLoadingChange, onNewCase, showEval = false }) {
  const [sessionId, setSessionId]   = useState(null)
  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState("")
  const [loading, setLoading]       = useState(false)
  const [poliza, setPoliza]           = useState(null)
  const [attachedFile, setAttachedFile] = useState(null)
  const [isStreaming, setIsStreaming]   = useState(false)
  const [suggestions, setSuggestions]   = useState([])
  const [agentStatus, setAgentStatus]   = useState("")
  const [evaluating, setEvaluating]     = useState(false)
  const [evaluation, setEvaluation]     = useState(null)
  const [ended, setEnded]               = useState(false)
  const [showOptPrompt, setShowOptPrompt] = useState(false)
  const [riskProfile, setRiskProfile]     = useState(null)
  const [retention, setRetention]         = useState(null)
  const [sentimentPts, setSentimentPts]   = useState([])
  const [showPolizaPicker, setShowPolizaPicker] = useState(false)
  const [polizaList, setPolizaList]       = useState([])
  const bottomRef    = useRef(null)
  const textareaRef  = useRef(null)
  const abortRef     = useRef(null)
  const fileInputRef = useRef(null)
  const genRef       = useRef(0)
  const messagesRef  = useRef([])
  const polizaRef    = useRef(null)

  async function streamChat(message, sessionId, controller, onToken, onStatus, onPoliza, onSuggestions, onCierre, onRiskProfile) {
    const res = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue
        const data = line.slice(6)
        if (data === "[DONE]") return
        try {
          const parsed = JSON.parse(data)
          if (parsed.error) throw new Error(parsed.error)
          if (parsed.status) onStatus?.(parsed.status)
          if (parsed.poliza) onPoliza?.(parsed.poliza)
          if (parsed.suggestions) onSuggestions?.(parsed.suggestions)
          if (parsed.risk_profile) onRiskProfile?.(parsed.risk_profile)
          if (parsed.cierre) onCierre?.()
          if (parsed.token) { onStatus?.(""); onToken(parsed.token) }
        } catch (e) {
          if (e.message !== "SyntaxError") throw e
        }
      }
    }
  }

  async function evaluateChat(currentMessages, currentPoliza) {
    setEvaluating(true)
    setEvaluation(null)
    try {
      const r = await fetch(`${API}/chat/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: currentMessages, poliza: currentPoliza }),
      })
      const data = await r.json()
      if (data.error) throw new Error(data.error)
      setEvaluation(data)
    } catch (e) {
      console.error("[evaluate]", e)
    } finally {
      setEvaluating(false)
    }
  }

  function handleFin() {
    abortRef.current?.abort()
    setEnded(true)
    setShowOptPrompt(true)
  }

  function handleOptimize() {
    setShowOptPrompt(false)
    evaluateChat(messagesRef.current, polizaRef.current)
  }

  function handleSkipOptimize() {
    setShowOptPrompt(false)
    onNewCase?.()
  }

  function handleModalClose() {
    onNewCase?.()                     // resetea ChatPanel via key change en App
  }

  useEffect(() => {
    async function init() {
      const r = await fetch(`${API}/session/new`, { method: "POST" })
      const { session_id } = await r.json()
      setSessionId(session_id)
      setMessages([{
        role: "assistant",
        content: "¡Hola! Soy el asistente de retención. Indícame el número de póliza del cliente para comenzar."
      }])
      // Cargar pólizas y mostrar picker
      try {
        const op = await fetch(`${API}/autopilot/opciones`)
        const data = await op.json()
        if (data.polizas?.length) {
          setPolizaList(data.polizas)
          setShowPolizaPicker(true)
        }
      } catch {}
    }
    init()
  }, [])

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    polizaRef.current = poliza
  }, [poliza])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  useEffect(() => {
    if (!loading) textareaRef.current?.focus()
  }, [loading])

  async function sendMessage() {
    const text = input.trim()
    if ((!text && !attachedFile) || !sessionId) return

    // Abort any in-progress stream and claim this generation
    abortRef.current?.abort()
    const myGen = ++genRef.current

    const fileToSend = attachedFile
    setInput("")
    setAttachedFile(null)
    setSuggestions([])
    setEvaluation(null)
    if (fileInputRef.current) fileInputRef.current.value = ""

    const displayText = fileToSend
      ? (text ? `📎 ${fileToSend.name}\n\n${text}` : `📎 ${fileToSend.name}`)
      : text
    setMessages(prev => [...prev, { role: "user", content: displayText }])
    setLoading(true); onLoadingChange?.(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      let finalMessage = text

      // Si hay archivo adjunto, subirlo primero
      if (fileToSend) {
        const formData = new FormData()
        formData.append("file", fileToSend.file)
        const uploadRes = await fetch(`${API}/upload`, {
          method: "POST",
          body: formData,
          signal: controller.signal,
        })
        const uploadData = await uploadRes.json()
        if (uploadData.error) throw new Error(uploadData.error)

        const docContext = `[Documento adjunto analizado: ${fileToSend.name}]\n\n${uploadData.contenido}`
        finalMessage = text ? `${docContext}\n\n${text}` : docContext
      }

      let accumulated = ""
      let started = false

      await streamChat(finalMessage, sessionId, controller, (token) => {
        accumulated += token
        if (!started) {
          started = true
          setIsStreaming(true)
          setMessages(prev => [...prev, { role: "assistant", content: accumulated }])
        } else {
          setMessages(prev => {
            const msgs = [...prev]
            msgs[msgs.length - 1] = { role: "assistant", content: accumulated }
            return msgs
          })
        }
      }, setAgentStatus, setPoliza, (s) => setSuggestions(s), undefined, (profile) => {
        setRiskProfile(profile)
        if (profile.retencion != null) setRetention(profile.retencion)
        if (profile.sentimiento != null) setSentimentPts(prev => [...prev, profile.sentimiento])
      })
    } catch (e) {
      if (e.name !== "AbortError")
        setMessages(prev => [...prev, { role: "assistant", content: `⚠️ Error: ${e.message}` }])
    } finally {
      // Only reset loading state if no newer message has taken over
      if (genRef.current === myGen) {
        setLoading(false); onLoadingChange?.(false)
        setIsStreaming(false)
        setAgentStatus("")
        abortRef.current = null
      }
    }
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function handleInput(e) {
    setInput(e.target.value)
    const el = textareaRef.current
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 200) + "px"
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) setAttachedFile({ file, name: file.name })
  }

  function removeAttachment() {
    setAttachedFile(null)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  function formatAssistantMsg(text) {
    // 1. Texto entre comillas (españolas o rectas) largas → blockquote
    let result = text.replace(/[""\u00ab]([^""\u00bb]{30,})[""\u00bb]/g, (_, quoted) => {
      return '\n\n> 💬 *' + quoted.trim() + '*\n\n'
    })
    return result
  }

  return (
    <div className="chat-panel-wrap">
      {/* Barra de contexto — siempre visible, ancho completo */}
      <div className="session-bar">
        {poliza ? (<>
          <span className="session-item">
            <span className="session-label">Póliza</span>
            <span className="session-value">{poliza.numero}</span>
          </span>
          {poliza.cliente && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">Cliente</span>
              <span className="session-value">{poliza.cliente}</span>
            </span>
          </>)}
          <span className="session-sep">·</span>
          <span className="session-item">
            <span className="session-label">Ramo</span>
            <span className="session-value">{poliza.ramo}</span>
          </span>
          {poliza.edad && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">Edad</span>
              <span className="session-value">{poliza.edad} años</span>
            </span>
          </>)}
          {poliza.cp && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">CP</span>
              <span className="session-value">{poliza.cp}</span>
            </span>
          </>)}
          <span className="session-sep">·</span>
          <span className="session-item">
            <span className="session-label">Antigüedad</span>
            <span className="session-value">{poliza.antiguedad}</span>
          </span>
          <span className="session-sep">·</span>
          <span className="session-item">
            <span className="session-label">Rentabilidad</span>
            <span className={`session-badge rentabilidad-${poliza.rentabilidad?.toLowerCase()}`}>
              {poliza.rentabilidad}
            </span>
          </span>
          {poliza.siniestralidad && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">Siniestralidad</span>
              <span className={`session-badge siniestralidad-${poliza.siniestralidad?.toLowerCase()}`}>
                {poliza.siniestralidad}
              </span>
            </span>
          </>)}
          {poliza.canal_mediador && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">Canal</span>
              <span className="session-value">{poliza.canal_mediador}</span>
            </span>
          </>)}
          {poliza.reincidencia > 0 && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">Reincidencia</span>
              <span className="session-value">{poliza.reincidencia}×</span>
            </span>
          </>)}
          {poliza.vinculacion && (<>
            <span className="session-sep">·</span>
            <span className="session-item">
              <span className="session-label">Vinculación</span>
              <span className={`session-badge vinculacion-${poliza.vinculacion?.toLowerCase()}`}>
                {poliza.vinculacion}
              </span>
            </span>
          </>)}
        </>) : (
          <span className="session-empty">Sin póliza cargada</span>
        )}
      </div>

      <div className="chat-panel">
      <div className="chat-main">
      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message-row ${msg.role}`}>
            {msg.role === "assistant" && <div className="avatar">SR</div>}
            <div className="bubble">
              {msg.role === "assistant"
                ? <ReactMarkdown>{formatAssistantMsg(msg.content)}</ReactMarkdown>
                : <span>{msg.content}</span>
              }
            </div>
          </div>
        ))}
        {loading && !isStreaming && (
          <div className="agent-status-row">
            <span className="pulse-dot" />
            <span className="status-label">
              {agentStatus || "Pensando"}
              <span className="ellipsis-anim" />
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Popup selector de póliza ── */}
      {showPolizaPicker && (
        <div className="poliza-picker-overlay" onClick={() => setShowPolizaPicker(false)}>
          <div className="poliza-picker" onClick={e => e.stopPropagation()}>
            <div className="poliza-picker-header">
              <span className="poliza-picker-title">Seleccionar póliza</span>
              <button className="poliza-picker-close" onClick={() => setShowPolizaPicker(false)} title="Cerrar el selector de pólizas. También puedes escribir el número directamente en el chat si lo conoces.">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
            <div className="poliza-picker-table-wrap">
              <table className="poliza-picker-table">
                <thead>
                  <tr>
                    <th>Póliza</th>
                    <th>Cliente</th>
                    <th>Ramo</th>
                    <th>Rentabilidad</th>
                  </tr>
                </thead>
                <tbody>
                  {polizaList.map(p => (
                    <tr key={p.numero_poliza} onClick={() => {
                      setInput(p.numero_poliza)
                      setShowPolizaPicker(false)
                      textareaRef.current?.focus()
                    }}>
                      <td className="pp-numero">{p.numero_poliza}</td>
                      <td>{p.cliente || "—"}</td>
                      <td>{p.ramo}</td>
                      <td><span className={`pp-badge rent-${p.rentabilidad?.toLowerCase()}`}>{p.rentabilidad}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal de evaluación (solo en modo ontologista) ── */}
      {showEval && (evaluating || evaluation) && (
        <EvaluationModal
          evaluation={evaluation}
          evaluating={evaluating}
          onClose={handleModalClose}
        />
      )}

      <div className="input-area">
        {suggestions.length > 0 && !loading && (
          <div className="suggestions">
            {suggestions.map((s, i) => (
              <button
                key={i}
                className="suggestion-btn"
                onClick={() => {
                  setInput(s)
                  setSuggestions([])
                  textareaRef.current?.focus()
                }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {attachedFile && (
          <div className="file-preview">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style={{flexShrink:0}}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z"/>
            </svg>
            <span className="file-name">{attachedFile.name}</span>
            <button className="file-remove" onClick={removeAttachment} title="Quitar el archivo adjunto antes de enviarlo. El asistente SR puede analizar documentos PDF e imágenes para enriquecer su respuesta con datos concretos del cliente.">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        )}
        <div className="input-row">
          <div className="input-box">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED}
              style={{ display: "none" }}
              onChange={handleFileChange}
            />
            <button
              className="attach-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={!sessionId}
              title="Adjuntar un archivo PDF o imagen a tu mensaje. El asistente SR puede leer documentos del cliente (pólizas, cartas, recibos) para personalizar sus argumentos de retención según las ontologías activas."
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
              </svg>
            </button>
            <textarea
              ref={textareaRef}
              className="chat-input"
              placeholder={ended ? "Conversación finalizada" : "Escribe un mensaje..."}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={!sessionId || ended}
            />
            {!ended && (loading ? (
              <button className="stop-btn" onClick={handleStop} title="Detener la respuesta del asistente SR en curso. Útil si detectas que la ontología está generando una respuesta incorrecta o demasiado larga y quieres redirigir la conversación.">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="3" y="3" width="18" height="18" rx="2"/>
                </svg>
              </button>
            ) : (
              <button
                className="send-btn"
                onClick={sendMessage}
                disabled={(!input.trim() && !attachedFile) || !sessionId}
                title="Enviar tu mensaje al asistente SR (también puedes pulsar Enter). El asistente responderá aplicando las ontologías activas: el system prompt define su personalidad, las reglas de retención guían su estrategia y los diferenciadores le aportan argumentos competitivos."
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                </svg>
              </button>
            ))}
          </div>
          {showEval && (
            <button
              className="eval-btn"
              title="Finalizar la conversación y lanzar la evaluación automática. Un agente evaluador analizará toda la conversación en tres niveles — system prompt, reglas de retención y diferenciadores — puntuando cada ontología del 1 al 10 y proponiendo mejoras concretas que puedes aplicar con un clic."
              disabled={messages.length < 2 || loading || evaluating || ended}
              onClick={handleFin}
            >
              Fin
            </button>
          )}
        </div>
        <p className="disclaimer">Desarrollado por Braintrust CS firma miembro de Andersen Consulting</p>
      </div>

      </div>{/* close chat-main */}

      {/* ── Radar de riesgo (solo en modo test) ── */}
      {showEval && (
        <div className="chat-radar-sidebar">
          <RadarChart data={riskProfile} />
          <RetentionGauge value={retention} />
          <SentimentLine points={sentimentPts} />
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
              <button className="ap-opt-yes" onClick={handleOptimize}>Sí, optimizar</button>
              <button className="ap-opt-no" onClick={handleSkipOptimize}>No, nuevo caso</button>
            </div>
          </div>
        </div>
      )}
    </div>{/* close chat-panel */}
    </div>
  )
}
