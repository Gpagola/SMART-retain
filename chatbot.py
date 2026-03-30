# ── Importaciones ──────────────────────────────────────────────────────────────

import argparse
import os
import pickle
from typing import Any, Iterator, Optional, Sequence, Tuple

import mysql.connector
from dotenv import load_dotenv

# [LANGCHAIN] Modelo de lenguaje
from langchain_openai import ChatOpenAI

# [LANGCHAIN] Decorador que convierte una función Python en una tool que el agente puede invocar
from langchain_core.tools import tool

# [LANGCHAIN] SystemMessage para inyectar el system prompt en cada llamada
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

# [LANGGRAPH] Componentes para construir el grafo ReAct manualmente
from langgraph.graph import StateGraph, MessagesState, START, END

# [LANGGRAPH] ToolNode ejecuta las tools que el LLM decide invocar
from langgraph.prebuilt import ToolNode

# [LANGGRAPH] Checkpoint base para implementación personalizada
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple


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

# Alias para compatibilidad con backend.py
def get_pool():
    return None


# ── MySQLSaver (checkpointer personalizado para LangGraph) ───────────────────

class MySQLSaver(BaseCheckpointSaver):
    """Checkpointer de LangGraph con persistencia propia en MySQL."""

    def __init__(self):
        super().__init__()

    def setup(self):
        """Crea las tablas de checkpoints si no existen."""
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id            VARCHAR(100) NOT NULL,
                    checkpoint_ns        VARCHAR(100) NOT NULL DEFAULT '',
                    checkpoint_id        VARCHAR(100) NOT NULL,
                    parent_checkpoint_id VARCHAR(100),
                    checkpoint_data      LONGBLOB     NOT NULL,
                    metadata_data        LONGBLOB     NOT NULL,
                    created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id      VARCHAR(100) NOT NULL,
                    checkpoint_ns  VARCHAR(100) NOT NULL DEFAULT '',
                    checkpoint_id  VARCHAR(100) NOT NULL,
                    task_id        VARCHAR(100) NOT NULL,
                    idx            INTEGER      NOT NULL,
                    channel        VARCHAR(100) NOT NULL,
                    write_data     LONGBLOB     NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                )
            """)
            conn.commit()
            cur.close()
        finally:
            conn.close()

    @staticmethod
    def _serialize(obj) -> bytes:
        return pickle.dumps(obj)

    @staticmethod
    def _deserialize(data: bytes):
        return pickle.loads(bytes(data))

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id     = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        conn = get_conn()
        try:
            cur = conn.cursor()
            if checkpoint_id:
                cur.execute("""
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata_data
                    FROM checkpoints
                    WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s
                """, (thread_id, checkpoint_ns, checkpoint_id))
            else:
                cur.execute("""
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata_data
                    FROM checkpoints
                    WHERE thread_id = %s AND checkpoint_ns = %s
                    ORDER BY checkpoint_id DESC LIMIT 1
                """, (thread_id, checkpoint_ns))

            row = cur.fetchone()
            if not row:
                cur.close()
                return None

            cp_id, parent_cp_id, cp_data, meta_data = row
            checkpoint = self._deserialize(cp_data)
            metadata   = self._deserialize(meta_data)

            cur.execute("""
                SELECT task_id, channel, write_data FROM checkpoint_writes
                WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s
                ORDER BY idx
            """, (thread_id, checkpoint_ns, cp_id))

            pending_writes = [
                (task_id, channel, self._deserialize(blob))
                for task_id, channel, blob in cur.fetchall()
            ]
            cur.close()
        finally:
            conn.close()

        config_out = {
            "configurable": {
                "thread_id":     thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": cp_id,
            }
        }
        parent_config = (
            {
                "configurable": {
                    "thread_id":     thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_cp_id,
                }
            }
            if parent_cp_id else None
        )
        return CheckpointTuple(
            config=config_out,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        if not config:
            return
        thread_id     = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        conn = get_conn()
        try:
            cur = conn.cursor()
            query = """
                SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata_data
                FROM checkpoints
                WHERE thread_id = %s AND checkpoint_ns = %s
                ORDER BY checkpoint_id DESC
            """
            params: list = [thread_id, checkpoint_ns]
            if limit:
                query += " LIMIT %s"
                params.append(limit)
            cur.execute(query, params)
            rows = cur.fetchall()
            cur.close()
        finally:
            conn.close()

        for cp_id, parent_cp_id, cp_data, meta_data in rows:
            checkpoint = self._deserialize(cp_data)
            metadata   = self._deserialize(meta_data)
            config_out = {
                "configurable": {
                    "thread_id":     thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": cp_id,
                }
            }
            parent_config = (
                {
                    "configurable": {
                        "thread_id":     thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_cp_id,
                    }
                }
                if parent_cp_id else None
            )
            yield CheckpointTuple(
                config=config_out,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: dict,
        metadata: dict,
        new_versions: Any,
    ) -> RunnableConfig:
        thread_id            = config["configurable"]["thread_id"]
        checkpoint_ns        = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id        = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        cp_data   = self._serialize(checkpoint)
        meta_data = self._serialize(metadata)

        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                     checkpoint_data, metadata_data)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    checkpoint_data = VALUES(checkpoint_data),
                    metadata_data   = VALUES(metadata_data)
            """, (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                  cp_data, meta_data))
            conn.commit()
            cur.close()
        finally:
            conn.close()

        return {
            "configurable": {
                "thread_id":     thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        thread_id     = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        conn = get_conn()
        try:
            cur = conn.cursor()
            for idx, (channel, value) in enumerate(writes):
                blob = self._serialize(value)
                cur.execute("""
                    INSERT INTO checkpoint_writes
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, write_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE write_data = VALUES(write_data)
                """, (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, blob))
            conn.commit()
            cur.close()
        finally:
            conn.close()


# ── Ontology Cache ────────────────────────────────────────────────────────────
_ontology_cache: dict = {}

def preload_ontologies():
    """Carga ontologías estáticas en memoria al arrancar para evitar consultas repetidas."""
    names = ["ontologia-reglas", "ontologia-diferenciadores"]
    conn = get_conn()
    try:
        cur = conn.cursor()
        for name in names:
            cur.execute("""
                SELECT contenido FROM ontologias
                WHERE nombre = %s AND activo = TRUE
                ORDER BY version DESC LIMIT 1
            """, (name,))
            row = cur.fetchone()
            if row:
                _ontology_cache[name] = row[0]
        cur.close()
    finally:
        conn.close()

def invalidate_ontology_cache(nombre: str = None):
    """Invalida el cache tras actualizar una ontología desde el admin."""
    if nombre:
        _ontology_cache.pop(nombre, None)
    else:
        _ontology_cache.clear()


# ── Carga del System Prompt desde la BD ───────────────────────────────────────

def cargar_system_prompt() -> str:
    """Carga la versión activa del system prompt desde la tabla ontologias."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido FROM ontologias
            WHERE nombre = 'system-prompt' AND activo = TRUE
            ORDER BY version DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not row:
        raise RuntimeError("No se encontró 'system-prompt' activo en la base de datos. Ejecuta setup_db.py.")
    return row[0]


# ── Tools (herramientas del agente) ───────────────────────────────────────────

@tool
def buscar_poliza(numero_poliza: str) -> str:
    """Busca los datos de una póliza por su número.
    Retorna nombre del cliente, ramo, fecha de alta, antigüedad, rentabilidad, CP, edad y siniestralidad.
    Usar cuando el ejecutivo proporcione el número de póliza del cliente."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT numero_poliza, ramo, fecha_alta, rentabilidad,
                   cliente, cp, edad, siniestralidad
            FROM polizas
            WHERE numero_poliza = %s
        """, (numero_poliza.upper().strip(),))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return f"No se encontró ninguna póliza con el número '{numero_poliza}'."

    numero, ramo, fecha_alta, rentabilidad, cliente, cp, edad, siniestralidad = row
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
        f"- Siniestralidad: {siniestralidad or 'No disponible'}"
    )


@tool
def ontologia_reglas(nombre: str = "ontologia-reglas") -> str:
    """Consulta el contenido de una ontología de retención por su nombre.
    Usar para obtener argumentos y contra-argumentos según el motivo de baja del cliente.
    Por defecto consulta 'ontologia-reglas'."""
    if nombre in _ontology_cache:
        return _ontology_cache[nombre]

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido FROM ontologias
            WHERE nombre = %s AND activo = TRUE
            ORDER BY version DESC
            LIMIT 1
        """, (nombre,))
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

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido FROM ontologias
            WHERE nombre = 'ontologia-diferenciadores' AND activo = TRUE
            ORDER BY version DESC
            LIMIT 1
        """)
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
    checkpointer = MySQLSaver()
    checkpointer.setup()
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
