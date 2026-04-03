import "./Header.css"

function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
  )
}

function MoonIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  )
}

export default function Header({ adminOpen, adminWidth, onToggleAdmin, onNewCase, theme, onToggleTheme, loading, autopilotMode, onToggleAutopilot }) {
  const isDark = theme === "dark"

  return (
    <>
    <header className="header">
      <div className="header-left" style={adminOpen ? { width: adminWidth } : {}}>
        <img
          src={`${import.meta.env.BASE_URL}logos/logo.jpg`}
          alt="Logo"
          className="header-logo"
          onError={e => { e.target.style.display = "none" }}
        />
        <div className="header-divider" />
        <span className="header-title">Smart Retain</span>
      </div>
      <div className="header-right">
        {/* Toggle Manual / Autopilot */}
        <div className="mode-toggle">
          <button
            className={`mode-btn ${!autopilotMode ? "active" : ""}`}
            onClick={() => autopilotMode && onToggleAutopilot()}
            title="Modo manual"
          >
            Manual
          </button>
          <button
            className={`mode-btn ${autopilotMode ? "active autopilot" : ""}`}
            onClick={() => !autopilotMode && onToggleAutopilot()}
            title="Modo autopilot"
          >
            ⚡ Autopilot
          </button>
        </div>

        <button className="new-case-btn" onClick={onNewCase} title="Nuevo caso">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          <span>Nuevo caso</span>
        </button>
        <button
          className={`admin-toggle ${adminOpen ? "active" : ""}`}
          onClick={onToggleAdmin}
          title={adminOpen ? "Ocultar estrategia" : "Mostrar estrategia"}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v0A2.5 2.5 0 0 1 14.5 2H15a5 5 0 0 1 5 5v1a5 5 0 0 1-5 5h-1.5"/>
            <path d="M14.5 22A2.5 2.5 0 0 1 12 19.5v0A2.5 2.5 0 0 1 9.5 22H9a5 5 0 0 1-5-5v-1a5 5 0 0 1 5-5h1.5"/>
            <path d="M12 4.5v15"/>
          </svg>
          <span>Estrategia</span>
        </button>

        {/* Switch luna/sol */}
        <button
          className={`theme-switch ${isDark ? "dark" : "light"}`}
          onClick={onToggleTheme}
          title={isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
        >
          <span className="switch-knob" />
          <span className="switch-moon"><MoonIcon /></span>
          <span className="switch-sun"><SunIcon /></span>
        </button>
      </div>
    </header>
    <div className={`header-bar${loading ? " animating" : ""}`} />
    </>
  )
}
