# ── Importaciones ──────────────────────────────────────────────────────────────

# python-dotenv: librería estándar de Python para leer variables de entorno
# desde el archivo .env (NO es de LangChain)
from dotenv import load_dotenv

# [LANGCHAIN] ChatOpenAI: wrapper de LangChain sobre la API de OpenAI.
# Permite usar modelos de chat (gpt-4o-mini, gpt-4, etc.) con la interfaz
# estándar de LangChain, sin llamar directamente a la API de OpenAI.
from langchain_openai import ChatOpenAI

# [LANGCHAIN] Clases de mensajes de LangChain. Representan los 3 roles
# que existen en una conversación con un LLM:
#   - SystemMessage  → instrucciones iniciales / personalidad del bot
#   - HumanMessage   → lo que escribe el usuario
#   - AIMessage      → la respuesta que dio el modelo anteriormente
# Usarlas permite construir el historial de conversación de forma estructurada.
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


# ── Carga de variables de entorno ───────────────────────────────────────────────

# Lee el archivo .env y carga OPENAI_API_KEY como variable de entorno.
# LangChain la detecta automáticamente al crear el modelo.
load_dotenv()


# ── Prompt del sistema ──────────────────────────────────────────────────────────

# Este texto define la "personalidad" y el alcance del chatbot.
# Se envía al modelo al inicio de cada conversación como SystemMessage.
# El modelo lo usa como contexto permanente para todas sus respuestas.
SYSTEM_PROMPT = """Eres un experto en fútbol con amplio conocimiento sobre:
- Historia del fútbol mundial
- Ligas y torneos (Champions League, Premier League, La Liga, Serie A, etc.)
- Jugadores legendarios y actuales
- Selecciones nacionales yurdiales
- Estadísticas, récords y curiosidades
- Tácticas y análisis de juego

Solo respondes preguntas relacionadas con el fútbol. Si el usuario pregunta sobre otro tema,
redirige amablemente la conversación de vuelta al fútbol."""


# ── Función principal del chatbot ───────────────────────────────────────────────

def run_chatbot():
    # [LANGCHAIN] Crea el modelo de lenguaje.
    # - model: el modelo de OpenAI a usar (gpt-4o-mini es rápido y económico)
    # - temperature: controla la creatividad de las respuestas.
    #   0.0 = respuestas más deterministas/exactas
    #   1.0 = respuestas más variadas/creativas
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)

    # [LANGCHAIN] Historial de mensajes. Es una lista de objetos Message de LangChain.
    # Empieza con el SystemMessage que define la personalidad del bot.
    # Cada vez que el usuario habla y el bot responde, se agregan nuevos mensajes.
    # Al enviar toda la lista al modelo, este "recuerda" la conversación completa.
    history = [SystemMessage(content=SYSTEM_PROMPT)]

    print("⚽ Bienvenido al Chatbot de Fútbol ⚽")
    print("Pregúntame cualquier cosa sobre fútbol. Escribe 'salir' para terminar.\n")

    # Bucle principal: se repite hasta que el usuario escriba 'salir'
    while True:
        user_input = input("Tú: ").strip()

        # Ignorar entrada vacía (el usuario presionó Enter sin escribir nada)
        if not user_input:
            continue

        # Salir del programa si el usuario escribe alguna de estas palabras
        if user_input.lower() in ("salir", "exit", "quit"):
            print("¡Hasta la próxima! ⚽")
            break

        # [LANGCHAIN] Agrega el mensaje del usuario al historial como HumanMessage
        history.append(HumanMessage(content=user_input))

        # [LANGCHAIN] Envía TODO el historial al modelo y obtiene una respuesta.
        # El modelo recibe: [SystemMessage, HumanMessage, AIMessage, HumanMessage, ...]
        # Esto es lo que le da "memoria" al chatbot — el modelo ve toda la conversación.
        response = llm.invoke(history)

        # [LANGCHAIN] Agrega la respuesta del modelo al historial como AIMessage,
        # para que en el siguiente turno el modelo recuerde lo que ya dijo.
        history.append(AIMessage(content=response.content))

        print(f"\nBot: {response.content}\n")


# ── Punto de entrada ────────────────────────────────────────────────────────────

# Solo ejecuta run_chatbot() si este archivo se corre directamente (no si se importa)
if __name__ == "__main__":
    run_chatbot()
