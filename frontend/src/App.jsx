import { useState, useRef, useCallback, useEffect } from "react"
import Header from "./components/Header"
import AdminPanel from "./components/AdminPanel"
import ChatPanel from "./components/ChatPanel"
import AutopilotPanel from "./components/AutopilotPanel"
import "./App.css"

const MIN_WIDTH = 380
const MAX_WIDTH = 600
const DEFAULT_WIDTH = 380

export default function App() {
  const [appMode, setAppMode] = useState("ontologist") // "ontologist" | "user"
  const [activeTab, setActiveTab] = useState("lab")     // "lab" | "test"
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

  const isOntologist = appMode === "ontologist"

  return (
    <div className="app">
      <Header
        appMode={appMode}
        onToggleMode={() => { setAppMode(m => m === "ontologist" ? "user" : "ontologist"); handleReset() }}
        onNewCase={handleReset}
        theme={theme}
        onToggleTheme={toggleTheme}
        loading={chatLoading}
        adminWidth={isOntologist ? adminWidth : undefined}
      />
      <div className="app-body">
        {isOntologist && (
          <>
            <AdminPanel onSaved={handleReset} width={adminWidth} />
            <div className="resize-handle" onMouseDown={onMouseDown} />
          </>
        )}

        {isOntologist ? (
          <div className="center-panel">
            <div className="center-nav">
              <button
                className={`center-nav-item ${activeTab === "lab" ? "active" : ""}`}
                onClick={() => { setActiveTab("lab"); handleReset() }}
              >
                Autopilot
              </button>
              <button
                className={`center-nav-item ${activeTab === "test" ? "active" : ""}`}
                onClick={() => { setActiveTab("test"); handleReset() }}
              >
                Prueba manual
              </button>
            </div>
            <div className="center-hero">
              <h1 className="center-hero-title">
                {activeTab === "lab" ? "Autopilot" : "Prueba Manual"}
              </h1>
            </div>
            <div className="center-content">
              {activeTab === "lab"
                ? <AutopilotPanel key={`ap-${resetKey}`} onLoadingChange={setChatLoading} />
                : <ChatPanel key={`test-${resetKey}`} onLoadingChange={setChatLoading} onNewCase={handleReset} showEval />
              }
            </div>
          </div>
        ) : (
          <ChatPanel key={`user-${resetKey}`} onLoadingChange={setChatLoading} onNewCase={handleReset} />
        )}
      </div>
    </div>
  )
}
