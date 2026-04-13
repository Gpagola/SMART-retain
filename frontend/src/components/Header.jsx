import { useState, useEffect } from "react"
import "./Header.css"

const API = import.meta.env.VITE_API_URL || "/api"
const FALLBACK_LOGO = `${import.meta.env.BASE_URL}logos/logo.jpg`

function resolveLogoUrl(url) {
  if (!url) return FALLBACK_LOGO
  if (url.startsWith("/api/logos/")) return url.replace("/api/logos/", `${API}/logos/`)
  return url
}

export default function Header({ loading, adminWidth }) {
  const [logoUrl, setLogoUrl] = useState(FALLBACK_LOGO)

  function loadActiveLogo() {
    fetch(`${API}/perfiles`)
      .then(r => r.json())
      .then(data => {
        const activo = data.find(p => p.activo)
        setLogoUrl(resolveLogoUrl(activo?.logo_url))
      })
      .catch(() => setLogoUrl(FALLBACK_LOGO))
  }

  useEffect(() => {
    loadActiveLogo()
    function onPerfilChanged() { loadActiveLogo() }
    window.addEventListener("perfil-changed", onPerfilChanged)
    return () => window.removeEventListener("perfil-changed", onPerfilChanged)
  }, [])

  return (
    <>
    <header className="header">
      <div className="header-left" style={adminWidth ? { width: adminWidth } : {}}>
        <span className="header-title">Smart Retain</span>
      </div>
      <div className="header-center">
        <span className="header-subtitle">Desarrollado por Braintrust CS firma miembro de Andersen Consulting</span>
      </div>
      <div className="header-right">
        <img
          src={logoUrl}
          alt="Logo"
          className="header-logo"
          onError={e => { e.target.style.display = "none" }}
        />
      </div>
    </header>
    <div className={`header-bar${loading ? " animating" : ""}`} />
    </>
  )
}
