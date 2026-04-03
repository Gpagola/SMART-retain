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
  const [adminOpen, setAdminOpen] = useState(true)
  const [adminWidth, setAdminWidth] = useState(DEFAULT_WIDTH)
  const [resetKey, setResetKey] = useState(0)
  const [theme, setTheme] = useState("light")
  const [chatLoading, setChatLoading] = useState(false)
  const [autopilotMode, setAutopilotMode] = useState(false)
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

  return (
    <div className="app">
      <Header
        adminOpen={adminOpen}
        adminWidth={adminWidth}
        onToggleAdmin={() => setAdminOpen(o => !o)}
        onNewCase={handleReset}
        theme={theme}
        onToggleTheme={toggleTheme}
        loading={chatLoading}
        autopilotMode={autopilotMode}
        onToggleAutopilot={() => setAutopilotMode(m => !m)}
      />
      <div className="app-body">
        {adminOpen && !autopilotMode && (
          <>
            <AdminPanel onSaved={handleReset} width={adminWidth} />
            <div className="resize-handle" onMouseDown={onMouseDown} />
          </>
        )}
        {autopilotMode
          ? <AutopilotPanel key={`ap-${resetKey}`} onLoadingChange={setChatLoading} />
          : <ChatPanel key={resetKey} onLoadingChange={setChatLoading} />
        }
      </div>
    </div>
  )
}
