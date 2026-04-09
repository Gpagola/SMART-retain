import { useState, useRef, useCallback, useEffect } from "react"
import Header from "./components/Header"
import AdminPanel from "./components/AdminPanel"
import ChatPanel from "./components/ChatPanel"
import AutopilotPanel from "./components/AutopilotPanel"
import PerfilSelector from "./components/PerfilSelector"
import "./App.css"

const MIN_WIDTH = 360
const MAX_WIDTH = 600
const DEFAULT_WIDTH = 360

export default function App() {
  const [activeTab, setActiveTab] = useState("lab")     // "lab" | "test" | "user"
  const [adminWidth, setAdminWidth] = useState(DEFAULT_WIDTH)
  const [resetKey, setResetKey] = useState(0)
  const [theme, setTheme] = useState("light")
  const [chatLoading, setChatLoading] = useState(false)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(0)

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme)
  }, [theme])

  // Cuando el usuario cambia de perfil activo, resetear ChatPanel/AutopilotPanel
  // (vía resetKey) y avisar al AdminPanel para que recargue las ontologías del nuevo perfil.
  useEffect(() => {
    function onPerfilChanged() {
      setResetKey(k => k + 1)
      window.dispatchEvent(new CustomEvent("ontologia-updated"))
    }
    window.addEventListener("perfil-changed", onPerfilChanged)
    return () => window.removeEventListener("perfil-changed", onPerfilChanged)
  }, [])

  function handleReset() {
    setResetKey(k => k + 1)
  }

  function toggleTheme() {
    setTheme(t => t === "dark" ? "light" : "dark")
  }

  const onMouseDown = useCallback((e) => {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = adminWidth
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"

    function onMouseMove(e) {
      if (!dragging.current) return
      const delta = e.clientX - startX.current
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta))
      setAdminWidth(newWidth)
    }

    function onMouseUp() {
      dragging.current = false
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      window.removeEventListener("mousemove", onMouseMove)
      window.removeEventListener("mouseup", onMouseUp)
    }

    window.addEventListener("mousemove", onMouseMove)
    window.addEventListener("mouseup", onMouseUp)
  }, [adminWidth])

  const showAdmin = activeTab === "lab" || activeTab === "test"

  const TAB_TITLES = { lab: "Auto-test", test: "Manual-test", user: "User-test" }

  return (
    <div className="app">
      <div className="app-row">
        {showAdmin && (
          <div className="app-sidebar-label">
            <span className="sidebar-title">Smart Retain → Guiado por Ontologías</span>
          </div>
        )}
        <div className="app-col">
          <Header
            loading={chatLoading}
            adminWidth={showAdmin ? adminWidth : undefined}
          />
          <div className="app-body">
            {showAdmin && (
              <>
                <AdminPanel onSaved={handleReset} width={adminWidth} />
                <div className="resize-handle" onMouseDown={onMouseDown} />
              </>
            )}

          <div className="center-panel">
            <div className="center-nav">
              <button
                className={`center-nav-item ${activeTab === "lab" ? "active" : ""}`}
                onClick={() => { setActiveTab("lab"); handleReset() }}
                title="Auto-test: ejecuta una conversación completa simulada entre un cliente IA y el asistente de retención, guiada por las ontologías activas (prompt, reglas y diferenciadores). Permite evaluar automáticamente la calidad de las respuestas y detectar oportunidades de mejora en las ontologías sin intervención humana."
              >
                Auto-test
              </button>
              <button
                className={`center-nav-item ${activeTab === "test" ? "active" : ""}`}
                onClick={() => { setActiveTab("test"); handleReset() }}
                title="Manual-test: tú interpretas al cliente mientras el asistente SR responde según las ontologías activas. Al finalizar, un evaluador IA analiza la conversación en tres niveles (prompt, reglas, diferenciadores), puntúa cada ontología y propone mejoras concretas que puedes aplicar con un clic."
              >
                Manual-test
              </button>
              <button
                className={`center-nav-item ${activeTab === "user" ? "active" : ""}`}
                onClick={() => { setActiveTab("user"); handleReset() }}
                title="User-test: conversación libre con el asistente de retención tal como la tendría un ejecutivo real. Permite probar las ontologías en un escenario realista, con radar de motivos, medidor de retención y sentimiento en tiempo real. Al finalizar se puede evaluar la calidad de las ontologías."
              >
                User-test
              </button>

              <div className="center-nav-spacer" />

              <button className="nav-new-case" onClick={handleReset} title="Reiniciar la sesión actual: limpia la conversación, los indicadores (radar, retención, sentimiento) y los datos de póliza para comenzar un nuevo caso de prueba desde cero.">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                <span>Nuevo caso</span>
              </button>

              <button
                className={`nav-theme-switch ${theme === "dark" ? "dark" : "light"}`}
                onClick={toggleTheme}
                title={theme === "dark" ? "Cambiar a modo claro: interfaz con fondo blanco para entornos con mucha luz" : "Cambiar a modo oscuro: interfaz con fondo oscuro que reduce la fatiga visual en sesiones largas de prueba"}
              >
                <span className="nav-switch-knob" />
                <span className="nav-switch-moon">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                  </svg>
                </span>
                <span className="nav-switch-sun">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="5"/>
                    <line x1="12" y1="1" x2="12" y2="3"/>
                    <line x1="12" y1="21" x2="12" y2="23"/>
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
                    <line x1="1" y1="12" x2="3" y2="12"/>
                    <line x1="21" y1="12" x2="23" y2="12"/>
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
                  </svg>
                </span>
              </button>

              <PerfilSelector />
            </div>
            {activeTab !== "user" && (
              <div className="center-hero">
                <h1 className="center-hero-title">
                  {TAB_TITLES[activeTab]}
                </h1>
              </div>
            )}
            <div className="center-content">
              {activeTab === "lab" && (
                <AutopilotPanel key={`ap-${resetKey}`} onLoadingChange={setChatLoading} />
              )}
              {activeTab === "test" && (
                <ChatPanel key={`test-${resetKey}`} onLoadingChange={setChatLoading} onNewCase={handleReset} showEval />
              )}
              {activeTab === "user" && (
                <ChatPanel key={`user-${resetKey}`} onLoadingChange={setChatLoading} onNewCase={handleReset} showEval />
              )}
            </div>
          </div>
          </div>
        </div>
      </div>
    </div>
  )
}
