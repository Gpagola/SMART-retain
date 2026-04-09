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
import mysql.connector
from openai import OpenAI
from langchain_core.messages import HumanMessage

from chatbot import build_agent, get_conn, preload_ontologies, invalidate_ontology_cache, get_active_perfil_id

# Ontologías que pertenecen a un perfil (vs globales como autopilot-*)
PROFILE_ONTOLOGIES = ("system-prompt", "ontologia-reglas", "ontologia-diferenciadores")
from autopilot import generar_caso_aleatorio, correr_conversacion, evaluar_conversacion, get_all_polizas, MOTIVOS, PERSONALIDADES

load_dotenv()

app = Flask(__name__)
CORS(app)  # permite peticiones desde React (localhost:5173)

# ── Estado global del agente ──────────────────────────────────────────────────

from langgraph.checkpoint.memory import MemorySaver as _MemorySaver

_checkpointer = None
_agent = None

def get_agent():
    global _checkpointer, _agent
    if _agent is None:
        _checkpointer = _MemorySaver()
        _agent = build_agent(_checkpointer)
        preload_ontologies()
    return _agent


# ── Generador de sugerencias rápidas ─────────────────────────────────────────

def _analyze_risk_profile(conversation_text: str) -> dict | None:
    """Analiza la conversación y devuelve scores de riesgo, retención y sentimiento."""
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Analiza esta conversación de retención de seguros y devuelve:\n"
                    "1. Riesgo por dimensión (0-100, 0=no detectado, 100=riesgo máximo):\n"
                    "   - precio: percepción de sobrecoste, subida de prima\n"
                    "   - competencia: ofertas de competidores, comparativas\n"
                    "   - experiencia: mala experiencia con siniestros o atención\n"
                    "   - valor: falta de valor percibido, 'nunca lo uso'\n"
                    "   - situacion: cambios personales (mudanza, venta, familia)\n"
                    "   - vinculacion: relación débil con la compañía\n"
                    "2. retencion: probabilidad de retener al cliente (0-100)\n"
                    "3. sentimiento: estado emocional actual del cliente (-100 muy negativo a +100 muy positivo)\n\n"
                    "Responde SOLO JSON: {\"precio\":N,\"competencia\":N,\"experiencia\":N,\"valor\":N,\"situacion\":N,\"vinculacion\":N,\"retencion\":N,\"sentimiento\":N}"
                )},
                {"role": "user", "content": conversation_text[-2000:]},
            ],
            max_tokens=120,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
        result = json.loads(raw)
        for key in ["precio", "competencia", "experiencia", "valor", "situacion", "vinculacion"]:
            result[key] = max(0, min(100, int(result.get(key, 0))))
        result["retencion"] = max(0, min(100, int(result.get("retencion", 50))))
        result["sentimiento"] = max(-100, min(100, int(result.get("sentimiento", 0))))
        return result
    except Exception as e:
        print(f"[risk_profile] error: {e}")
        return None


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
    reincidencia_m = re.search(r"Reincidencia[^:]*[:\s]+(\d+)", text, re.IGNORECASE)
    return {
        "numero":         field(r"Número[:\s]+([^\n]+)"),
        "cliente":        field(r"Cliente[:\s]+([^\n]+)"),
        "ramo":           field(r"Ramo[:\s]+([^\n]+)"),
        "antiguedad":     field(r"Antig[uü]edad[:\s]+([^\n]+)"),
        "rentabilidad":   field(r"Rentabilidad[:\s]+([^\n]+)"),
        "cp":             field(r"\bCP[:\s]+([^\n]+)"),
        "edad":           edad_m.group(1) if edad_m else None,
        "siniestralidad": field(r"Siniestralidad[:\s]+([^\n]+)"),
        "canal_mediador": field(r"Canal mediador[:\s]+([^\n]+)"),
        "reincidencia":   int(reincidencia_m.group(1)) if reincidencia_m else 0,
        "vinculacion":    field(r"Vinculación[:\s]+([^\n]+)"),
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
            # Risk profile al recibir el mensaje del cliente (antes de que responda el agente)
            try:
                prev_state = get_agent().get_state(config)
                prev_msgs = prev_state.values.get("messages", [])
                conv_lines = [
                    f"{'Cliente' if m.type == 'human' else 'Agente'}: {m.content[:300]}"
                    for m in prev_msgs
                    if hasattr(m, "content") and isinstance(m.content, str) and m.content.strip()
                ]
                conv_lines.append(f"Cliente: {message[:300]}")
                if len(conv_lines) > 2:
                    risk = _analyze_risk_profile("\n".join(conv_lines))
                    if risk:
                        yield f"data: {json.dumps({'risk_profile': risk})}\n\n"
            except Exception as ex:
                print(f"[risk_profile chat] {ex}")

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


# ── Endpoints de Perfiles ─────────────────────────────────────────────────────

LOGOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")
os.makedirs(LOGOS_DIR, exist_ok=True)


def _reset_agent():
    """Fuerza la reconstrucción del agente con el system-prompt del perfil activo."""
    global _agent, _checkpointer
    _agent = None
    _checkpointer = None
    invalidate_ontology_cache()


@app.route("/api/perfiles", methods=["GET"])
def listar_perfiles():
    """Lista todos los perfiles. El frontend usa el flag activo para resaltar el actual."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre, aseguradora, logo_url, activo
            FROM perfiles
            ORDER BY id
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return jsonify([
        {"id": r[0], "nombre": r[1], "aseguradora": r[2], "logo_url": r[3], "activo": bool(r[4])}
        for r in rows
    ])


@app.route("/api/perfiles", methods=["POST"])
def crear_perfil():
    """
    Crea un perfil nuevo y le copia las ontologías del perfil indicado en
    `copy_from_perfil_id` (por defecto, el perfil activo). Si no hay ninguno
    para copiar, las inserta vacías.
    Body: { nombre, aseguradora, logo_url?, copy_from_perfil_id? }
    """
    data = request.get_json() or {}
    nombre      = (data.get("nombre") or "").strip()
    aseguradora = (data.get("aseguradora") or "").strip()
    logo_url    = (data.get("logo_url") or "").strip() or None
    copy_from   = data.get("copy_from_perfil_id")

    if not nombre or not aseguradora:
        return jsonify({"error": "nombre y aseguradora son requeridos"}), 400

    if copy_from is None:
        copy_from = get_active_perfil_id()

    conn = get_conn()
    try:
        cur = conn.cursor()

        # Crear el perfil
        try:
            cur.execute("""
                INSERT INTO perfiles (nombre, aseguradora, logo_url, activo)
                VALUES (%s, %s, %s, 0)
            """, (nombre, aseguradora, logo_url))
        except mysql.connector.IntegrityError:
            return jsonify({"error": f"Ya existe un perfil con el nombre '{nombre}'"}), 409

        new_id = cur.lastrowid

        # Copiar ontologías de perfil desde el perfil origen
        for ont_nombre in PROFILE_ONTOLOGIES:
            contenido = ""
            if copy_from:
                cur.execute("""
                    SELECT contenido FROM ontologias
                    WHERE nombre = %s AND activo = TRUE AND perfil_id = %s
                    ORDER BY id DESC LIMIT 1
                """, (ont_nombre, copy_from))
                row = cur.fetchone()
                if row:
                    contenido = row[0]
            cur.execute("""
                INSERT INTO ontologias (nombre, version, contenido, activo, perfil_id)
                VALUES (%s, '1.0', %s, TRUE, %s)
            """, (ont_nombre, contenido, new_id))

        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/perfiles/<int:perfil_id>", methods=["PUT"])
def actualizar_perfil(perfil_id):
    """Actualiza metadatos del perfil. Body: { nombre?, aseguradora?, logo_url? }"""
    data = request.get_json() or {}
    fields = []
    args = []
    for key in ("nombre", "aseguradora", "logo_url"):
        if key in data:
            val = data[key]
            if isinstance(val, str):
                val = val.strip() or None
            fields.append(f"{key} = %s")
            args.append(val)
    if not fields:
        return jsonify({"error": "Nada para actualizar"}), 400

    args.append(perfil_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"UPDATE perfiles SET {', '.join(fields)} WHERE id = %s", tuple(args))
        except mysql.connector.IntegrityError:
            return jsonify({"error": "Ya existe un perfil con ese nombre"}), 409
        conn.commit()
        affected = cur.rowcount
        cur.close()
    finally:
        conn.close()

    if affected == 0:
        return jsonify({"error": "Perfil no encontrado"}), 404
    return jsonify({"ok": True})


@app.route("/api/perfiles/<int:perfil_id>", methods=["DELETE"])
def borrar_perfil(perfil_id):
    """
    Elimina el perfil y, en cascada, sus ontologías (FK ON DELETE CASCADE).
    Restricciones:
    - No se puede borrar el perfil activo.
    - Debe quedar al menos un perfil en el sistema.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT activo FROM perfiles WHERE id = %s", (perfil_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            return jsonify({"error": "Perfil no encontrado"}), 404
        if row[0]:
            cur.close()
            return jsonify({"error": "No se puede borrar el perfil activo. Activa otro primero."}), 400

        cur.execute("SELECT COUNT(*) FROM perfiles")
        if cur.fetchone()[0] <= 1:
            cur.close()
            return jsonify({"error": "Debe existir al menos un perfil"}), 400

        cur.execute("DELETE FROM perfiles WHERE id = %s", (perfil_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/perfiles/<int:perfil_id>/activate", methods=["POST"])
def activar_perfil(perfil_id):
    """Marca el perfil como activo (los demás quedan inactivos) y resetea el agente."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM perfiles WHERE id = %s", (perfil_id,))
        if not cur.fetchone():
            cur.close()
            return jsonify({"error": "Perfil no encontrado"}), 404

        cur.execute("UPDATE perfiles SET activo = 0")
        cur.execute("UPDATE perfiles SET activo = 1 WHERE id = %s", (perfil_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    _reset_agent()
    return jsonify({"ok": True, "id": perfil_id})


@app.route("/api/perfiles/upload-logo", methods=["POST"])
def upload_logo():
    """Recibe un archivo de imagen y lo guarda en disco. Devuelve la URL pública."""
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    file = request.files["file"]
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png", "webp", "svg"):
        return jsonify({"error": "Formato no soportado (jpg, png, webp, svg)"}), 400

    safe_name = f"logo_{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(LOGOS_DIR, safe_name))
    return jsonify({"logo_url": f"/api/logos/{safe_name}"})


@app.route("/api/logos/<path:filename>", methods=["GET"])
def serve_logo(filename):
    """Sirve los logos guardados en LOGOS_DIR."""
    from flask import send_from_directory
    return send_from_directory(LOGOS_DIR, filename)


# ── Endpoints de administración ───────────────────────────────────────────────

@app.route("/api/ontologias", methods=["GET"])
def listar_ontologias():
    """
    Lista las ontologías activas:
    - Las de perfil (system-prompt, ontologia-reglas, ontologia-diferenciadores)
      filtradas por el perfil_id activo.
    - Las globales (autopilot-*) con perfil_id IS NULL.
    """
    perfil_id = get_active_perfil_id()
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Ontologías de perfil
        if perfil_id is not None:
            cur.execute("""
                SELECT o.nombre, o.version, o.contenido
                FROM ontologias o
                INNER JOIN (
                    SELECT nombre, MAX(id) AS max_id
                    FROM ontologias
                    WHERE activo = TRUE AND perfil_id = %s
                    GROUP BY nombre
                ) latest ON o.id = latest.max_id
                ORDER BY o.id
            """, (perfil_id,))
            perfil_rows = cur.fetchall()
        else:
            perfil_rows = []

        # Ontologías globales
        cur.execute("""
            SELECT o.nombre, o.version, o.contenido
            FROM ontologias o
            INNER JOIN (
                SELECT nombre, MAX(id) AS max_id
                FROM ontologias
                WHERE activo = TRUE AND perfil_id IS NULL
                GROUP BY nombre
            ) latest ON o.id = latest.max_id
            ORDER BY o.id
        """)
        global_rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return jsonify([
        {"nombre": r[0], "version": r[1], "contenido": r[2]}
        for r in (*perfil_rows, *global_rows)
    ])


def _guardar_nueva_version(nombre: str, contenido: str) -> str:
    """
    Desactiva la versión activa e inserta una nueva fila.
    Las ontologías de perfil se guardan ligadas al perfil activo;
    las globales (autopilot-*) se guardan con perfil_id NULL.
    Devuelve el número de versión nuevo.
    """
    es_perfil = nombre in PROFILE_ONTOLOGIES
    perfil_id = get_active_perfil_id() if es_perfil else None
    if es_perfil and perfil_id is None:
        raise RuntimeError(f"No hay perfil activo para guardar '{nombre}'.")

    # Cláusula común: misma ontología en el mismo scope (perfil o global)
    scope_clause = "perfil_id = %s" if es_perfil else "perfil_id IS NULL"
    scope_args   = (perfil_id,) if es_perfil else ()

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT version FROM ontologias WHERE nombre = %s AND activo = TRUE AND {scope_clause} "
            f"ORDER BY id DESC LIMIT 1",
            (nombre, *scope_args)
        )
        row = cur.fetchone()
        version_actual = row[0] if row else "1.0"
        try:
            nueva_version = f"{float(version_actual) + 0.1:.1f}"
        except (ValueError, TypeError):
            nueva_version = "1.1"

        cur.execute(
            f"UPDATE ontologias SET activo = FALSE WHERE nombre = %s AND activo = TRUE AND {scope_clause}",
            (nombre, *scope_args)
        )
        cur.execute(
            "INSERT INTO ontologias (nombre, version, contenido, activo, perfil_id) "
            "VALUES (%s, %s, %s, TRUE, %s)",
            (nombre, nueva_version, contenido, perfil_id)
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

    # Cargar contenido y versión actuales (del perfil activo, ya que las 3
    # ontologías mapeadas son siempre de perfil)
    perfil_id = get_active_perfil_id()
    if perfil_id is None:
        return jsonify({"error": "No hay perfil activo"}), 400

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT contenido, version FROM ontologias "
            "WHERE nombre = %s AND activo = TRUE AND perfil_id = %s "
            "ORDER BY id DESC LIMIT 1",
            (nombre, perfil_id)
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": f"No se encontró la ontología '{nombre}' en el perfil activo"}), 404

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

    contenido_nuevo = None
    last_error = None
    for model_name, use_mct in (("gpt-5.4", True), ("gpt-4o", False)):
        try:
            kwargs = dict(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_APLICAR},
                    {"role": "user",   "content": prompt},
                ],
            )
            if use_mct:
                kwargs["max_completion_tokens"] = 4000
            else:
                kwargs["max_tokens"]  = 4000
                kwargs["temperature"] = 0.2
            resp = openai_client.chat.completions.create(**kwargs)
            contenido_nuevo = (resp.choices[0].message.content or "").strip()
            print(f"[apply-recommendation] model={model_name} len={len(contenido_nuevo)}")
            if contenido_nuevo:
                break
        except Exception as e:
            last_error = e
            print(f"[apply-recommendation] model={model_name} error: {e}")

    if not contenido_nuevo:
        return jsonify({"error": f"Error al generar cambio: {last_error or 'respuesta vacía'}"}), 500

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

            def _stream_agent(input_msg):
                """Corre un turno del agente y hace yield de eventos SSE."""
                response = ""
                for chunk, metadata in agent.stream(
                    {"messages": [HumanMessage(content=input_msg)]},
                    config=config,
                    stream_mode="messages",
                ):
                    node = metadata.get("langgraph_node")

                    if node == "agent" and hasattr(chunk, "tool_calls") and chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            tool_name = tc.get("name", "")
                            yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"

                    if node == "tools" and hasattr(chunk, "content") and isinstance(chunk.content, str):
                        if "Póliza encontrada" in chunk.content:
                            poliza_data = _parse_poliza_result(chunk.content)
                            if poliza_data:
                                yield f"data: {json.dumps({'poliza': poliza_data})}\n\n"

                    if node == "agent" and isinstance(chunk.content, str) and chunk.content:
                        response += chunk.content
                        yield f"data: {json.dumps({'type': 'agent_token', 'token': chunk.content})}\n\n"

                if response:
                    yield f"data: {json.dumps({'type': 'agent_end'})}\n\n"
                return response

            # Agente responde al primer mensaje
            agent_response = ""
            for event in _stream_agent(primer_msg):
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

                # Risk profile al recibir mensaje del cliente
                try:
                    conv_text = "\n".join(
                        f"{t['role'].capitalize()}: {t['content'][:300]}"
                        for t in transcripcion
                    )
                    risk = _analyze_risk_profile(conv_text)
                    if risk:
                        yield f"data: {json.dumps({'type': 'risk_profile', 'data': risk})}\n\n"
                except Exception as ex:
                    print(f"[risk_profile autopilot] {ex}")

                if decision in ("retenido", "cancelado"):
                    break

                # Agente responde
                for event in _stream_agent(msg_cliente):
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

            # Enviar datos de fin de conversación (la evaluación se lanza desde el frontend)
            yield f"data: {json.dumps({'type': 'done_conversation', 'transcripcion': transcripcion, 'decision': decision})}\n\n"

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


@app.route("/api/autopilot/evaluate", methods=["POST", "OPTIONS"])
def autopilot_evaluate():
    """Evalúa una conversación de autopilot bajo demanda."""
    if request.method == "OPTIONS":
        return "", 200

    data          = request.get_json()
    transcripcion = data.get("transcripcion", [])
    caso          = data.get("caso", {})
    decision      = data.get("decision", "indeciso")

    try:
        evaluacion = evaluar_conversacion(transcripcion, caso, decision)
        evaluacion["decision"] = decision
        return jsonify(evaluacion)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "decision": decision}), 500


# ── Arranque ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=5001, threaded=True)
