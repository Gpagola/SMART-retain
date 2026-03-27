import { useState, useEffect, useRef } from "react"
import ReactMarkdown from "react-markdown"
import "./ChatPanel.css"

const API = "http://localhost:5001/api"

const ACCEPTED = ".pdf,.jpg,.jpeg,.png,.webp"

// Extrae datos de póliza — el número lo toma del mensaje del usuario
function extractPoliza(responseText, userText) {
  const clean = responseText.replace(/\*\*/g, "").replace(/\*/g, "")
  const ramo         = clean.match(/Ramo[:\s]+([^\n\-–]+)/i)?.[1]?.trim()
  const rentabilidad = clean.match(/Rentabilidad[:\s]+([^\n\-–]+)/i)?.[1]?.trim()
  if (!ramo || !rentabilidad) return null

  // Número de póliza viene del mensaje del usuario
  const numero = userText?.match(/([A-Z]{2,}-\d+)/i)?.[1]?.toUpperCase()
              || userText?.trim().toUpperCase()

  const antiguedad = clean.match(/Antig[uü]edad[:\s]+([^\n\-–]+)/i)?.[1]?.trim()
  return { numero, ramo, antiguedad, rentabilidad }
}

export default function ChatPanel() {
  const [sessionId, setSessionId]   = useState(null)
  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState("")
  const [loading, setLoading]       = useState(false)
  const [poliza, setPoliza]           = useState(null)
  const [attachedFile, setAttachedFile] = useState(null)
  const [isStreaming, setIsStreaming]   = useState(false)
  const [suggestions, setSuggestions]   = useState([])
  const bottomRef  = useRef(null)
  const textareaRef = useRef(null)
  const abortRef   = useRef(null)
  const fileInputRef = useRef(null)

  async function streamChat(message, sessionId, controller, onToken) {
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
          if (parsed.token) onToken(parsed.token)
          if (parsed.suggestions) setSuggestions(parsed.suggestions)
        } catch (e) {
          if (e.message !== "SyntaxError") throw e
        }
      }
    }
  }

  useEffect(() => {
    async function init() {
      const r = await fetch(`${API}/session/new`, { method: "POST" })
      const { session_id } = await r.json()
      setSessionId(session_id)

      setLoading(true)
      const controller = new AbortController()
      abortRef.current = controller
      try {
        let accumulated = ""
        let started = false
        await streamChat("Hola", session_id, controller, (token) => {
          accumulated += token
          if (!started) {
            started = true
            setIsStreaming(true)
            setMessages([{ role: "assistant", content: accumulated }])
          } else {
            setMessages([{ role: "assistant", content: accumulated }])
          }
        })
      } catch (e) {
        if (e.name !== "AbortError")
          setMessages([{ role: "assistant", content: `⚠️ Error al iniciar: ${e.message}` }])
      } finally {
        setLoading(false)
        setIsStreaming(false)
        abortRef.current = null
      }
    }
    init()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  useEffect(() => {
    if (!loading) textareaRef.current?.focus()
  }, [loading])

  async function sendMessage() {
    const text = input.trim()
    if ((!text && !attachedFile) || loading || !sessionId) return

    const fileToSend = attachedFile
    setInput("")
    setAttachedFile(null)
    setSuggestions([])
    if (fileInputRef.current) fileInputRef.current.value = ""

    const displayText = fileToSend
      ? (text ? `📎 ${fileToSend.name}\n\n${text}` : `📎 ${fileToSend.name}`)
      : text
    setMessages(prev => [...prev, { role: "user", content: displayText }])
    setLoading(true)

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
      })

      // Detectar si la respuesta contiene datos de póliza
      if (!poliza) {
        const found = extractPoliza(accumulated, text)
        if (found) setPoliza(found)
      }
    } catch (e) {
      if (e.name !== "AbortError")
        setMessages(prev => [...prev, { role: "assistant", content: `⚠️ Error: ${e.message}` }])
    } finally {
      setLoading(false)
      setIsStreaming(false)
      abortRef.current = null
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

  return (
    <div className="chat-panel">

      {/* Barra de contexto — aparece solo cuando hay póliza cargada */}
      {poliza && (
        <div className="session-bar">
          <span className="session-item">
            <span className="session-label">Póliza</span>
            <span className="session-value">{poliza.numero}</span>
          </span>
          <span className="session-sep">·</span>
          <span className="session-item">
            <span className="session-label">Ramo</span>
            <span className="session-value">{poliza.ramo}</span>
          </span>
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
        </div>
      )}

      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message-row ${msg.role}`}>
            {msg.role === "assistant" && <div className="avatar">SR</div>}
            <div className="bubble">
              {msg.role === "assistant"
                ? <ReactMarkdown>{msg.content}</ReactMarkdown>
                : <span>{msg.content}</span>
              }
            </div>
          </div>
        ))}
        {loading && !isStreaming && (
          <div className="message-row assistant">
            <div className="avatar">SR</div>
            <div className="bubble typing">
              <span /><span /><span />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

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
            <button className="file-remove" onClick={removeAttachment} title="Quitar archivo">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        )}
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
            disabled={loading || !sessionId}
            title="Adjuntar PDF o imagen"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            className="chat-input"
            placeholder="Escribe un mensaje..."
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={loading || !sessionId}
          />
          {loading ? (
            <button className="stop-btn" onClick={handleStop} title="Detener respuesta">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
              </svg>
            </button>
          ) : (
            <button
              className="send-btn"
              onClick={sendMessage}
              disabled={(!input.trim() && !attachedFile) || !sessionId}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          )}
        </div>
        <p className="disclaimer">Desarrollado por Braintrust CS firma miembro de Andersen Consulting</p>
      </div>
    </div>
  )
}
