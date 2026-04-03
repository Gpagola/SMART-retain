"""
Autopilot — Simulador de cliente + Evaluador de conversaciones
Corre conversaciones automáticas contra el agente de retención para hacer pruebas.
"""

import json
import random
from openai import OpenAI
from chatbot import get_conn

client = OpenAI()

# ── Datos de referencia ───────────────────────────────────────────────────────

MOTIVOS = [
    "precio muy alto",
    "me cambio a la competencia (Sura)",
    "me cambio a la competencia (Reale)",
    "me cambio a la competencia (Mutua)",
    "no uso el seguro, no lo necesito",
    "mala experiencia con un siniestro",
    "dificultades económicas, no puedo pagar",
]

PERSONALIDADES = [
    "agresivo y decidido a cancelar",
    "dubitativo y abierto a escuchar",
    "receptivo pero necesita ser convencido con argumentos concretos",
    "muy analítico, compara precios y coberturas",
    "emocional, está frustrado por una mala experiencia",
]


# ── Carga de póliza aleatoria desde la BD ────────────────────────────────────

def get_poliza_aleatoria() -> dict:
    """Devuelve una póliza al azar de la BD."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT numero_poliza, ramo, rentabilidad, cliente
            FROM polizas
            ORDER BY RAND()
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        raise RuntimeError("No hay pólizas en la base de datos.")
    return {
        "numero_poliza": row[0],
        "ramo":          row[1],
        "rentabilidad":  row[2],
        "cliente":       row[3],
    }


def get_all_polizas() -> list[dict]:
    """Devuelve todas las pólizas disponibles."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT numero_poliza, ramo, rentabilidad, cliente FROM polizas ORDER BY numero_poliza")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [{"numero_poliza": r[0], "ramo": r[1], "rentabilidad": r[2], "cliente": r[3]} for r in rows]


# ── Generador de caso aleatorio ───────────────────────────────────────────────

def generar_caso_aleatorio(numero_poliza: str = None) -> dict:
    """Genera un caso de test aleatorio. Si no se da póliza, elige una de la BD."""
    if numero_poliza:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT numero_poliza, ramo, rentabilidad, cliente FROM polizas WHERE numero_poliza = %s",
                (numero_poliza.upper().strip(),)
            )
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        if not row:
            raise ValueError(f"No se encontró la póliza '{numero_poliza}'")
        poliza = {"numero_poliza": row[0], "ramo": row[1], "rentabilidad": row[2], "cliente": row[3]}
    else:
        poliza = get_poliza_aleatoria()

    return {
        "numero_poliza": poliza["numero_poliza"],
        "ramo":          poliza["ramo"],
        "rentabilidad":  poliza["rentabilidad"],
        "cliente":       poliza["cliente"],
        "motivo":        random.choice(MOTIVOS),
        "personalidad":  random.choice(PERSONALIDADES),
    }


# ── LLM Cliente (simula al cliente / humano) ─────────────────────────────────

SYSTEM_CLIENTE = """Simulas lo que un ejecutivo escribe para transmitir la respuesta del cliente. Ramo: {ramo}. Motivo: {motivo}. Personalidad: {personalidad}.
- Responde en 3-8 palabras, directo, sin explicaciones.
- Ejemplos: "está muy caro", "me voy a Sura", "lo voy a pensar", "no me convence", "ok me quedo", "voy a cancelar igual".
- No decidas antes del turno 4.
- Si el agente se despide, da las gracias o da la conversación por cerrada, decidí INMEDIATAMENTE con [DECISION: RETENER] o [DECISION: CANCELAR] según cómo terminó.
- Al decidir, terminá el mensaje con [DECISION: RETENER] o [DECISION: CANCELAR]."""

def _generar_mensaje_cliente(historial: list, caso: dict) -> str:
    """Genera la respuesta del cliente simulado dado el historial."""
    system = SYSTEM_CLIENTE.format(
        ramo=caso["ramo"],
        numero_poliza=caso["numero_poliza"],
        motivo=caso["motivo"],
        personalidad=caso["personalidad"],
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}] + historial[-4:],
        max_tokens=30,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Runner de conversación ────────────────────────────────────────────────────

def correr_conversacion(caso: dict, session_id: str, max_turnos: int = 8) -> list[dict]:
    """
    Corre la conversación completa entre cliente simulado y agente.
    Retorna la transcripción como lista de dicts {role, content}.

    Esta función es un generador que hace yield de eventos SSE-ready:
      {"type": "client_turn", "content": "..."}
      {"type": "agent_turn", "content": "..."}
      {"type": "done", "transcripcion": [...]}
    """
    from langchain_core.messages import HumanMessage
    from chatbot import build_agent, MySQLSaver, preload_ontologies

    checkpointer = MySQLSaver()
    checkpointer.setup()
    agent = build_agent(checkpointer)
    preload_ontologies()
    config = {"configurable": {"thread_id": session_id}}

    historial_cliente = []  # historial para el LLM cliente (formato OpenAI)
    transcripcion = []      # lista completa de turnos

    # Mensaje inicial del ejecutivo al agente
    primer_msg = (
        f"Tengo al cliente {caso['cliente']} en línea, "
        f"póliza {caso['numero_poliza']} del ramo {caso['ramo']}. "
        f"Quiere cancelar porque: {caso['motivo']}. "
        f"Por favor ayúdame a retenerlo."
    )

    # Primer turno: agente recibe el contexto
    agent_response = ""
    for chunk, metadata in agent.stream(
        {"messages": [HumanMessage(content=primer_msg)]},
        config=config,
        stream_mode="messages",
    ):
        node = metadata.get("langgraph_node")
        if node == "agent" and isinstance(chunk.content, str) and chunk.content:
            agent_response += chunk.content

    transcripcion.append({"role": "ejecutivo", "content": primer_msg})
    if agent_response:
        transcripcion.append({"role": "asistente", "content": agent_response})
        historial_cliente.append({"role": "user", "content": f"Ejecutivo (leyendo de la pantalla): {agent_response}"})

    decision = None

    for turno in range(max_turnos):
        # Cliente responde
        msg_cliente = _generar_mensaje_cliente(historial_cliente, caso)
        transcripcion.append({"role": "cliente", "content": msg_cliente})

        # Detectar decisión
        if "[DECISION: RETENER]" in msg_cliente:
            decision = "retenido"
            msg_cliente = msg_cliente.replace("[DECISION: RETENER]", "").strip()
            transcripcion[-1]["content"] = msg_cliente
            break
        if "[DECISION: CANCELAR]" in msg_cliente:
            decision = "cancelado"
            msg_cliente = msg_cliente.replace("[DECISION: CANCELAR]", "").strip()
            transcripcion[-1]["content"] = msg_cliente
            break

        # El ejecutivo transmite la respuesta del cliente al agente
        agent_response = ""
        for chunk, metadata in agent.stream(
            {"messages": [HumanMessage(content=msg_cliente)]},
            config=config,
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node")
            if node == "agent" and isinstance(chunk.content, str) and chunk.content:
                agent_response += chunk.content

        if agent_response:
            transcripcion.append({"role": "asistente", "content": agent_response})
            historial_cliente.append({"role": "assistant", "content": msg_cliente})
            historial_cliente.append({"role": "user", "content": f"Ejecutivo (leyendo de la pantalla): {agent_response}"})

    return transcripcion, decision or "indeciso"


# ── Evaluador ─────────────────────────────────────────────────────────────────

SYSTEM_EVALUADOR = """Eres un experto en calidad de atención al cliente para aseguradoras.
Evaluarás una conversación de retención entre un asistente de IA (que ayuda al ejecutivo) y un cliente.

Debes evaluar en 3 dimensiones y dar recomendaciones concretas de mejora para cada nivel de la ontología:

1. **system-prompt**: instrucciones generales del agente (tono, estructura, personalización)
2. **ontologia-reglas**: argumentos y tácticas según el motivo de cancelación
3. **ontologia-diferenciadores**: uso y calidad de diferenciadores competitivos

Para cada dimensión:
- Score del 1 al 10
- Lista de problemas detectados (puede estar vacía)
- Recomendación concreta de texto a agregar/modificar en esa ontología

Además:
- Score global ponderado
- Resultado: "retenido", "cancelado" o "indeciso"
- Análisis narrativo breve (3-4 oraciones)

Responde SOLO con JSON válido, sin markdown, con esta estructura exacta:
{
  "score_global": 7.5,
  "resultado": "retenido",
  "analisis": "Texto narrativo...",
  "niveles": {
    "system_prompt": {
      "score": 8,
      "problemas": ["problema 1"],
      "recomendacion": "Agregar al system prompt: ..."
    },
    "ontologia_reglas": {
      "score": 6,
      "problemas": ["problema 1"],
      "recomendacion": "En la sección de motivo=precio, agregar: ..."
    },
    "ontologia_diferenciadores": {
      "score": 9,
      "problemas": [],
      "recomendacion": null
    }
  }
}"""

def evaluar_conversacion(transcripcion: list[dict], caso: dict, decision: str) -> dict:
    """Evalúa la conversación y retorna un dict con scores y recomendaciones."""
    transcript_text = "\n".join(
        f"[{t['role'].upper()}]: {t['content']}"
        for t in transcripcion
    )

    prompt = f"""CASO:
- Póliza: {caso['numero_poliza']} | Ramo: {caso['ramo']} | Rentabilidad: {caso['rentabilidad']}
- Motivo del cliente: {caso['motivo']}
- Personalidad: {caso['personalidad']}
- Decisión final: {decision}

TRANSCRIPCIÓN:
{transcript_text}

Evalúa esta conversación de retención."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_EVALUADOR},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
        temperature=0.2,
    )
    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Intentar extraer JSON de la respuesta
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"error": "No se pudo parsear la evaluación", "raw": raw}
