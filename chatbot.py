# ── Importaciones ──────────────────────────────────────────────────────────────

import argparse
import os
from psycopg_pool import ConnectionPool
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

# [LANGGRAPH] Checkpointer para persistencia en PostgreSQL
from langgraph.checkpoint.postgres import PostgresSaver


# ── Carga de variables de entorno ────────────────────────────────────────────
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


# ── Connection Pool ───────────────────────────────────────────────────────────
_pool: ConnectionPool | None = None

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=2, max_size=5, open=True)
    return _pool


# ── Ontology Cache ────────────────────────────────────────────────────────────
_ontology_cache: dict = {}

def preload_ontologies():
    """Carga ontologías estáticas en memoria al arrancar para evitar consultas repetidas."""
    names = ["ontologia-reglas", "ontologia-diferenciadores"]
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            for name in names:
                cur.execute("""
                    SELECT contenido FROM ontologias
                    WHERE nombre = %s AND activo = TRUE
                    ORDER BY version DESC LIMIT 1
                """, (name,))
                row = cur.fetchone()
                if row:
                    _ontology_cache[name] = row[0]

def invalidate_ontology_cache(nombre: str = None):
    """Invalida el cache tras actualizar una ontología desde el admin."""
    if nombre:
        _ontology_cache.pop(nombre, None)
    else:
        _ontology_cache.clear()


# ── Carga del System Prompt desde la BD ───────────────────────────────────────
# El prompt ya no vive en el código — se almacena en la tabla ontologias
# bajo el nombre "system-prompt". Así puede editarse desde un frontend
# sin tocar código, y cada versión queda guardada.

def cargar_system_prompt() -> str:
    """Carga la versión activa del system prompt desde la tabla ontologias."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT contenido FROM ontologias
                WHERE nombre = 'system-prompt' AND activo = TRUE
                ORDER BY version DESC
                LIMIT 1
            """)
            row = cur.fetchone()
    if not row:
        raise RuntimeError("No se encontró 'system-prompt' activo en la base de datos. Ejecuta setup_db.py.")
    return row[0]


# ── Tools (herramientas del agente) ───────────────────────────────────────────

# [LANGCHAIN] @tool convierte la función en una herramienta que el LLM puede decidir invocar.
# El docstring es fundamental: el agente lo lee para saber cuándo y cómo usar la tool.

@tool
def buscar_poliza(numero_poliza: str) -> str:
    """Busca los datos de una póliza por su número.
    Retorna ramo, fecha de alta, antigüedad y rentabilidad.
    Usar cuando el ejecutivo proporcione el número de póliza del cliente."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT numero_poliza, ramo, fecha_alta, rentabilidad
                FROM polizas
                WHERE numero_poliza = %s
            """, (numero_poliza.upper().strip(),))
            row = cur.fetchone()

    if not row:
        return f"No se encontró ninguna póliza con el número '{numero_poliza}'."

    numero, ramo, fecha_alta, rentabilidad = row
    from datetime import date
    antiguedad = (date.today() - fecha_alta).days // 365

    return (
        f"Póliza encontrada:\n"
        f"- Número: {numero}\n"
        f"- Ramo: {ramo}\n"
        f"- Fecha de alta: {fecha_alta.strftime('%d/%m/%Y')}\n"
        f"- Antigüedad: {antiguedad} año(s)\n"
        f"- Rentabilidad: {rentabilidad}"
    )


@tool
def ontologia_reglas(nombre: str = "ontologia-reglas") -> str:
    """Consulta el contenido de una ontología de retención por su nombre.
    Usar para obtener argumentos y contra-argumentos según el motivo de baja del cliente.
    Por defecto consulta 'ontologia-reglas'."""
    if nombre in _ontology_cache:
        return _ontology_cache[nombre]

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT contenido FROM ontologias
                WHERE nombre = %s AND activo = TRUE
                ORDER BY version DESC
                LIMIT 1
            """, (nombre,))
            row = cur.fetchone()

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

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT contenido FROM ontologias
                WHERE nombre = 'ontologia-diferenciadores' AND activo = TRUE
                ORDER BY version DESC
                LIMIT 1
            """)
            row = cur.fetchone()

    if not row:
        return "No se encontró la ontología de diferenciadores. Contacta al administrador."

    return row[0]


@tool
def sugerir_respuestas(opciones: list) -> str:
    """Muestra botones de respuesta rápida al ejecutivo en la interfaz de chat.
    Llamar SIEMPRE al final de cada respuesta con 2-5 opciones cortas relevantes al contexto.
    Considera: motivo de baja, ramo, competidor mencionado, argumentos ya presentados.
    Usa los nombres de competidores reales cuando corresponda: Sura, Reale, Mutua Madrileña.
    opciones: lista de strings cortos, máximo 5 palabras cada uno.
    Ejemplo: ["Sí, acepta", "Lo rechaza", "El precio es alto", "Menciona Sura"]"""
    return "[BOTONES: " + " | ".join(str(o).strip() for o in opciones[:5]) + "]"


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

    # Carga el system prompt desde la BD al iniciar el agente
    system_prompt = cargar_system_prompt()

    # [LANGCHAIN] Vincula las tools al LLM para que pueda decidir cuándo invocarlas
    llm_with_tools = llm.bind_tools(tools)

    # [LANGGRAPH] Nodo "agente": razona y decide si responder o llamar una tool
    def agent_node(state: MessagesState):
        # Inyectamos el SystemMessage al inicio en cada llamada
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    # [LANGGRAPH] Decide si seguir llamando tools o terminar
    def should_continue(state: MessagesState):
        last = state["messages"][-1]
        # Si el LLM pidió ejecutar tools → ir al nodo "tools"
        # Si no hay tool_calls → la respuesta está lista, terminar
        return "tools" if last.tool_calls else END

    # [LANGGRAPH] Construye el grafo ReAct: agent → tools → agent → ... → END
    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))  # ejecuta las tools automáticamente
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue)
    builder.add_edge("tools", "agent")           # tras ejecutar tools, vuelve al agente

    # [LANGGRAPH] compile() con checkpointer activa la persistencia en PostgreSQL
    return builder.compile(checkpointer=checkpointer)


# ── Función principal ─────────────────────────────────────────────────────────

def run_agent(session_id: str):
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()
        agent = build_agent(checkpointer)

        # [LANGGRAPH] thread_id identifica la sesión — permite retomar conversaciones
        config = {"configurable": {"thread_id": session_id}}

        print(f"\n Asistente de Retención — sesión: '{session_id}'")
        print("Escribe 'salir' para terminar.\n")

        # Primer mensaje automático para arrancar el flujo
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
