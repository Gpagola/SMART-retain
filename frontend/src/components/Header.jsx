import "./Header.css"

export default function Header({ loading, adminWidth }) {
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
          src={`${import.meta.env.BASE_URL}logos/logo.jpg`}
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
