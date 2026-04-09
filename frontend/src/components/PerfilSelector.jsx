import { useState, useEffect, useRef } from "react"
import "./PerfilSelector.css"

const API = import.meta.env.VITE_API_URL || "/api"

export default function PerfilSelector({ onPerfilChanged }) {
  const [perfiles, setPerfiles] = useState([])
  const [activo, setActivo]     = useState(null)
  const [open, setOpen]         = useState(false)
  const [showManager, setShowManager] = useState(false)
  const dropRef = useRef(null)

  function loadPerfiles() {
    fetch(`${API}/perfiles`)
      .then(r => r.json())
      .then(data => {
        setPerfiles(data)
        const act = data.find(p => p.activo) || data[0] || null
        setActivo(act)
      })
      .catch(console.error)
  }

  useEffect(() => { loadPerfiles() }, [])

  // Cerrar dropdown al hacer click fuera
  useEffect(() => {
    function onClick(e) {
      if (dropRef.current && !dropRef.current.contains(e.target)) setOpen(false)
    }
    if (open) document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [open])

  async function handleActivate(perfil) {
    if (perfil.id === activo?.id) { setOpen(false); return }
    setOpen(false)
    try {
      const r = await fetch(`${API}/perfiles/${perfil.id}/activate`, { method: "POST" })
      if (!r.ok) throw new Error("Error al activar")
      loadPerfiles()
      // Notificar al resto de la app: AdminPanel debe recargar ontologías,
      // ChatPanel/AutopilotPanel deben resetear sesión.
      window.dispatchEvent(new CustomEvent("perfil-changed", { detail: { id: perfil.id } }))
      onPerfilChanged?.(perfil)
    } catch (e) {
      alert("No se pudo activar el perfil: " + e.message)
    }
  }

  function handleManagerClose(reload) {
    setShowManager(false)
    if (reload) loadPerfiles()
  }

  return (
    <div className="perfil-selector" ref={dropRef}>
      <button
        className={`perfil-burger ${open ? "open" : ""}`}
        onClick={() => setOpen(o => !o)}
        title={`Perfil activo: ${activo?.aseguradora || "Sin perfil"}. Clic para cambiar de perfil o gestionarlos.`}
      >
        <span className="perfil-burger-bar" />
        <span className="perfil-burger-bar" />
        <span className="perfil-burger-bar" />
      </button>

      {open && (
        <div className="perfil-dropdown">
          <div className="perfil-dropdown-label">Cambiar de perfil</div>
          {perfiles.map(p => (
            <button
              key={p.id}
              className={`perfil-item ${p.id === activo?.id ? "active" : ""}`}
              onClick={() => handleActivate(p)}
            >
              {p.logo_url && (
                <img
                  src={p.logo_url}
                  alt=""
                  className="perfil-logo-mini"
                  onError={e => { e.target.style.display = "none" }}
                />
              )}
              <div className="perfil-item-text">
                <span className="perfil-item-name">{p.aseguradora}</span>
                <span className="perfil-item-sub">{p.nombre}</span>
              </div>
              {p.id === activo?.id && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              )}
            </button>
          ))}
          <div className="perfil-dropdown-sep" />
          <button
            className="perfil-manage-btn"
            onClick={() => { setOpen(false); setShowManager(true) }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            Gestionar perfiles
          </button>
        </div>
      )}

      {showManager && (
        <PerfilManager
          perfiles={perfiles}
          activoId={activo?.id}
          onClose={handleManagerClose}
        />
      )}
    </div>
  )
}

// ── Modal de gestión ─────────────────────────────────────────────────────────

function PerfilManager({ perfiles, activoId, onClose }) {
  const [editing, setEditing] = useState(null)  // perfil | "new" | null
  const [busy, setBusy]       = useState(false)

  async function handleDelete(p) {
    if (!confirm(`¿Eliminar el perfil "${p.aseguradora}"?\n\nSe borrarán también todas sus ontologías. Esta acción no se puede deshacer.`)) return
    try {
      const r = await fetch(`${API}/perfiles/${p.id}`, { method: "DELETE" })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || "Error al borrar")
      onClose(true)
    } catch (e) {
      alert(e.message)
    }
  }

  async function handleActivate(p) {
    if (p.id === activoId) return
    setBusy(true)
    try {
      const r = await fetch(`${API}/perfiles/${p.id}/activate`, { method: "POST" })
      if (!r.ok) throw new Error("Error al activar")
      window.dispatchEvent(new CustomEvent("perfil-changed", { detail: { id: p.id } }))
      onClose(true)
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <PerfilForm
        perfil={editing === "new" ? null : editing}
        activoId={activoId}
        onCancel={() => setEditing(null)}
        onSaved={() => { setEditing(null); onClose(true) }}
      />
    )
  }

  return (
    <div className="pm-overlay" onClick={() => onClose(false)}>
      <div className="pm-dialog" onClick={e => e.stopPropagation()}>
        <div className="pm-header">
          <span className="pm-title">Perfiles configurados</span>
          <button className="pm-close" onClick={() => onClose(false)} title="Cerrar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="pm-list">
          {perfiles.map(p => (
            <div key={p.id} className={`pm-row ${p.id === activoId ? "active" : ""}`}>
              {p.logo_url ? (
                <img src={p.logo_url} alt="" className="pm-logo" onError={e => { e.target.style.display = "none" }} />
              ) : (
                <div className="pm-logo pm-logo-empty">{(p.aseguradora?.[0] || "?").toUpperCase()}</div>
              )}
              <div className="pm-row-text">
                <span className="pm-row-name">{p.aseguradora}</span>
                <span className="pm-row-sub">{p.nombre}</span>
              </div>
              {p.id === activoId && <span className="pm-active-badge">activo</span>}
              <div className="pm-row-actions">
                {p.id !== activoId && (
                  <button className="pm-btn-mini" onClick={() => handleActivate(p)} disabled={busy}>
                    Activar
                  </button>
                )}
                <button className="pm-btn-mini" onClick={() => setEditing(p)}>Editar</button>
                {p.id !== activoId && perfiles.length > 1 && (
                  <button className="pm-btn-mini danger" onClick={() => handleDelete(p)}>Borrar</button>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="pm-footer">
          <button className="pm-btn-new" onClick={() => setEditing("new")}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            Nuevo perfil
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Formulario de alta/edición ───────────────────────────────────────────────

function PerfilForm({ perfil, activoId, onCancel, onSaved }) {
  const isEdit = !!perfil
  const [nombre, setNombre]           = useState(perfil?.nombre || "")
  const [aseguradora, setAseguradora] = useState(perfil?.aseguradora || "")
  const [logoUrl, setLogoUrl]         = useState(perfil?.logo_url || "")
  const [saving, setSaving]           = useState(false)
  const [uploadingLogo, setUL]        = useState(false)
  const fileRef = useRef(null)

  async function handleLogoUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUL(true)
    try {
      const fd = new FormData()
      fd.append("file", file)
      const r = await fetch(`${API}/perfiles/upload-logo`, { method: "POST", body: fd })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || "Error al subir")
      setLogoUrl(data.logo_url)
    } catch (err) {
      alert(err.message)
    } finally {
      setUL(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  async function handleSave() {
    if (!nombre.trim() || !aseguradora.trim()) {
      alert("Nombre y aseguradora son obligatorios")
      return
    }
    setSaving(true)
    try {
      const url    = isEdit ? `${API}/perfiles/${perfil.id}` : `${API}/perfiles`
      const method = isEdit ? "PUT" : "POST"
      const body   = isEdit
        ? { nombre, aseguradora, logo_url: logoUrl }
        : { nombre, aseguradora, logo_url: logoUrl, copy_from_perfil_id: activoId }
      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || "Error al guardar")
      onSaved()
    } catch (e) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="pm-overlay" onClick={onCancel}>
      <div className="pm-dialog" onClick={e => e.stopPropagation()}>
        <div className="pm-header">
          <span className="pm-title">{isEdit ? "Editar perfil" : "Nuevo perfil"}</span>
          <button className="pm-close" onClick={onCancel} title="Cerrar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="pm-form">
          <label className="pm-field">
            <span>Nombre interno</span>
            <input
              type="text"
              value={nombre}
              onChange={e => setNombre(e.target.value)}
              placeholder="Ej: Seguros Mundial"
            />
          </label>
          <label className="pm-field">
            <span>Aseguradora</span>
            <input
              type="text"
              value={aseguradora}
              onChange={e => setAseguradora(e.target.value)}
              placeholder="Nombre comercial visible"
            />
          </label>
          <div className="pm-field">
            <span>Logo</span>
            <div className="pm-logo-row">
              {logoUrl ? (
                <img src={logoUrl} alt="" className="pm-logo-preview" onError={e => { e.target.style.display = "none" }} />
              ) : (
                <div className="pm-logo-preview pm-logo-empty">?</div>
              )}
              <input
                ref={fileRef}
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.svg"
                style={{ display: "none" }}
                onChange={handleLogoUpload}
              />
              <button
                className="pm-btn-mini"
                onClick={() => fileRef.current?.click()}
                disabled={uploadingLogo}
              >
                {uploadingLogo ? "Subiendo..." : (logoUrl ? "Cambiar" : "Subir logo")}
              </button>
              {logoUrl && (
                <button className="pm-btn-mini danger" onClick={() => setLogoUrl("")}>
                  Quitar
                </button>
              )}
            </div>
          </div>
          {!isEdit && (
            <p className="pm-hint">
              Las ontologías (prompt, reglas, diferenciadores) se copiarán del perfil activo como punto de partida.
              Podrás editarlas después desde el panel de administración.
            </p>
          )}
        </div>

        <div className="pm-footer">
          <button className="pm-btn-cancel" onClick={onCancel}>Cancelar</button>
          <button className="pm-btn-save" onClick={handleSave} disabled={saving}>
            {saving ? "Guardando..." : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  )
}
