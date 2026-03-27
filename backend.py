"""
Backend Flask — Asistente de Retención Seguros Mundial
Expone el agente LangGraph como API REST para el frontend React.
"""

import os
import re
import uuid
import base64
import json
import psycopg
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

import pypdf
from openai import OpenAI
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver

from chatbot import build_agent, DATABASE_URL, preload_ontologies, invalidate_ontology_cache

load_dotenv()

app = Flask(__name__)
CORS(app)  # permite peticiones desde React (localhost:5173)

# ── Estado global del agente ──────────────────────────────────────────────────
# El checkpointer y el agente se inicializan una vez al arrancar el servidor.
# Cada sesión se identifica por su thread_id (session_id).

_checkpointer = None
_agent = None

def get_agent():
    global _checkpointer, _agent
    if _agent is None:
        # Conexión persistente para el ciclo de vida del servidor Flask
        conn = psycopg.connect(DATABASE_URL)
        _checkpointer = PostgresSaver(conn)
        _checkpointer.setup()
        _agent = build_agent(_checkpointer)
        preload_ontologies()
    return _agent


# ── Generador de sugerencias rápidas ─────────────────────────────────────────

def _generar_sugerencias(session_id: str) -> list:
    """Genera 3-5 respuestas rápidas usando el historial de la sesión."""
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

        # Necesitamos al menos 2 turnos completos (ejecutivo + asistente x2) para sugerir algo útil
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
        print(f"[Sugerencias] raw GPT response: {raw!r}")
        # Strip markdown code fences if present (```json ... ``` or ``` ... ```)
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        result = json.loads(raw)
        print(f"[Sugerencias] parsed: {result}")
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
    message = data.get("message", "").strip()
    session_id = data.get("session_id", "")

    if not message or not session_id:
        return jsonify({"error": "message y session_id son requeridos"}), 400

    agent = get_agent()
    config = {"configurable": {"thread_id": session_id}}

    def generate():
        try:
            for chunk, metadata in agent.stream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode="messages",
            ):
                if (
                    metadata.get("langgraph_node") == "agent"
                    and isinstance(chunk.content, str)
                    and chunk.content
                ):
                    yield f"data: {json.dumps({'token': chunk.content})}\n\n"

            # Post-proceso: generar sugerencias con el historial actualizado
            suggestions = _generar_sugerencias(session_id)
            print(f"[Chat] suggestions to send: {suggestions}")
            if suggestions:
                payload = json.dumps({'suggestions': suggestions})
                print(f"[Chat] sending SSE: {payload}")
                yield f"data: {payload}\n\n"

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

@app.route("/api/upload", methods=["POST"])
def upload_document():
    """
    Recibe un PDF o imagen, extrae su contenido y lo analiza con GPT-4o Vision.
    Devuelve el texto interpretado listo para pasarle al agente.
    """
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    file = request.files["file"]
    filename = file.filename.lower()
    client = OpenAI()

    try:
        # ── PDF ──────────────────────────────────────────────────────────────
        if filename.endswith(".pdf"):
            reader = pypdf.PdfReader(file)
            texto = "\n".join(
                page.extract_text() or "" for page in reader.pages
            ).strip()

            # Si el PDF tiene texto extraíble lo usamos directamente
            if len(texto) > 100:
                analisis = _interpretar_con_vision(client, texto_plano=texto)
            else:
                # PDF escaneado — convertir primera página a imagen via Vision
                file.seek(0)
                raw = file.read()
                b64 = base64.b64encode(raw).decode()
                analisis = _interpretar_con_vision(client, b64_pdf=b64)

        # ── Imagen ───────────────────────────────────────────────────────────
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
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nombre, version, contenido
                FROM ontologias
                WHERE activo = TRUE
                ORDER BY id
            """)
            rows = cur.fetchall()

    return jsonify([
        {"nombre": r[0], "version": r[1], "contenido": r[2]}
        for r in rows
    ])


@app.route("/api/ontologias/<nombre>", methods=["PUT"])
def actualizar_ontologia(nombre):
    """
    Actualiza el contenido de una ontología por nombre.
    Body: { "contenido": "..." }
    """
    data = request.get_json()
    contenido = data.get("contenido", "").strip()

    if not contenido:
        return jsonify({"error": "contenido es requerido"}), 400

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ontologias
                SET contenido = %s
                WHERE nombre = %s AND activo = TRUE
            """, (contenido, nombre))
        conn.commit()

    invalidate_ontology_cache(nombre)
    return jsonify({"ok": True})


# ── Arranque ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=5001)
