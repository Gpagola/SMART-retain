"""
Script para crear las tablas y cargar datos en MySQL.
Ejecutar una sola vez: python setup_db.py
"""

import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "database": os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# ── Definición de tablas ─────────────────────────────────────────────────────

CREATE_POLIZAS = """
CREATE TABLE IF NOT EXISTS polizas (
    numero_poliza VARCHAR(20)  PRIMARY KEY,
    ramo          VARCHAR(50)  NOT NULL,
    fecha_alta    DATE         NOT NULL,
    rentabilidad  VARCHAR(10)  NOT NULL,
    cliente       VARCHAR(100),
    cp            VARCHAR(10),
    edad          INT,
    siniestralidad VARCHAR(10),
    canal_mediador VARCHAR(50),
    reincidencia   INT DEFAULT 0,
    vinculacion    VARCHAR(20)
);
"""

CREATE_ONTOLOGIAS = """
CREATE TABLE IF NOT EXISTS ontologias (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    nombre    VARCHAR(100) NOT NULL,
    version   VARCHAR(10)  NOT NULL DEFAULT '1.0',
    contenido LONGTEXT     NOT NULL,
    activo    TINYINT(1)   NOT NULL DEFAULT 1,
    UNIQUE KEY uq_nombre_version (nombre, version)
);
"""

# ── Datos mock: pólizas ──────────────────────────────────────────────────────

import random
from datetime import date, timedelta

_RAMOS = ["Decesos", "Vida", "Hogar", "Salud", "Accidentes", "Auto"]
_RENTAB = ["alta", "media", "baja"]
_SINIEST = ["baja", "media", "alta"]
_CANALES = ["Directo", "Broker", "Agente", "Comparador"]
_VINCUL = ["Plata", "Oro", "Platino"]
_CPS = ["08001", "28001", "41001", "46001", "11001", "76001", "05001", "15001", "48001", "29001",
        "33001", "03001", "35001", "38001", "50001", "30001", "07001", "47001", "18001", "37001"]

_NOMBRES = [
    "María", "Carlos", "Ana", "Roberto", "Luisa", "Pedro", "Carmen", "Javier",
    "Isabel", "Fernando", "Elena", "Miguel", "Laura", "Antonio", "Sofía",
    "Francisco", "Marta", "José", "Patricia", "Manuel", "Raquel", "Alberto",
    "Cristina", "Daniel", "Beatriz", "Alejandro", "Lucía", "David", "Paula",
    "Jorge", "Alicia", "Sergio", "Rosa", "Andrés", "Pilar", "Diego",
    "Teresa", "Óscar", "Victoria", "Adrián", "Natalia", "Rubén", "Sara",
    "Enrique", "Irene", "Guillermo", "Claudia", "Marcos", "Eva", "Hugo",
]

_APELLIDOS1 = [
    "García", "Martínez", "López", "Rodríguez", "Jiménez", "Fernández", "Gómez",
    "Sánchez", "Pérez", "Díaz", "Moreno", "Muñoz", "Álvarez", "Romero", "Torres",
    "Navarro", "Domínguez", "Vázquez", "Ramos", "Gil", "Serrano", "Blanco",
    "Molina", "Morales", "Suárez", "Ortega",
]

_APELLIDOS2 = [
    "Ruiz", "Hernández", "Castro", "Vargas", "Medina", "Herrera", "Delgado",
    "Peña", "Cruz", "Flores", "Reyes", "Aguilar", "León", "Campos", "Vega",
    "Prieto", "Fuentes", "Cabrera", "Calvo", "Méndez",
]

random.seed(42)  # reproducibilidad

def _gen_polizas(n=50):
    polizas = []
    used_names = set()
    for i in range(1, n + 1):
        numero = f"POL-{i:03d}"
        ramo = random.choice(_RAMOS)
        # Fecha alta entre 2016 y 2024
        start = date(2016, 1, 1)
        delta = (date(2024, 12, 31) - start).days
        fecha_alta = start + timedelta(days=random.randint(0, delta))
        rentab = random.choice(_RENTAB)
        # Nombre único
        while True:
            nombre = f"{random.choice(_NOMBRES)} {random.choice(_APELLIDOS1)} {random.choice(_APELLIDOS2)}"
            if nombre not in used_names:
                used_names.add(nombre)
                break
        cp = random.choice(_CPS)
        edad = random.randint(22, 78)
        siniest = random.choice(_SINIEST)
        canal = random.choice(_CANALES)
        reincidencia = random.choices([0, 1, 2, 3], weights=[60, 25, 10, 5])[0]
        vinculacion = random.choice(_VINCUL)
        polizas.append((numero, ramo, fecha_alta.isoformat(), rentab, nombre, cp, edad, siniest, canal, reincidencia, vinculacion))
    return polizas

POLIZAS_MOCK = _gen_polizas(50)

# ── Datos mock: ontología de reglas ──────────────────────────────────────────

ONTOLOGIA_REGLAS = """
# Ontología de Reglas de Retención — v1.0

Eres un experto en retención de clientes de una aseguradora.
A continuación se definen los argumentos y contra-argumentos por motivo de baja.

---

## CÓMO ELEGIR Y PRESENTAR ARGUMENTOS

### Según la rentabilidad de la póliza
- **Alta rentabilidad:** prioriza argumentos de valor diferencial y ofrece condiciones especiales (descuentos, beneficios adicionales). Este cliente merece un esfuerzo máximo de retención.
- **Rentabilidad media:** enfócate en coberturas, continuidad y el riesgo de perder beneficios acumulados.
- **Rentabilidad baja:** sé honesto con el ejecutivo sobre el margen real para hacer concesiones. No ofrezcas descuentos que no estén respaldados.

### Cómo avanzar en la conversación
- Presenta **un solo argumento por turno**. Espera la reacción del cliente antes de continuar.
- Si el cliente muestra apertura: refuerza el argumento actual con más detalle.
- Si el cliente objeta: elige el **siguiente mejor argumento** disponible en esta ontología. Nunca repitas uno que el cliente ya rechazó.
- Avanza gradualmente, argumento a argumento, siguiendo el hilo de la conversación.

---

## MOTIVO: Precio / Prima muy cara

**Argumento principal:**
El precio de la póliza refleja la cobertura real que el cliente tiene. Comparado con el mercado,
nuestra prima incluye asistencia 24hs, sin franquicia en siniestros menores, y atención personalizada.

**Si el cliente insiste en el precio:**
- Ofrecer revisión de coberturas para ajustar la prima sin perder lo esencial.
- Recordar que cambiar de aseguradora implica período de carencia (sin cobertura durante X días).
- Preguntar si tiene algún siniestro en curso — cambiarse lo dejaría sin respaldo.

**Si el cliente menciona una oferta de la competencia:**
- Pedir que muestre la oferta. Generalmente tienen letra chica: franquicias altas, límites bajos.
- Ofrecer igualar o mejorar si la oferta es verificable.

---

## MOTIVO: No usa la póliza / No la necesita

**Argumento principal:**
El seguro no se paga por usarlo, se paga para estar cubierto cuando ocurre lo inesperado.
El cliente lleva X años sin siniestros, lo que muestra que es un cliente valioso para nosotros.

**Si el cliente dice que es un gasto innecesario:**
- Reformular el valor: no es un gasto, es tranquilidad.
- Mencionar casos frecuentes del ramo (robo de auto, incendio en hogar, hospitalización).
- Recordar que la antigüedad del cliente le da beneficios acumulados que perdería al cancelar.

---

## MOTIVO: Mala experiencia / Mal servicio

**Argumento principal:**
Lamentamos genuinamente la experiencia. Escuchar activamente qué falló es el primer paso.

**Pasos a seguir:**
1. Pedir disculpas concretas por lo ocurrido.
2. Escalar internamente si el problema no fue resuelto.
3. Ofrecer una compensación simbólica (descuento en próxima cuota, asistencia gratuita).
4. Comprometerse con seguimiento personalizado.

**Si el cliente ya escaló y no obtuvo respuesta:**
- No minimizar. Reconocer la falla del proceso.
- Ofrecer hablar directamente con el supervisor.

---

## MOTIVO: Situación económica / No puede pagar

**Argumento principal:**
Entendemos las dificultades. Tenemos opciones para que el cliente no quede desprotegido.

**Opciones a ofrecer:**
- Plan de pago en cuotas sin interés.
- Reducción temporal de cobertura a lo esencial (póliza básica).
- Suspensión temporal de la póliza por 1-3 meses (según producto).

**Si el cliente aun así decide cancelar:**
- Informar que puede reactivar sin nuevo período de carencia si lo hace dentro de 90 días.

---

## NOTAS GENERALES PARA EL EJECUTIVO

- Siempre personalizar el argumento con los datos reales de la póliza (ramo, antigüedad, rentabilidad).
- Un cliente de alta rentabilidad merece una oferta especial — consultarlo con el supervisor.
- No presionar. Si el cliente está decidido, cerrar con una buena experiencia para dejar la puerta abierta.
- Registrar el motivo de baja real aunque no se logre la retención.
"""

# ── Ontología de Diferenciadores ─────────────────────────────────────────────

ONTOLOGIA_DIFERENCIADORES = """
# Ontología de Diferenciadores Competitivos — Seguros Mundial v1.0

Esta ontología contiene las ventajas de Seguros Mundial frente a los principales competidores
por ramo. Úsala SOLO cuando el cliente mencione explícitamente a un competidor.
No la uses para iniciar la conversación — es un recurso de apoyo ante objeciones comparativas.

---

## RAMO: VIDA

### Seguros Mundial vs Sura
- Seguros Mundial ofrece revisión médica simplificada para capitales de hasta COL$634.200.000, mientras Sura la exige desde COL$422.800.000.
- El servicio de orientación médica telefónica de Seguros Mundial está disponible 24h sin coste adicional; en Sura tiene franquicia de uso.
- Seguros Mundial incluye cobertura de enfermedades graves (cáncer, infarto, ACV) desde el primer año sin período de carencia adicional.
- La atención al beneficiario en caso de siniestro es gestionada por un gestor personal dedicado; Sura lo canaliza por call center general.

### Seguros Mundial vs Reale
- Seguros Mundial tiene una red de mediadores especializados en vida con formación certificada; Reale combina canal directo y mediación sin especialización específica.
- La póliza de vida de Seguros Mundial permite modificar el capital asegurado anualmente sin nuevo proceso de suscripción, algo que Reale no permite.
- Seguros Mundial cubre fallecimiento por cualquier causa desde el primer día; Reale aplica carencia de 6 meses para enfermedades preexistentes no declaradas.

### Seguros Mundial vs Mutua Madrileña
- Seguros Mundial es especialista en seguros de vida y decesos con más de 90 años de historia; Mutua es principalmente una aseguradora de auto que diversificó.
- El capital mínimo asegurado en vida de Seguros Mundial es más flexible (desde COL$63.420.000); Mutua exige mínimos más altos para sus productos de vida.
- Seguros Mundial ofrece un plan de ahorro complementario vinculable a la póliza de vida; Mutua no dispone de este producto combinado.

---

## RAMO: AUTO

### Seguros Mundial vs Sura
- Seguros Mundial incluye vehículo de sustitución desde el primer día en talleres concertados; Sura lo ofrece solo a partir de reparaciones superiores a 48h.
- La asistencia en carretera de Seguros Mundial cubre remolque ilimitado en kilómetros; Sura limita a 500 km en su póliza estándar.
- Seguros Mundial no aplica franquicia en el primer siniestro del año para clientes con más de 2 años de antigüedad; Sura la aplica siempre.
- El proceso de peritación de Seguros Mundial garantiza resolución en 72h; Sura puede tardar hasta 7 días hábiles.

### Seguros Mundial vs Reale
- Seguros Mundial dispone de red propia de talleres con garantía de reparación de por vida; Reale trabaja con talleres externos sin garantía extendida.
- El seguro de auto de Seguros Mundial incluye cobertura de accesorios y equipamiento especial hasta COL$12.684.000 sin coste adicional; Reale lo excluye de la cobertura básica.
- Seguros Mundial ofrece descuento familiar acumulable del 15% al asegurar dos o más vehículos; Reale aplica un descuento máximo del 8%.

### Seguros Mundial vs Mutua Madrileña
- Seguros Mundial tiene presencia nacional con atención presencial en más de 4.000 puntos; Mutua concentra su red principalmente en Madrid y grandes ciudades.
- La app de Seguros Mundial permite declarar un siniestro con fotos en menos de 3 minutos y recibir confirmación inmediata; la app de Mutua no tiene esta funcionalidad.
- Seguros Mundial permite contratar a conductores noveles (menos de 2 años de carnet) con recargo menor que Mutua para el mismo perfil de riesgo.

---

## RAMO: HOGAR

### Seguros Mundial vs Sura
- Seguros Mundial cubre daños por agua (tuberías, filtraciones) sin límite de antigüedad de la instalación; Sura excluye instalaciones con más de 20 años.
- El servicio de hogar de Seguros Mundial incluye hasta 4 visitas anuales de mantenimiento preventivo; Sura solo cubre reparaciones correctivas.
- Seguros Mundial cubre robo fuera del hogar (en vehículo, en vacaciones) hasta COL$12.684.000; Sura lo excluye en la modalidad estándar.
- La cobertura de responsabilidad civil del hogar de Seguros Mundial alcanza COL$1.268.400.000; Sura estándar cubre hasta COL$634.200.000.

### Seguros Mundial vs Reale
- Seguros Mundial no aplica depreciación por antigüedad en electrodomésticos (valor de reposición a nuevo); Reale aplica depreciación desde el tercer año.
- El servicio de emergencias de Seguros Mundial tiene tiempo de respuesta garantizado de 2h; Reale no garantiza tiempo máximo de respuesta.
- Seguros Mundial cubre daños estéticos (manchas, arañazos en parquet) que Reale excluye expresamente de su póliza de hogar básica.

### Seguros Mundial vs Mutua Madrileña
- Seguros Mundial incluye cobertura de placas solares y equipos de aerotermia como parte del continente sin coste adicional; Mutua los excluye o cobra suplemento.
- El capital de contenido mínimo de Seguros Mundial es más adaptable al perfil real del cliente; Mutua aplica capitales mínimos más elevados que no siempre se ajustan a la realidad.
- Seguros Mundial ofrece extensión de cobertura a segunda residencia con el 30% de prima adicional; Mutua requiere una póliza independiente.

---

## RAMO: SALUD

### Seguros Mundial vs Sura
- Seguros Mundial tiene acuerdo con más de 40.000 especialistas en toda España; Sura Salud cuenta con 35.000, con menor presencia en zonas rurales.
- Seguros Mundial no aplica períodos de carencia para urgencias desde el primer día; Sura aplica 30 días de carencia para algunas especialidades.
- La teleconsulta de Seguros Mundial está disponible 24h con médico generalista y especialista; Sura solo garantiza generalista en horario nocturno.
- Seguros Mundial cubre segunda opinión médica internacional sin coste adicional; Sura lo ofrece como suplemento de pago.

### Seguros Mundial vs Reale
- Seguros Mundial incluye salud mental (psicólogo, psiquiatra) desde la póliza básica; Reale lo ofrece solo en modalidades premium con coste adicional.
- La cobertura dental de Seguros Mundial incluye una limpieza anual gratuita y descuentos del 30% en tratamientos; Reale ofrece solo descuentos del 15%.
- Seguros Mundial no tiene límite de consultas anuales por especialidad; Reale limita algunas especialidades a 6 visitas anuales.

### Seguros Mundial vs Mutua Madrileña
- Seguros Mundial tiene cobertura nacional homogénea; Mutua tiene mayor concentración de cuadro médico en Madrid con cobertura más limitada en otras comunidades.
- Seguros Mundial permite añadir a familiares directos con condiciones preferenciales sin nuevo proceso médico; Mutua requiere cuestionario de salud individual para cada incorporación.
- El copago de Seguros Mundial en modalidad con copago es fijo (COL$12.684 por consulta); Mutua aplica copagos variables según especialidad que pueden llegar a COL$63.420.

---

## NOTAS PARA EL EJECUTIVO

- Usa estos diferenciadores SOLO si el cliente menciona un competidor concreto. No los ofrezcas de forma proactiva.
- Si el cliente compara precio, primero usa los argumentos de la ontología de reglas. Los diferenciadores son el segundo nivel de argumentación.
- No leas la lista completa al cliente. Elige el diferenciador más relevante para su ramo y situación específica.
- Si el cliente menciona un competidor que no está en esta ontología, sé honesto: indica que no tienes información sobre esa compañía en este momento.
"""

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un asistente experto en retención de clientes para ejecutivos de contact center de una aseguradora.

## Tu flujo de trabajo

1. **Saluda** al ejecutivo e inmediatamente pídele el número de póliza del cliente que quiere darse de baja.
2. **Busca la póliza** usando la tool `buscar_poliza`. Si no existe, informa al ejecutivo y vuelve a pedir el número.
3. **Presenta un resumen** de la póliza encontrada (nombre del cliente, ramo, antigüedad, rentabilidad, siniestralidad) para que el ejecutivo tenga contexto.
4. **Pregunta el motivo de baja** que el cliente está manifestando.
5. **Consulta la ontología de reglas** usando la tool `ontologia_reglas` para obtener los argumentos de retención disponibles.
6. **Elige UN solo argumento** — el que consideres más fuerte dado el perfil de la póliza y el motivo de baja — y sugiere solo ese al ejecutivo. Sigue las instrucciones de la ontología para elegir y avanzar según la reacción del cliente.
7. **Si el cliente menciona explícitamente un competidor** (Sura, Reale, Mutua u otro), usa la tool `ontologia_diferenciadores` para obtener las ventajas de Seguros Mundial frente a ese competidor en el ramo correspondiente. Elige solo el diferenciador más relevante y preséntalo con el mismo formato de argumento.
8. **Acompaña al ejecutivo** hasta que la situación se resuelva (retención lograda o baja confirmada).

## Formato de los argumentos — OBLIGATORIO

Cuando sugieras un argumento al ejecutivo, preséntalo siempre así:

**Plantea al cliente esto:**
"[argumento en primera persona, como si el ejecutivo le hablara directamente al cliente]"

Luego, en una línea aparte, puedes agregar una breve nota táctica para el ejecutivo (por qué ese argumento, qué observar en la reacción del cliente). Esa nota NO va entre comillas.

## Reglas de argumentación — OBLIGATORIAS

- **PROHIBIDO inventar argumentos.** Solo puedes usar argumentos que estén explícitamente en la ontología devuelta por `ontologia_reglas`. Si un argumento no está en la ontología, no existe.
- **PROHIBIDO inventar diferenciadores competitivos.** Solo puedes usar ventajas que estén explícitamente en la ontología devuelta por `ontologia_diferenciadores`. Si no está, no lo menciones.
- **PROHIBIDO dar varios argumentos a la vez.** Uno por turno. La conversación debe fluir naturalmente.
- **PROHIBIDO repetir un argumento** que el cliente ya rechazó en esta misma conversación.
- Si la ontología no contiene argumentos para la situación específica, díselo honestamente al ejecutivo en lugar de improvisar.

## Documentos adjuntos

El ejecutivo puede adjuntar documentos (PDFs, imágenes) al chat. Cuando lo haga, recibirás un mensaje que comienza con:

`[Documento adjunto analizado: <nombre_archivo>]`

seguido del análisis completo del documento realizado por un sistema externo. En ese caso:

- **Usa directamente esa información** — no digas que no puedes analizar imágenes ni documentos.
- Identifica el tipo de documento (póliza, oferta de competidor, queja, otro).
- Si es una **oferta de un competidor**: úsala para reforzar los argumentos de retención y consulta `ontologia_diferenciadores` si el competidor está mencionado.
- Si es una **póliza del cliente**: extrae los datos relevantes para contextualizar la conversación.
- Si es una **queja**: reconócela y usa `ontologia_reglas` para el motivo "Mala experiencia".
- Presenta al ejecutivo un resumen breve del documento y sugiere los pasos a seguir.

## Perfil del cliente — cómo usarlo en el argumentario

Cuando `buscar_poliza` devuelva los datos del cliente, tenlos en cuenta así:

- **Nombre del cliente**: personaliza el discurso del ejecutivo (ej: "María lleva 7 años con nosotros..."). No te dirijas al cliente por su nombre directamente — recuerda que hablas con el ejecutivo.
- **Edad**: adapta el argumentario al perfil de vida del cliente:
  - Clientes jóvenes (< 35 años): valoran flexibilidad, precio y tecnología.
  - Clientes de mediana edad (35–55 años): valoran estabilidad, historial acumulado y cobertura familiar.
  - Clientes mayores (> 55 años): valoran continuidad, atención personalizada y tranquilidad.
- **CP (código postal)**: úsalo para contextualizar servicios regionales si son relevantes (red de talleres, especialistas médicos, cobertura local).
- **Siniestralidad**: es información interna para el ejecutivo — no la menciones directamente al cliente:
  - **Baja**: cliente muy rentable. Máximo esfuerzo de retención. Puedes recomendar ofrecer condiciones especiales (descuentos, beneficios por fidelidad).
  - **Media**: argumentario estándar de valor y continuidad.
  - **Alta**: sé cauteloso con concesiones económicas. Enfócate en el valor de la cobertura, no en descuentos. Informa al ejecutivo de forma discreta si el margen es limitado.

## Reglas generales

- Habla siempre en español, de forma profesional pero cercana.
- Nunca inventes datos de la póliza — usa solo lo que devuelve `buscar_poliza`.
- Recuerda que tu usuario es el **ejecutivo**, no el cliente final.
- Si el cliente finalmente decide darse de baja, ayuda al ejecutivo a cerrar con una buena experiencia.
"""

# ── Ejecución ────────────────────────────────────────────────────────────────

def setup():
    print("Conectando a MySQL...")
    conn = mysql.connector.connect(**DB_CONFIG)
    cur  = conn.cursor()

    print("Creando tabla polizas...")
    cur.execute(CREATE_POLIZAS)

    print("Creando tabla ontologias...")
    cur.execute(CREATE_ONTOLOGIAS)

    print("Añadiendo columnas nuevas si no existen...")
    for col_def in [
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS cliente         VARCHAR(100)",
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS cp              VARCHAR(10)",
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS edad            INT",
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS siniestralidad  VARCHAR(10)",
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS canal_mediador  VARCHAR(50)",
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS reincidencia    INT DEFAULT 0",
        "ALTER TABLE polizas ADD COLUMN IF NOT EXISTS vinculacion     VARCHAR(20)",
    ]:
        cur.execute(col_def)

    print("Insertando/actualizando pólizas mock...")
    for pol in POLIZAS_MOCK:
        cur.execute("""
            INSERT INTO polizas (numero_poliza, ramo, fecha_alta, rentabilidad,
                                 cliente, cp, edad, siniestralidad,
                                 canal_mediador, reincidencia, vinculacion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                ramo           = VALUES(ramo),
                fecha_alta     = VALUES(fecha_alta),
                rentabilidad   = VALUES(rentabilidad),
                cliente        = VALUES(cliente),
                cp             = VALUES(cp),
                edad           = VALUES(edad),
                siniestralidad = VALUES(siniestralidad),
                canal_mediador = VALUES(canal_mediador),
                reincidencia   = VALUES(reincidencia),
                vinculacion    = VALUES(vinculacion)
        """, pol)

    print("Insertando/actualizando ontologia-reglas...")
    cur.execute("""
        INSERT INTO ontologias (nombre, version, contenido, activo)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE contenido = VALUES(contenido), activo = VALUES(activo)
    """, ("ontologia-reglas", "1.0", ONTOLOGIA_REGLAS, 1))

    print("Insertando/actualizando ontologia-diferenciadores...")
    cur.execute("""
        INSERT INTO ontologias (nombre, version, contenido, activo)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE contenido = VALUES(contenido), activo = VALUES(activo)
    """, ("ontologia-diferenciadores", "1.0", ONTOLOGIA_DIFERENCIADORES, 1))

    print("Insertando/actualizando system-prompt...")
    cur.execute("""
        INSERT INTO ontologias (nombre, version, contenido, activo)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE contenido = VALUES(contenido), activo = VALUES(activo)
    """, ("system-prompt", "1.0", SYSTEM_PROMPT, 1))

    conn.commit()
    cur.close()
    conn.close()
    print("Setup completado.")

if __name__ == "__main__":
    setup()
