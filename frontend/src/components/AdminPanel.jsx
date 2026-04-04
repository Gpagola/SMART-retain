import { useState, useEffect, useLayoutEffect, useRef } from "react"
import "./AdminPanel.css"

const API = import.meta.env.VITE_API_URL || "/api"

const LABELS = {
  "system-prompt":             "System Prompt",
  "ontologia-reglas":          "Reglas de Retención",
  "ontologia-diferenciadores": "Diferenciadores",
}

function findMatches(text, query) {
  if (!query.trim()) return []
  const result = []
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  let i = 0
  while (i < lower.length) {
    const pos = lower.indexOf(q, i)
    if (pos === -1) break
    result.push(pos)
    i = pos + 1
  }
  return result
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

function buildHighlightHtml(text, query, currentIdx, matchArr) {
  if (!query || !matchArr.length) return escapeHtml(text)
  let result = ""
  let last = 0
  matchArr.forEach((pos, i) => {
    result += escapeHtml(text.slice(last, pos))
    const cls = i === currentIdx ? "match-current" : "match"
    result += `<mark class="${cls}">${escapeHtml(text.slice(pos, pos + query.length))}</mark>`
    last = pos + query.length
  })
  return result + escapeHtml(text.slice(last))
}

export default function AdminPanel({ onSaved, width }) {
  const [ontologias, setOntologias] = useState([])
  const [selected, setSelected]     = useState(null)
  const [contenido, setContenido]   = useState("")
  const [saving, setSaving]         = useState(false)
  const [dirty, setDirty]           = useState(false)

  const [searchOpen, setSearchOpen]   = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [matchIndex, setMatchIndex]   = useState(0)

  const textareaRef = useRef(null)
  const hlRef       = useRef(null)
  const searchRef   = useRef(null)

  const matches = findMatches(contenido, searchQuery)

  // ── Sincroniza estilos y compensa ancho de scrollbar ──────────────────────
  useLayoutEffect(() => {
    const ta = textareaRef.current
    const hl = hlRef.current
    if (!ta || !hl) return

    const s = window.getComputedStyle(ta)
    ;[
      'fontFamily', 'fontSize', 'fontWeight', 'fontStyle',
      'lineHeight', 'letterSpacing', 'wordSpacing', 'textIndent', 'tabSize',
      'paddingTop', 'paddingLeft', 'paddingBottom',
      'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
      'boxSizing',
    ].forEach(p => { try { hl.style[p] = s[p] } catch (_) {} })

    // Compensar el ancho del scrollbar del textarea para que el texto wrappe igual
    const scrollbarW = ta.offsetWidth - ta.clientWidth
    hl.style.paddingRight = (parseFloat(s.paddingRight || '0') + scrollbarW) + 'px'
  })  // sin deps — se re-ejecuta en cada render para capturar cambios de scrollbar

  // ── Sincroniza scroll: textarea → highlight layer ─────────────────────────
  useEffect(() => {
    const ta = textareaRef.current
    const hl = hlRef.current
    if (!ta || !hl) return
    const sync = () => { hl.scrollTop = ta.scrollTop }
    ta.addEventListener("scroll", sync)
    return () => ta.removeEventListener("scroll", sync)
  }, [])

  // ── Scroll al match actual usando la posición del mark en el highlight layer
  function jumpTo(idx, arr) {
    if (!arr?.length) return
    setTimeout(() => {
      const ta = textareaRef.current
      const hl = hlRef.current
      if (!ta || !hl) return
      const marks = hl.querySelectorAll("mark")
      if (!marks[idx]) return
      ta.scrollTop = Math.max(0, marks[idx].offsetTop - ta.clientHeight / 3)
    }, 30)
  }

  function handleSearchChange(e) {
    const q = e.target.value
    setSearchQuery(q)
    setMatchIndex(0)
    const arr = findMatches(contenido, q)
    if (arr.length) jumpTo(0, arr)
  }

  function navigate(dir) {
    if (!matches.length) return
    const next = (matchIndex + dir + matches.length) % matches.length
    setMatchIndex(next)
    jumpTo(next, matches)
  }

  function toggleSearch() {
    setSearchOpen(o => {
      if (!o) setTimeout(() => searchRef.current?.focus(), 50)
      else { setSearchQuery(""); setMatchIndex(0) }
      return !o
    })
  }

  function handleSearchKey(e) {
    if (e.key === "Enter")  { e.preventDefault(); navigate(e.shiftKey ? -1 : 1) }
    if (e.key === "Escape") { toggleSearch() }
  }

  function loadOntologias(keepSelected) {
    fetch(`${API}/ontologias`)
      .then(r => r.json())
      .then(data => {
        setOntologias(data)
        if (!keepSelected && data.length) {
          setSelected(data[0].nombre)
          setContenido(data[0].contenido)
          setDirty(false)
        } else if (keepSelected) {
          // Actualizar contenido del tab activo con la versión más reciente
          setSelected(prev => {
            const updated = data.find(o => o.nombre === prev)
            if (updated) {
              setContenido(updated.contenido)
              setDirty(false)
            }
            return prev
          })
        }
      })
  }

  useEffect(() => {
    loadOntologias(false)
  }, [])

  // Escuchar cambios externos (evaluación, agente autónomo)
  useEffect(() => {
    function onExternalChange() { loadOntologias(true) }
    window.addEventListener("ontologia-updated", onExternalChange)
    return () => window.removeEventListener("ontologia-updated", onExternalChange)
  }, [])

  function handleSelect(nombre) {
    const item = ontologias.find(o => o.nombre === nombre)
    setSelected(nombre)
    setContenido(item?.contenido || "")
    setDirty(false)
    setSearchQuery("")
    setMatchIndex(0)
  }

  function handleChange(e) {
    setContenido(e.target.value)
    setDirty(true)
  }

  async function handleSave() {
    const confirmReset = window.confirm(
      "¿Aplicar cambios ahora?\n\nLa sesión de chat actual se cerrará y comenzará una nueva con el contenido actualizado.\n\nPulsa Cancelar para guardar sin reiniciar el chat."
    )
    setSaving(true)
    await fetch(`${API}/ontologias/${selected}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contenido }),
    })
    setSaving(false)
    setDirty(false)
    loadOntologias(true)
    if (confirmReset) onSaved()
  }

  return (
    <aside className="admin-panel" style={width ? { width, minWidth: width, maxWidth: width } : {}}>
      <div className="admin-tabs">
        {ontologias.map(o => (
          <button
            key={o.nombre}
            className={`admin-tab ${selected === o.nombre ? "active" : ""}`}
            onClick={() => handleSelect(o.nombre)}
          >
            {LABELS[o.nombre] || o.nombre}
          </button>
        ))}
      </div>

      <div className="admin-editor">
        <div className="editor-wrap">
          {/* Highlight layer — detrás del textarea */}
          <div
            ref={hlRef}
            className="highlight-layer"
            dangerouslySetInnerHTML={{ __html: buildHighlightHtml(contenido, searchQuery, matchIndex, matches) }}
          />
          {/* Textarea editable — encima, fondo transparente cuando hay búsqueda activa */}
          <textarea
            ref={textareaRef}
            className={`admin-textarea ${searchOpen ? "search-active" : ""}`}
            value={contenido}
            onChange={handleChange}
            spellCheck={false}
          />
        </div>
      </div>

      {searchOpen && (
        <div className="search-bar">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            ref={searchRef}
            className="search-input"
            placeholder="Buscar..."
            value={searchQuery}
            onChange={handleSearchChange}
            onKeyDown={handleSearchKey}
          />
          {searchQuery && (
            <span className="search-count">
              {matches.length ? `${matchIndex + 1}/${matches.length}` : "0 resultados"}
            </span>
          )}
          <button className="search-nav" onClick={() => navigate(-1)} disabled={!matches.length} title="Anterior">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="18 15 12 9 6 15"/></svg>
          </button>
          <button className="search-nav" onClick={() => navigate(1)} disabled={!matches.length} title="Siguiente">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
      )}

      <div className="admin-footer">
        <button className="save-btn" onClick={handleSave} disabled={saving || !dirty}>
          {saving ? "Guardando..." : "Guardar"}
        </button>
        {dirty && <span className="unsaved">Sin guardar</span>}
        <button
          className={`search-toggle ${searchOpen ? "active" : ""}`}
          onClick={toggleSearch}
          title="Buscar en el contenido"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </button>
      </div>
    </aside>
  )
}
