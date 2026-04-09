# ── Importaciones ──────────────────────────────────────────────────────────────

import argparse
import os

import mysql.connector
from dotenv import load_dotenv

# [LANGCHAIN] Modelo de lenguaje
from langchain_openai import ChatOpenAI

# [LANGCHAIN] Decorador que convierte una función Python en una tool que el agente puede invocar
from langchain_core.tools import tool

# [LANGCHAIN] SystemMessage para inyectar el system prompt en cada llamada
from langchain_core.messages import SystemMessage

# [LANGGRAPH] Componentes para construir el grafo ReAct manualmente
from langgraph.graph import StateGraph, MessagesState, START, END

# [LANGGRAPH] ToolNode ejecuta las tools que el LLM decide invocar
from langgraph.prebuilt import ToolNode

# [LANGGRAPH] Checkpointer en memoria
from langgraph.checkpoint.memory import MemorySaver


# ── Carga de variables de entorno ────────────────────────────────────────────
load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "database": os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}


# ── Conexión MySQL ────────────────────────────────────────────────────────────

def get_conn():
    """Crea y devuelve una nueva conexión MySQL."""
    return mysql.connector.connect(**DB_CONFIG)


# ── Perfil activo ─────────────────────────────────────────────────────────────

def get_active_perfil_id() -> int | None:
    """Devuelve el id del perfil marcado como activo en la tabla perfiles."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM perfiles WHERE activo = TRUE ORDER BY id LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return row[0] if row else None


# ── Ontology Cache ────────────────────────────────────────────────────────────
_ontology_cache: dict = {}

def preload_ontologies():
    """Carga ontologías del perfil activo en memoria al arrancar."""
    perfil_id = get_active_perfil_id()
    if perfil_id is None:
        print("[preload_ontologies] No hay perfil activo. Saltando precarga.")
        return
    names = ["ontologia-reglas", "ontologia-diferenciadores"]
    conn = get_conn()
    try:
        cur = conn.cursor()
        for name in names:
            cur.execute("""
                SELECT contenido FROM ontologias
                WHERE nombre = %s AND activo = TRUE AND perfil_id = %s
                ORDER BY version DESC LIMIT 1
            """, (name, perfil_id))
            row = cur.fetchone()
            if row:
                _ontology_cache[name] = row[0]
        cur.close()
    finally:
        conn.close()

def invalidate_ontology_cache(nombre: str = None):
    """Invalida el cache tras actualizar una ontología desde el admin o tras cambio de perfil."""
    if nombre:
        _ontology_cache.pop(nombre, None)
    else:
        _ontology_cache.clear()


# ── Carga del System Prompt desde la BD ───────────────────────────────────────

def cargar_system_prompt() -> str:
    """Carga la versión activa del system prompt del perfil activo."""
    perfil_id = get_active_perfil_id()
    if perfil_id is None:
        raise RuntimeError("No hay perfil activo en la tabla perfiles. Ejecuta setup_db.py.")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido FROM ontologias
            WHERE nombre = 'system-prompt' AND activo = TRUE AND perfil_id = %s
            ORDER BY version DESC
            LIMIT 1
        """, (perfil_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not row:
        raise RuntimeError(
            f"No se encontró 'system-prompt' activo para perfil_id={perfil_id}. Ejecuta setup_db.py."
        )
    return row[0]


# ── Tools (herramientas del agente) ───────────────────────────────────────────

@tool
def buscar_poliza(numero_poliza: str) -> str:
    """Busca los datos de una póliza por su número.
    Retorna nombre del cliente, ramo, fecha de alta, antigüedad, rentabilidad, CP, edad, siniestralidad,
    canal mediador, reincidencia en retención y nivel de vinculación.
    Usar cuando el ejecutivo proporcione el número de póliza del cliente."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT numero_poliza, ramo, fecha_alta, rentabilidad,
                   cliente, cp, edad, siniestralidad,
                   canal_mediador, reincidencia, vinculacion
            FROM polizas
            WHERE numero_poliza = %s
        """, (numero_poliza.upper().strip(),))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return f"No se encontró ninguna póliza con el número '{numero_poliza}'."

    numero, ramo, fecha_alta, rentabilidad, cliente, cp, edad, siniestralidad, canal_mediador, reincidencia, vinculacion = row
    from datetime import date
    antiguedad = (date.today() - fecha_alta).days // 365

    return (
        f"Póliza encontrada:\n"
        f"- Número: {numero}\n"
        f"- Cliente: {cliente or 'No disponible'}\n"
        f"- Ramo: {ramo}\n"
        f"- Fecha de alta: {fecha_alta.strftime('%d/%m/%Y')}\n"
        f"- Antigüedad: {antiguedad} año(s)\n"
        f"- Rentabilidad: {rentabilidad}\n"
        f"- CP: {cp or 'No disponible'}\n"
        f"- Edad: {edad or 'No disponible'} años\n"
        f"- Siniestralidad: {siniestralidad or 'No disponible'}\n"
        f"- Canal mediador: {canal_mediador or 'No disponible'}\n"
        f"- Reincidencia en retención: {reincidencia or 0} vez(es)\n"
        f"- Vinculación: {vinculacion or 'No disponible'}"
    )


@tool
def ontologia_reglas(nombre: str = "ontologia-reglas") -> str:
    """Consulta el contenido de una ontología de retención por su nombre.
    Usar para obtener argumentos y contra-argumentos según el motivo de baja del cliente.
    Por defecto consulta 'ontologia-reglas'."""
    if nombre in _ontology_cache:
        return _ontology_cache[nombre]

    perfil_id = get_active_perfil_id()
    if perfil_id is None:
        return "No hay perfil activo configurado."

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido FROM ontologias
            WHERE nombre = %s AND activo = TRUE AND perfil_id = %s
            ORDER BY version DESC
            LIMIT 1
        """, (nombre, perfil_id))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return f"No se encontró la ontología '{nombre}'."
    return row[0]


@tool
def ontologia_diferenciadores() -> str:
    """Consulta las ventajas competitivas de Seguros Mundial frente a la competencia (Sura, Reale, Mutua).
    Usar SOLO cuando el cliente mencione explícitamente una aseguradora competidora.
    El agente elige el diferenciador más relevante según el ramo y competidor mencionado."""
    cache_key = "ontologia-diferenciadores"
    if cache_key in _ontology_cache:
        return _ontology_cache[cache_key]

    perfil_id = get_active_perfil_id()
    if perfil_id is None:
        return "No hay perfil activo configurado."

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido FROM ontologias
            WHERE nombre = 'ontologia-diferenciadores' AND activo = TRUE AND perfil_id = %s
            ORDER BY version DESC
            LIMIT 1
        """, (perfil_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return "No se encontró la ontología de diferenciadores. Contacta al administrador."
    return row[0]


@tool
def analizar_documento(contenido: str) -> str:
    """Analiza el contenido extraído de un documento (PDF o imagen) subido por el ejecutivo.
    Determina el tipo de documento (póliza, oferta de competidor, queja, otro) y extrae
    la información relevante para el proceso de retención.
    Usar cuando el ejecutivo adjunte un archivo al chat."""
    return contenido


# ── Construcción del agente ───────────────────────────────────────────────────

def build_agent(checkpointer):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
    tools = [buscar_poliza, ontologia_reglas, ontologia_diferenciadores, analizar_documento]

    system_prompt = cargar_system_prompt()
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: MessagesState):
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: MessagesState):
        last = state["messages"][-1]
        return "tools" if last.tool_calls else END

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue)
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=checkpointer)


# ── Función principal ─────────────────────────────────────────────────────────

def run_agent(session_id: str):
    checkpointer = MemorySaver()
    agent = build_agent(checkpointer)

    config = {"configurable": {"thread_id": session_id}}

    print(f"\n Asistente de Retención — sesión: '{session_id}'")
    print("Escribe 'salir' para terminar.\n")

    from langchain_core.messages import HumanMessage
    result = agent.invoke(
        {"messages": [HumanMessage(content="Hola, necesito ayuda con un cliente.")]},
        config=config
    )
    print(f"Asistente: {result['messages'][-1].content}\n")

    while True:
        user_input = input("Ejecutivo: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("salir", "exit", "quit"):
            print("Sesión cerrada.")
            break

        result = agent.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config
        )
        print(f"\nAsistente: {result['messages'][-1].content}\n")


# ── Punto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Asistente de retención para contact center")
    parser.add_argument("--session", type=str, default="default", help="ID de sesión")
    args = parser.parse_args()

    run_agent(args.session)
