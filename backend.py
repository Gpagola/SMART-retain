"""
Backend Flask — Asistente de Retención Seguros Mundial
Expone el agente LangGraph como API REST para el frontend React.
"""

import os
import re
import uuid
import base64
import json
import time
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

import pypdf
from openai import OpenAI
from langchain_core.messages import HumanMessage

from chatbot import build_agent, get_conn, MySQLSaver, preload_ontologies, invalidate_ontology_cache
from autopilot import generar_caso_aleatorio, correr_conversacion, evaluar_conversacion, get_all_polizas, MOTIVOS, PERSONALIDADES

load_dotenv()

app = Flask(__name__)
CORS(app)  # permite peticiones desde React (localhost:5173)

# ── Estado global del agente ──────────────────────────────────────────────────

_checkpointer = None
_agent = None

def get_agent():
    global _checkpointer, _agent
    if _agent is None:
        _checkpointer = MySQLSaver()
        _checkpointer.setup()
        _agent = build_agent(_checkpointer)
        preload_ontologies()
    return _agent


# ── Generador de sugerencias rápidas ─────────────────────────────────────────

def _generar_sugerencias_rapidas(user_msg: str, assistant_msg: str) -> list:
    """Genera sugerencias rápidas a partir del último intercambio, sin acceder a la BD."""
    try:
        lines = []
        if user_msg:
            lines.append(f"Ejecutivo: {user_msg[:300]}")
        lines.append(f"Asistente: {assistant_msg[:400]}")

        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Eres un asistente en una app de retención de seguros. "
                    "El ejecutivo de ventas escribe frases cortas para transmitir al asistente IA lo que dice el CLIENTE. "
                    "Dado el último mensaje del asistente, genera 3-4 frases cortas (máx 6 palabras) "
                    "que representen posibles respuestas del CLIENTE. "
                    "Ejemplos si el asistente pregunta el motivo: 'El precio es muy alto', 'Se va a Sura', 'No lo necesita', 'Mala atención en siniestro'. "
                    "Ejemplos si el asistente argumenta valor: 'No me convence', 'Igual está muy caro', 'Lo voy a pensar'. "
                    "NUNCA generes preguntas. NUNCA generes frases del asistente. Solo respuestas del cliente. "
                    "Responde SOLO con JSON array de strings."
                )},
                {"role": "user", "content": f"Último mensaje del asistente:\n{lines[-1] if lines else ''}"},
            ],
            max_tokens=60,
            temperature=0.4,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        result = json.loads(raw)
        if isinstance(result, list):
            return [str(s).strip() for s in result[:4] if s]
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return [str(s).strip() for s in v[:4] if s]
    except Exception as e:
        print(f"[Sugerencias] error: {e}")
    return []


def _generar_sugerencias(session_id: str) -> list:
    """Genera 3-4 respuestas rápidas usando el historial de la sesión."""
    try:
        state = get_agent().get_state({"configurable": {"thread_id": session_id}})
        msgs = state.values.get("messages", [])

        lines = []
        for m in msgs[-8:]:
            if not hasattr(m, "content") or not isinstance(m.content, str) or not m.content.strip():
                continue
            if m.type == "human":
                lines.append(f"Ejecutivo: {m.content[:300]}")
            elif m.type == "ai":
                lines.append(f"Asistente: {m.content[:300]}")

        # Necesitamos al menos 2 turnos del ejecutivo para tener contexto útil
        human_turns = sum(1 for l in lines if l.startswith("Ejecutivo:"))
        if not lines or human_turns < 2:
            return []

        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": (
                "Conversación de retención de seguros:\n"
                + "\n".join(lines)
                + "\n\nBasándote SOLO en lo que se ha dicho en esta conversación, "
                "genera 3-4 frases MUY cortas (máximo 5 palabras) que representen "
                "lo que el CLIENTE podría estar respondiendo en este momento, "
                "para que el ejecutivo las seleccione y se las transmita al asistente. "
                "Deben sonar como el cliente hablando, no como el ejecutivo. "
                "Las frases deben tener sentido concreto en este punto del diálogo. "
                "Si no hay contexto suficiente, devuelve []. "
                "No inventes competidores ni conceptos que no aparezcan en la conversación. "
                'Responde SOLO con un JSON array de strings, sin markdown. '
                'Ejemplo: ["Me parece bien", "El precio es muy alto", "Me lo pienso", "Prefiero Sura"]'
            )}],
            max_tokens=80,
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        print(f"[Sugerencias] raw: {raw!r}")
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        result = json.loads(raw)
        if isinstance(result, list):
            suggestions = [str(s).strip() for s in result[:5] if s]
        elif isinstance(result, dict):
            suggestions = []
            for v in result.values():
                if isinstance(v, list):
                    suggestions = [str(s).strip() for s in v[:5] if s]
                    break
        else:
            suggestions = []
        print(f"[Sugerencias] final: {suggestions}")
        return suggestions
    except Exception as e:
        print(f"[Sugerencias] error: {e}")
    return []


# ── Parser de resultado de buscar_poliza ─────────────────────────────────────

def _parse_poliza_result(text: str) -> dict | None:
    """Parsea el texto devuelto por buscar_poliza y retorna un dict estructurado."""
    if "Póliza encontrada" not in text:
        return None
    def field(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else None
    edad_m = re.search(r"-\s*Edad[:\s]+(\d+)", text, re.IGNORECASE)
    return {
        "numero":        field(r"Número[:\s]+([^\n]+)"),
        "cliente":       field(r"Cliente[:\s]+([^\n]+)"),
        "ramo":          field(r"Ramo[:\s]+([^\n]+)"),
        "antiguedad":    field(r"Antig[uü]edad[:\s]+([^\n]+)"),
        "rentabilidad":  field(r"Rentabilidad[:\s]+([^\n]+)"),
        "cp":            field(r"\bCP[:\s]+([^\n]+)"),
        "edad":          edad_m.group(1) if edad_m else None,
        "siniestralidad": field(r"Siniestralidad[:\s]+([^\n]+)"),
    }


# ── Endpoints de chat ─────────────────────────────────────────────────────────

@app.route("/api/session/new", methods=["POST"])
def new_session():
    """Genera un nuevo session_id único."""
    session_id = str(uuid.uuid4())
    return jsonify({"session_id": session_id})


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Envía un mensaje al agente y devuelve la respuesta en streaming (SSE).
    Body: { "message": "...", "session_id": "..." }
    """
    data = request.get_json()
    message    = data.get("message", "").strip()
    session_id = data.get("session_id", "")

    if not message or not session_id:
        return jsonify({"error": "message y session_id son requeridos"}), 400

    agent  = get_agent()
    config = {"configurable": {"thread_id": session_id}}

    TOOL_STATUS = {
        "buscar_poliza":              "Buscando póliza...",
        "ontologia_reglas":           "Validando reglas de retención...",
        "ontologia_diferenciadores":  "Analizando diferenciadores competitivos...",
        "analizar_documento":         "Analizando documento adjunto...",
    }

    def generate():
        try:
            current_node = None
            agent_response = ""

            for chunk, metadata in agent.stream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node")

                if node != current_node:
                    current_node = node
                    if node == "agent":
                        yield f"data: {json.dumps({'status': 'Pensando...'})}\n\n"

                if node == "agent" and hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        name = tc.get("name", "")
                        if name in TOOL_STATUS:
                            yield f"data: {json.dumps({'status': TOOL_STATUS[name]})}\n\n"

                if node == "tools":
                    content = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(content, str) and "Póliza encontrada" in content:
                        poliza_data = _parse_poliza_result(content)
                        if poliza_data:
                            yield f"data: {json.dumps({'poliza': poliza_data})}\n\n"

                if node == "agent" and isinstance(chunk.content, str) and chunk.content:
                    agent_response += chunk.content
                    yield f"data: {json.dumps({'token': chunk.content})}\n\n"

            # Generar sugerencias al final con la respuesta completa — prompt mínimo
            if agent_response.strip():
                try:
                    oai = OpenAI()
                    r = oai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": (
                                "Retención de seguros. El ejecutivo transmite al asistente lo que dice el cliente. "
                                "Dado el mensaje del asistente, genera 3-4 frases cortas (máx 6 palabras) "
                                "que el CLIENTE podría responder. Solo JSON array, sin markdown."
                            )},
                            {"role": "user", "content": agent_response[-600:]},
                        ],
                        max_tokens=60,
                        temperature=0.4,
                    )
                    raw = r.choices[0].message.content.strip()
                    raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
                    print(f"[suggestions] {raw}")
                    sugerencias = json.loads(raw)
                    if isinstance(sugerencias, list) and sugerencias:
                        yield f"data: {json.dumps({'suggestions': sugerencias})}\n\n"
                except Exception as ex:
                    print(f"[suggestions error] {ex}")

                # Detectar cierre de conversación
                CIERRE_KEYWORDS = ["buen día", "buenas noches", "hasta luego", "que tenga",
                                   "cuídese", "no dude en contactar", "fue un placer"]
                if any(k in agent_response.lower() for k in CIERRE_KEYWORDS):
                    yield f"data: {json.dumps({'cierre': True})}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            print(f"ERROR en /api/chat: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Endpoint de análisis de documentos ───────────────────────────────────────

@app.route("/api/suggestions", methods=["POST"])
def suggestions():
    """Genera sugerencias basadas en el último intercambio (sin consultar la BD)."""
    data = request.get_json()
    user_msg      = data.get("user_msg", "").strip()
    assistant_msg = data.get("assistant_msg", "").strip()
    if not assistant_msg:
        return jsonify([])
    return jsonify(_generar_sugerencias_rapidas(user_msg, assistant_msg))


@app.route("/api/upload", methods=["POST"])
def upload_document():
    """
    Recibe un PDF o imagen, extrae su contenido y lo analiza con GPT-4o Vision.
    Devuelve el texto interpretado listo para pasarle al agente.
    """
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    file     = request.files["file"]
    filename = file.filename.lower()
    client   = OpenAI()

    try:
        if filename.endswith(".pdf"):
            reader = pypdf.PdfReader(file)
            texto  = "\n".join(
                page.extract_text() or "" for page in reader.pages
            ).strip()

            if len(texto) > 100:
                analisis = _interpretar_con_vision(client, texto_plano=texto)
            else:
                file.seek(0)
                raw = file.read()
                b64 = base64.b64encode(raw).decode()
                analisis = _interpretar_con_vision(client, b64_pdf=b64)

        elif filename.endswith((".jpg", ".jpeg", ".png", ".webp")):
            raw = file.read()
            b64 = base64.b64encode(raw).decode()
            ext = filename.rsplit(".", 1)[-1].replace("jpg", "jpeg")
            analisis = _interpretar_con_vision(client, b64_imagen=b64, mime=f"image/{ext}")

        else:
            return jsonify({"error": "Formato no soportado. Usa PDF, JPG o PNG."}), 400

        return jsonify({"contenido": analisis})

    except Exception as e:
        print(f"ERROR en /api/upload: {e}")
        return jsonify({"error": str(e)}), 500


def _interpretar_con_vision(client, texto_plano=None, b64_imagen=None, b64_pdf=None, mime="image/jpeg"):
    """Llama a GPT-4o para interpretar el documento y clasificarlo."""
    instruccion = """Eres un asistente de retención de clientes para una aseguradora.
Analiza el documento adjunto e identifica:
1. TIPO DE DOCUMENTO: ¿Es una póliza de seguro, una oferta de un competidor, una carta de queja, u otro?
2. DATOS CLAVE según el tipo:
   - Si es una póliza: número, ramo, titular, fecha, coberturas, prima
   - Si es oferta de competidor: nombre del competidor, ramo, precio, coberturas ofrecidas
   - Si es una queja: motivo principal, hechos relevantes
   - Otro: resumen del contenido relevante para retención
3. RECOMENDACIÓN: qué debería hacer el ejecutivo con esta información

Responde en español, de forma estructurada y concisa."""

    if texto_plano:
        messages = [{"role": "user", "content": f"{instruccion}\n\nContenido del documento:\n{texto_plano}"}]
    elif b64_imagen:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruccion},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64_imagen}"}}
            ]
        }]
    else:
        messages = [{"role": "user", "content": f"{instruccion}\n\n(PDF escaneado — analiza según el contexto disponible)"}]

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=1000,
    )
    return response.choices[0].message.content


# ── Endpoints de administración ───────────────────────────────────────────────

@app.route("/api/ontologias", methods=["GET"])
def listar_ontologias():
    """Lista todos los registros activos de la tabla ontologias."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT nombre, version, contenido
            FROM ontologias
            WHERE activo = TRUE
            ORDER BY id
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return jsonify([
        {"nombre": r[0], "version": r[1], "contenido": r[2]}
        for r in rows
    ])


def _guardar_nueva_version(nombre: str, contenido: str) -> str:
    """
    Desactiva la versión activa e inserta una nueva fila.
    Devuelve el número de versión nuevo.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Obtener versión actual
        cur.execute(
            "SELECT version FROM ontologias WHERE nombre = %s AND activo = TRUE ORDER BY id DESC LIMIT 1",
            (nombre,)
        )
        row = cur.fetchone()
        version_actual = row[0] if row else "1.0"
        try:
            nueva_version = f"{float(version_actual) + 0.1:.1f}"
        except (ValueError, TypeError):
            nueva_version = "1.1"

        cur.execute(
            "UPDATE ontologias SET activo = FALSE WHERE nombre = %s AND activo = TRUE",
            (nombre,)
        )
        cur.execute(
            "INSERT INTO ontologias (nombre, version, contenido, activo) VALUES (%s, %s, %s, TRUE)",
            (nombre, nueva_version, contenido)
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return nueva_version


def _on_ontology_changed(nombre: str):
    """Invalida cache y, si cambia el system-prompt, fuerza recarga del agente."""
    global _agent, _checkpointer
    invalidate_ontology_cache(nombre)
    if nombre in ("system-prompt", None):
        # El system-prompt está baked en el agente; hay que reconstruirlo
        _agent = None
        _checkpointer = None


@app.route("/api/ontologias/<nombre>", methods=["PUT"])
def actualizar_ontologia(nombre):
    """
    Guarda una nueva versión de la ontología (dejar la anterior inactiva).
    Body: { "contenido": "..." }
    """
    data      = request.get_json()
    contenido = data.get("contenido", "").strip()

    if not contenido:
        return jsonify({"error": "contenido es requerido"}), 400

    nueva_version = _guardar_nueva_version(nombre, contenido)
    _on_ontology_changed(nombre)
    return jsonify({"ok": True, "version": nueva_version})


@app.route("/api/chat/evaluate", methods=["POST", "OPTIONS"])
def chat_evaluate():
    """
    Evalúa una conversación manual usando el mismo evaluador del autopilot.
    Body: { "messages": [{role, content}], "poliza": {...} }
    """
    if request.method == "OPTIONS":
        return "", 200

    data     = request.get_json()
    messages = data.get("messages", [])
    poliza   = data.get("poliza") or {}

    # Convertir al formato que espera evaluar_conversacion
    transcripcion = [
        {
            "role": "ejecutivo" if m["role"] == "user" else "asistente",
            "content": m["content"],
        }
        for m in messages if m.get("content", "").strip()
    ]

    caso = {
        "numero_poliza": poliza.get("numero", "N/A"),
        "ramo":          poliza.get("ramo", "N/A"),
        "rentabilidad":  poliza.get("rentabilidad", "N/A"),
        "cliente":       poliza.get("cliente", "N/A"),
        "motivo":        "modo manual",
        "personalidad":  "modo manual",
    }

    try:
        evaluacion = evaluar_conversacion(transcripcion, caso, "indeciso")
        return jsonify(evaluacion)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/autopilot/apply-recommendation", methods=["POST"])
def apply_recommendation():
    """
    Aplica quirúrgicamente una recomendación del evaluador a la ontología correspondiente.
    Guarda una nueva versión en la BD y invalida el cache.
    Body: { "nivel": "system_prompt|ontologia_reglas|ontologia_diferenciadores",
            "recomendacion": "..." }
    """
    data = request.get_json()
    nivel        = data.get("nivel", "").strip()
    recomendacion = data.get("recomendacion", "").strip()

    if not nivel or not recomendacion:
        return jsonify({"error": "nivel y recomendacion son requeridos"}), 400

    # Mapeo nivel evaluación → nombre en BD
    NIVEL_TO_NOMBRE = {
        "system_prompt":            "system-prompt",
        "ontologia_reglas":          "ontologia-reglas",
        "ontologia_diferenciadores": "ontologia-diferenciadores",
    }
    nombre = NIVEL_TO_NOMBRE.get(nivel)
    if not nombre:
        return jsonify({"error": f"nivel desconocido: {nivel}"}), 400

    # Cargar contenido y versión actuales
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT contenido, version FROM ontologias WHERE nombre = %s AND activo = TRUE ORDER BY id DESC LIMIT 1",
            (nombre,)
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": f"No se encontró la ontología '{nombre}'"}), 404

    contenido_actual = row[0]

    # GPT-4o aplica el cambio quirúrgicamente
    openai_client = OpenAI()
    SYSTEM_APLICAR = (
        "Eres un experto en sistemas de retención de clientes para aseguradoras. "
        "Tu tarea es aplicar una mejora puntual a un fragmento de ontología de un agente de IA.\n\n"
        "Reglas de aplicación:\n"
        "- Aplica ÚNICAMENTE el cambio recomendado, sin alterar el contenido no relacionado\n"
        "- Mantén el formato, estructura y estilo del texto original\n"
        "- Si la recomendación indica agregar texto, agrégalo en el lugar más apropiado\n"
        "- Si indica modificar algo específico, modifícalo con precisión quirúrgica\n"
        "- Devuelve SOLO el texto completo actualizado, sin explicaciones ni marcadores extra\n\n"
        "RESTRICCIÓN sobre el cambio que aplicas (no sobre el contenido existente):\n"
        "- No introduzcas contenido nuevo que incluya descuentos, bonificaciones, rebajas de precio, "
        "cuotas especiales, nuevas coberturas, cambios de tarifa ni concesiones económicas\n"
        "- Si la recomendación recibida sugiere algo de lo anterior, conviértela en su equivalente "
        "de argumentación y valor percibido: enfatiza beneficios existentes, confianza, historial "
        "y valor emocional del producto, sin prometer nada que implique coste\n"
        "- El contenido que YA EXISTE en la ontología no debe ser cuestionado ni eliminado, "
        "aunque incluya referencias a precios o condiciones comerciales"
    )
    prompt = (
        f"ONTOLOGÍA ACTUAL ({nombre}):\n"
        f"---\n{contenido_actual}\n---\n\n"
        f"RECOMENDACIÓN A APLICAR:\n{recomendacion}\n\n"
        f"Devuelve el texto completo de la ontología con el cambio aplicado."
    )

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_APLICAR},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
        contenido_nuevo = resp.choices[0].message.content.strip()
    except Exception as e:
        return jsonify({"error": f"Error al generar cambio: {str(e)}"}), 500

    nueva_version = _guardar_nueva_version(nombre, contenido_nuevo)
    _on_ontology_changed(nombre)

    return jsonify({
        "ok":      True,
        "nombre":  nombre,
        "version": nueva_version,
    })


# ── Endpoints de Autopilot ────────────────────────────────────────────────────

@app.route("/api/autopilot/opciones", methods=["GET"])
def autopilot_opciones():
    """Devuelve las pólizas disponibles y las listas de motivos/personalidades."""
    return jsonify({
        "polizas":       get_all_polizas(),
        "motivos":       MOTIVOS,
        "personalidades": PERSONALIDADES,
    })


@app.route("/api/autopilot/start", methods=["POST"])
def autopilot_start():
    """
    Genera (o valida) el caso de test y crea la sesión.
    Body (todos opcionales): { "numero_poliza": "...", "motivo": "...", "personalidad": "..." }
    Retorna el caso completo con session_id.
    """
    data = request.get_json() or {}
    numero_poliza = data.get("numero_poliza", "").strip() or None
    motivo        = data.get("motivo", "").strip() or None
    personalidad  = data.get("personalidad", "").strip() or None

    try:
        caso = generar_caso_aleatorio(numero_poliza)
        if motivo:
            caso["motivo"] = motivo
        if personalidad:
            caso["personalidad"] = personalidad
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    session_id = str(uuid.uuid4())
    caso["session_id"] = session_id
    return jsonify(caso)


@app.route("/api/autopilot/run/<session_id>", methods=["GET"])
def autopilot_run(session_id):
    """
    Corre la conversación autopilot y emite eventos SSE en tiempo real.
    Parámetros query: numero_poliza, ramo, rentabilidad, cliente, motivo, personalidad
    """
    caso = {
        "numero_poliza": request.args.get("numero_poliza", ""),
        "ramo":          request.args.get("ramo", ""),
        "rentabilidad":  request.args.get("rentabilidad", ""),
        "cliente":       request.args.get("cliente", ""),
        "motivo":        request.args.get("motivo", ""),
        "personalidad":  request.args.get("personalidad", ""),
    }

    def generate():
        transcripcion = []
        decision = "indeciso"

        try:
            from langchain_core.messages import HumanMessage, AIMessage
            from langgraph.checkpoint.memory import MemorySaver
            from chatbot import build_agent
            from autopilot import _generar_mensaje_cliente

            checkpointer = MemorySaver()
            agent = build_agent(checkpointer)
            config = {"configurable": {"thread_id": session_id}}

            # Inyectar saludo falso para que el agente no salude de nuevo
            # y vaya directo a buscar la póliza con el primer mensaje real
            agent.update_state(config, {"messages": [
                HumanMessage(content="Hola"),
                AIMessage(content="¡Hola! Soy el asistente de retención. ¿En qué te puedo ayudar hoy?"),
            ]})

            historial_cliente = []

            # Turno 0: ejecutivo presenta el caso al agente
            primer_msg = (
                f"Tengo al cliente {caso['cliente']} en línea, póliza {caso['numero_poliza']}, ramo {caso['ramo']}. "
                f"Quiere darse de baja. Busca la póliza. "
                f"A partir de ahora cada mensaje que recibas es lo que dice el cliente directamente — "
                f"no me preguntes a mí más información, dirígete al cliente."
            )
            transcripcion.append({"role": "ejecutivo", "content": primer_msg})
            yield f"data: {json.dumps({'type': 'turn', 'role': 'ejecutivo', 'content': primer_msg})}\n\n"

            def _stream_agent(input_msg, turno_label):
                """Corre un turno del agente y hace yield de eventos SSE detallados."""
                def ts(): return int(time.time() * 1000)

                response = ""
                yield f"data: {json.dumps({'type': 'trace', 'turno': turno_label, 'event': 'thinking', 'ts': ts()})}\n\n"
                for chunk, metadata in agent.stream(
                    {"messages": [HumanMessage(content=input_msg)]},
                    config=config,
                    stream_mode="messages",
                ):
                    node = metadata.get("langgraph_node")

                    if node == "agent" and hasattr(chunk, "tool_calls") and chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            tool_name = tc.get("name", "")
                            tool_args = tc.get("args", {})
                            yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"
                            yield f"data: {json.dumps({'type': 'trace', 'turno': turno_label, 'event': 'tool_call', 'tool': tool_name, 'args': tool_args, 'ts': ts()})}\n\n"

                    if node == "tools" and hasattr(chunk, "content") and isinstance(chunk.content, str):
                        tool_name_res = getattr(chunk, "name", "tool")
                        preview = chunk.content[:200].replace("\n", " ")
                        yield f"data: {json.dumps({'type': 'trace', 'turno': turno_label, 'event': 'tool_result', 'tool': tool_name_res, 'preview': preview, 'ts': ts()})}\n\n"
                        if "Póliza encontrada" in chunk.content:
                            poliza_data = _parse_poliza_result(chunk.content)
                            if poliza_data:
                                yield f"data: {json.dumps({'poliza': poliza_data})}\n\n"

                    if node == "agent" and isinstance(chunk.content, str) and chunk.content:
                        response += chunk.content
                        yield f"data: {json.dumps({'type': 'agent_token', 'token': chunk.content})}\n\n"

                if response:
                    yield f"data: {json.dumps({'type': 'trace', 'turno': turno_label, 'event': 'agent_response', 'chars': len(response), 'ts': ts()})}\n\n"
                    yield f"data: {json.dumps({'type': 'agent_end'})}\n\n"
                return response

            # Agente responde al primer mensaje
            agent_response = ""
            for event in _stream_agent(primer_msg, "T0"):
                if event.startswith("data:"):
                    # Extraer respuesta acumulada del generador
                    pass
                yield event

            # Reconstruir agent_response del primer turno leyendo el estado del agente
            state = agent.get_state(config)
            msgs = state.values.get("messages", [])
            last_ai = next((m for m in reversed(msgs) if hasattr(m, "content") and m.type == "ai" and isinstance(m.content, str) and m.content), None)
            agent_response = last_ai.content if last_ai else ""

            if agent_response:
                transcripcion.append({"role": "asistente", "content": agent_response})
                historial_cliente.append({"role": "user", "content": agent_response[:200]})

            CIERRE_KEYWORDS = ["buen día", "buenas noches", "hasta luego", "que tenga", "cuídese",
                               "no dude en contactar", "fue un placer", "procederé a cancelar",
                               "te deseo lo mejor", "lamento que hayamos"]

            # Turnos de conversación
            for turno in range(8):
                # Si el agente ya se despidió en el turno anterior, no generar más cliente
                if agent_response and any(k in agent_response.lower() for k in CIERRE_KEYWORDS):
                    break

                # Cliente responde
                msg_cliente = _generar_mensaje_cliente(historial_cliente, caso)

                if "[DECISION: RETENER]" in msg_cliente:
                    decision = "retenido"
                    msg_cliente = msg_cliente.replace("[DECISION: RETENER]", "").strip()
                elif "[DECISION: CANCELAR]" in msg_cliente:
                    decision = "cancelado"
                    msg_cliente = msg_cliente.replace("[DECISION: CANCELAR]", "").strip()

                transcripcion.append({"role": "cliente", "content": msg_cliente})
                yield f"data: {json.dumps({'type': 'turn', 'role': 'cliente', 'content': msg_cliente})}\n\n"

                if decision in ("retenido", "cancelado"):
                    break

                # Agente responde
                for event in _stream_agent(msg_cliente, f"T{turno+1}"):
                    yield event

                # Leer respuesta acumulada del estado
                state = agent.get_state(config)
                msgs = state.values.get("messages", [])
                last_ai = next((m for m in reversed(msgs) if hasattr(m, "content") and m.type == "ai" and isinstance(m.content, str) and m.content), None)
                agent_response = last_ai.content if last_ai else ""

                if agent_response:
                    transcripcion.append({"role": "asistente", "content": agent_response})
                    historial_cliente.append({"role": "assistant", "content": msg_cliente})
                    historial_cliente.append({"role": "user", "content": agent_response[:200]})

                    if any(k in agent_response.lower() for k in CIERRE_KEYWORDS):
                        decision = decision or "cancelado"

            # Evaluación final
            yield f"data: {json.dumps({'type': 'evaluating'})}\n\n"
            try:
                evaluacion = evaluar_conversacion(transcripcion, caso, decision)
                print(f"[evaluacion] resultado: {json.dumps(evaluacion)[:200]}")
                evaluacion["decision"] = decision
                yield f"data: {json.dumps({'type': 'evaluation', 'data': evaluacion})}\n\n"
            except Exception as eval_err:
                import traceback
                traceback.print_exc()
                print(f"[evaluacion ERROR] {eval_err}")
                yield f"data: {json.dumps({'type': 'evaluation', 'data': {'error': str(eval_err), 'decision': decision, 'score_global': 0, 'analisis': 'Error al evaluar.', 'niveles': {}}})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Arranque ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=5001, threaded=True)
