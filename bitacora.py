#!/usr/bin/env python3
"""
Bitácora del Empalme · Colombia 2026
Monitorea la transición presidencial: gabinete, apoyos y entrega del poder.
Genera un resumen diario y lo envía por email.
"""

import os
import sys
import json
import datetime
import urllib.request
import urllib.error
import html
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Zona horaria Colombia ─────────────────────────────────────────────────────
COLOMBIA_TZ = datetime.timezone(datetime.timedelta(hours=-5))

# ── Paleta bandera Colombia ───────────────────────────────────────────────────
C_AMARILLO  = "#FCD116"
C_AZUL      = "#003087"
C_ROJO      = "#CE1126"
C_AZUL_OSC  = "#001a4d"

# ── Configuración ─────────────────────────────────────────────────────────────
SCRIPT_DIR      = Path(__file__).parent
OUTPUT_HTML     = SCRIPT_DIR / "bitacora.html"
LOG_FILE        = SCRIPT_DIR / "bitacora.log"
DESTINATARIOS_F = SCRIPT_DIR / "destinatarios.txt"
CONFIG_F        = SCRIPT_DIR / "config.txt"
MEMORIA_F       = SCRIPT_DIR / "memoria.json"

EMAIL_REMITENTE = "juandanielserrano@gmail.com"
EMAIL_NOMBRE    = "Bitácora del Empalme"

POSESION = datetime.date(2026, 8, 7)

MEDIOS = [
    ("El Tiempo",        "https://www.eltiempo.com/politica"),
    ("El Espectador",    "https://www.elespectador.com/politica"),
    ("La Silla Vacía",   "https://lasillavacia.com"),
    ("Caracol Noticias", "https://noticias.caracoltv.com/colombia/politica"),
    ("La FM",            "https://www.lafm.com.co/politica"),
    ("El Colombiano",    "https://www.elcolombiano.com/colombia/politica"),
    ("Dos Orillas",      "https://www.dosrillas.com"),
    ("Cuestión Pública", "https://cuestionpublica.com/categoria/politica/"),
    ("W Radio",          "https://www.wradio.com.co/noticias/"),
    ("Blu Radio",        "https://www.bluradio.com/nacion"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MODEL           = "claude-sonnet-4-5"
MAX_TOKENS      = 3500
TEXTO_POR_MEDIO = 1500

# Carteras base del gabinete — persisten en memoria.json entre ejecuciones
CARTERAS_BASE = {
    "Interior":        {"sector": "Político-institucional", "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Cancillería":     {"sector": "Político-institucional", "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Defensa":         {"sector": "Político-institucional", "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Justicia":        {"sector": "Político-institucional", "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Hacienda":        {"sector": "Económico",              "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "DNP":             {"sector": "Económico",              "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Comercio":        {"sector": "Económico",              "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Minas y Energía": {"sector": "Económico",              "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Salud":           {"sector": "Social",                 "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Educación":       {"sector": "Social",                 "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Trabajo":         {"sector": "Social",                 "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
    "Ambiente":        {"sector": "Social",                 "nombre_principal": "", "nombre_alternativo": "", "estado": "vacante", "fuente": ""},
}

SECTORES_ORDEN = ["Político-institucional", "Económico", "Social", "Otros"]


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.datetime.now(tz=COLOMBIA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Configuración desde archivo ───────────────────────────────────────────────

def leer_config() -> dict:
    """Lee config.txt. Las variables de entorno tienen prioridad si existen."""
    config = {"MODO": "produccion", "EMAIL_ADMIN": "juandanielserrano@gmail.com"}
    if CONFIG_F.exists():
        for linea in CONFIG_F.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                config[clave.strip()] = valor.strip()
    return config


# ── Destinatarios ─────────────────────────────────────────────────────────────

def leer_destinatarios() -> list:
    cfg         = leer_config()
    modo        = os.environ.get("MODO", cfg.get("MODO", "produccion")).strip().lower()
    email_admin = os.environ.get("EMAIL_ADMIN", cfg.get("EMAIL_ADMIN", "juandanielserrano@gmail.com")).strip()

    if modo == "pruebas":
        log(f"MODO PRUEBAS — enviando solo a {email_admin}")
        return [email_admin]

    env_dest = os.environ.get("DESTINATARIOS", "").strip()
    if env_dest:
        correos = [c.strip() for c in env_dest.split(",") if c.strip()]
        log(f"MODO PRODUCCIÓN — {len(correos)} destinatario(s) desde variable de entorno")
        return correos

    if not DESTINATARIOS_F.exists():
        log(f"AVISO: No se encontró {DESTINATARIOS_F} ni variable DESTINATARIOS. Enviando solo a admin.")
        return [email_admin]

    correos = []
    for linea in DESTINATARIOS_F.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            correos.append(linea)
    log(f"MODO PRODUCCIÓN — {len(correos)} destinatario(s) desde archivo")
    return correos


# ── Scraping ──────────────────────────────────────────────────────────────────

def fetch_texto(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        raw = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>.*?</style>",   " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)
        # Extraer enlaces antes de limpiar tags
        links = re.findall(
            r'<a[^>]+href=["\']([^"\'#][^"\']*)["\'][^>]*>([^<]{15,})</a>',
            raw, flags=re.IGNORECASE
        )
        raw = re.sub(r"</?(p|br|h[1-6]|li|div|article|section)[^>]*>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = html.unescape(raw)
        lines = [l.strip() for l in raw.splitlines() if len(l.strip()) > 40]
        texto = "\n".join(lines)[:TEXTO_POR_MEDIO]
        if links:
            validos = [(u, t.strip()) for u, t in links if "javascript" not in u and len(t.strip()) > 10][:10]
            if validos:
                texto += "\nENLACES DISPONIBLES:\n" + "\n".join(f"{t} → {u}" for u, t in validos)
        return texto
    except Exception as e:
        return f"[Error al cargar {url}: {e}]"


def recopilar_medios() -> str:
    log("Recopilando medios...")
    partes = []
    for nombre, url in MEDIOS:
        log(f"  → {nombre}")
        texto = fetch_texto(url)
        partes.append(f"=== {nombre} ({url}) ===\n{texto}\n")
    return "\n".join(partes)


# ── Memoria y gabinete ────────────────────────────────────────────────────────

def cargar_memoria() -> tuple:
    """Retorna (resumen_texto, gabinete_dict)."""
    if not MEMORIA_F.exists():
        return "", {}
    try:
        data = json.loads(MEMORIA_F.read_text(encoding="utf-8"))
        return data.get("resumen", ""), data.get("gabinete", {})
    except Exception:
        return "", {}


def actualizar_gabinete(gabinete_actual: dict, updates: dict) -> dict:
    """Fusiona las actualizaciones del modelo con el estado persistido."""
    # Garantizar que todas las carteras base existen
    for cartera, base in CARTERAS_BASE.items():
        if cartera not in gabinete_actual:
            gabinete_actual[cartera] = base.copy()
    # Aplicar deltas del modelo
    for cartera, datos in updates.items():
        if cartera in gabinete_actual:
            for k, v in datos.items():
                if v:  # Solo sobreescribir si el modelo trae valor
                    gabinete_actual[cartera][k] = v
        else:
            # Cartera no predefinida (agencias, superintendencias, etc.)
            gabinete_actual[cartera] = {
                "sector": "Otros",
                "nombre_principal":   datos.get("nombre_principal", ""),
                "nombre_alternativo": datos.get("nombre_alternativo", ""),
                "estado":             datos.get("estado", "vacante"),
                "fuente":             datos.get("fuente", ""),
            }
    return gabinete_actual


def guardar_memoria(briefing: dict, gabinete: dict):
    titulares = [
        it.get("titular", "").strip()
        for it in briefing.get("noticias", [])
        if it.get("titular")
    ]
    data = {
        "fecha":           briefing.get("fecha", ""),
        "hora":            briefing.get("hora", ""),
        "titular_del_dia": briefing.get("titular_del_dia", ""),
        "resumen":         briefing.get("editorial", ""),
        "titulares":       titulares[:10],
        "gabinete":        gabinete,
    }
    MEMORIA_F.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Llamada a la API ──────────────────────────────────────────────────────────

def llamar_api(contexto: str, api_key: str, gabinete_actual: dict) -> dict:
    ahora = datetime.datetime.now(tz=COLOMBIA_TZ)
    dias  = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"][ahora.weekday()]
    meses = ["","enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_str     = f"{dias} {ahora.day} de {meses[ahora.month]} de {ahora.year}"
    hora_str      = ahora.strftime("%H:%M")
    dias_posesion = (POSESION - ahora.date()).days

    resumen_anterior, _ = cargar_memoria()
    bloque_memoria = ""
    if resumen_anterior:
        bloque_memoria = (
            "\nCONTEXTO DEL ÚLTIMO BRIEFING:\n"
            + resumen_anterior
            + "\n\nEnfócate en lo NUEVO o CAMBIADO desde esa entrega. No repitas hechos ya cubiertos.\n"
        )

    gabinete_json = json.dumps(gabinete_actual, ensure_ascii=False, indent=2)

    prompt = (
        f"Eres un analista político colombiano senior especializado en transiciones de poder. "
        f"Estilo Financial Times: directo, preciso, sin adjetivos innecesarios, con visión de hacia dónde van los hechos. "
        f"Hoy es {fecha_str}, {hora_str} (hora Colombia). "
        f"Faltan {dias_posesion} días para la posesión presidencial el 7 de agosto de 2026.\n"
        f"{bloque_memoria}\n"
        f"ESTADO ACTUAL DEL GABINETE (persiste entre ediciones):\n"
        f"{gabinete_json}\n\n"
        f"A continuación tienes el contenido extraído de los principales medios colombianos:\n\n"
        f"{contexto}\n\n"
        f"Contexto de la elección:\n"
        f"- Abelardo de la Espriella (Defensores de la Patria, derecha) ganó la segunda vuelta del 21 de junio de 2026.\n"
        f"- Iván Cepeda Castro (Pacto Histórico) perdió. El gobierno Petro está en transición.\n"
        f"- La Registraduría aún no ha certificado formalmente el resultado "
        f"(actualiza este dato si los medios lo confirman o desmienten).\n\n"
        f"Genera una Bitácora del Empalme ejecutiva. Prioridades editoriales en orden:\n"
        f"1. Conformación del gabinete: quiénes suenan, quiénes se confirmaron, perfiles breves.\n"
        f"2. Apoyos políticos y alianzas que está construyendo De la Espriella.\n"
        f"3. Anuncios de política pública del presidente electo.\n"
        f"4. Estado de la transición: empalme formal, actitud del gobierno Petro, certificación electoral.\n\n"
        f"Para el campo 'editorial': síntesis analítica más, cuando haya nombres nuevos relevantes para el gabinete, "
        f"un perfil breve de 1-2 líneas por persona (quién es, de dónde viene, por qué importa para ese cargo). "
        f"Máximo 180 palabras en total.\n\n"
        f"Responde ÚNICAMENTE con un objeto JSON válido. Sin texto adicional, sin backticks, sin markdown.\n\n"
        f'{{\n'
        f'  "fecha": "{fecha_str}",\n'
        f'  "hora": "{hora_str}",\n'
        f'  "titular_del_dia": "Una frase corta que capture el hecho más relevante del momento",\n'
        f'  "editorial": "Síntesis analítica con perfiles breves cuando aplique. Prosa fluida. Máximo 180 palabras.",\n'
        f'  "empalme": {{\n'
        f'    "gabinete": "avanzando|parcial|pendiente",\n'
        f'    "reconocimiento": "completo|en_proceso|pendiente",\n'
        f'    "nota": "Una línea sobre la dinámica de la transición en este momento"\n'
        f'  }},\n'
        f'  "gabinete_update": {{\n'
        f'    "NombreCartera": {{\n'
        f'      "nombre_principal": "Nombre Apellido o cadena vacía",\n'
        f'      "nombre_alternativo": "Otro nombre que suena o cadena vacía",\n'
        f'      "estado": "confirmado|suena|vacante",\n'
        f'      "fuente": "Nombre del medio"\n'
        f'    }}\n'
        f'  }},\n'
        f'  "noticias": [\n'
        f'    {{\n'
        f'      "titular": "Titular preciso del hecho nuevo",\n'
        f'      "contexto": "1-2 frases: qué cambió o evolucionó. Solo lo nuevo.",\n'
        f'      "fuente": "Nombre del medio",\n'
        f'      "url": ""\n'
        f'    }}\n'
        f'  ],\n'
        f'  "para_estar_atento": "1-2 frases sobre qué viene en las próximas horas o días"\n'
        f'}}\n\n'
        f"Reglas:\n"
        f"- 'gabinete_update' solo incluye carteras con información NUEVA. Puede ser {{}} si no hay nada nuevo.\n"
        f"- Usa los nombres de cartera exactamente como están en el estado actual del gabinete.\n"
        f"- Máximo 6 noticias. Sin repetir lo ya cubierto.\n"
        f"- No inventes hechos ni nombres. Si no hay información, deja los campos en cadena vacía.\n"
    )

    payload = json.dumps({
        "model":      MODEL,
        "max_tokens": MAX_TOKENS,
        "messages":   [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))

    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(text)


# ── Helpers de renderizado ────────────────────────────────────────────────────

def _stats_gabinete(gabinete: dict) -> tuple:
    """Devuelve (confirmados, suenan, vacantes) contando el gabinete actual."""
    confirmados = sum(1 for d in gabinete.values() if d.get("estado") == "confirmado")
    suenan      = sum(1 for d in gabinete.values() if d.get("estado") == "suena")
    vacantes    = sum(1 for d in gabinete.values() if d.get("estado") == "vacante")
    return confirmados, suenan, vacantes

def _chip_empalme_css(campo: str, val: str) -> str:
    """Chips del panel de empalme — versión con clases CSS para HTML web."""
    if campo == "gabinete":
        if val == "avanzando":
            return '<span class="chip chip-verde">Avanzando</span>'
        if val == "parcial":
            return '<span class="chip chip-amarillo">Parcial</span>'
        return '<span class="chip chip-gris">Pendiente</span>'
    else:  # reconocimiento
        if val == "completo":
            return '<span class="chip chip-azul">Completo</span>'
        if val == "en_proceso":
            return '<span class="chip chip-amarillo">En proceso</span>'
        return '<span class="chip chip-rojo">Pendiente</span>'


def _chip_empalme_inline(campo: str, val: str) -> str:
    """Chips del panel de empalme — versión inline para email."""
    base = "font-size:9px;padding:2px 8px;font-weight:bold;font-family:Helvetica,Arial,sans-serif;"
    if campo == "gabinete":
        if val == "avanzando":
            return f'<span style="{base}background:#2D6A1F;color:#fff">Avanzando</span>'
        if val == "parcial":
            return f'<span style="{base}background:{C_AMARILLO};color:#7a5c00">Parcial</span>'
        return f'<span style="{base}background:#888;color:#fff">Pendiente</span>'
    else:
        if val == "completo":
            return f'<span style="{base}background:{C_AZUL};color:#fff">Completo</span>'
        if val == "en_proceso":
            return f'<span style="{base}background:{C_AMARILLO};color:#7a5c00">En proceso</span>'
        return f'<span style="{base}background:{C_ROJO};color:#fff">Pendiente</span>'


def _chip_gabinete_inline(estado: str) -> str:
    base = "font-size:9px;padding:2px 8px;font-weight:bold;font-family:Helvetica,Arial,sans-serif;"
    if estado == "confirmado":
        return f'<span style="{base}background:{C_AZUL};color:#fff">Confirmado</span>'
    if estado == "suena":
        return f'<span style="{base}background:{C_AMARILLO};color:#7a5c00">Suena</span>'
    return f'<span style="{base}background:#888;color:#fff">Vacante</span>'


def _render_gabinete_web(gabinete: dict) -> str:
    """Tabla de gabinete para el HTML web (usa clases CSS)."""
    if not gabinete:
        return ""

    sectores: dict[str, list] = {}
    for cartera, data in gabinete.items():
        s = data.get("sector", "Otros")
        sectores.setdefault(s, []).append((cartera, data))

    filas = ""
    for sector in SECTORES_ORDEN:
        if sector not in sectores:
            continue
        filas += f'<tr><td colspan="4" class="gb-sector">{html.escape(sector)}</td></tr>'
        for cartera, data in sectores[sector]:
            np  = html.escape(data.get("nombre_principal", "") or "—")
            na  = data.get("nombre_alternativo", "")
            est = data.get("estado", "vacante")
            fue = html.escape(data.get("fuente", ""))
            na_html = ""
            if na:
                na_html = f'<br><span class="gb-nombre-alt">También: {html.escape(na)}</span>'
            if est == "confirmado":
                chip = '<span class="chip chip-azul">Confirmado</span>'
            elif est == "suena":
                chip = '<span class="chip chip-amarillo">Suena</span>'
            else:
                chip = '<span class="chip chip-gris">Vacante</span>'
            filas += (
                f'<tr>'
                f'<td class="gb-cartera">{html.escape(cartera)}</td>'
                f'<td class="gb-nombre">{np}{na_html}</td>'
                f'<td style="text-align:center">{chip}</td>'
                f'<td class="gb-fuente">{fue}</td>'
                f'</tr>'
            )

    return f"""
    <div class="gb-wrapper">
      <div class="sec-lbl"><span class="sec-line"></span>Conformación del gabinete</div>
      <table class="gb">
        <thead>
          <tr>
            <th style="width:26%">Cartera</th>
            <th style="width:40%">Nombre(s)</th>
            <th style="width:16%;text-align:center">Estado</th>
            <th style="width:18%;text-align:right">Fuente</th>
          </tr>
        </thead>
        <tbody>{filas}</tbody>
      </table>
      <div class="gb-leyenda">
        <div class="gb-ley-item"><span class="chip chip-azul">Confirmado</span> Oficial</div>
        <div class="gb-ley-item"><span class="chip chip-amarillo">Suena</span> En medios</div>
        <div class="gb-ley-item"><span class="chip chip-gris">Vacante</span> Sin info</div>
      </div>
    </div>"""


def _render_gabinete_email(gabinete: dict) -> str:
    """Tabla de gabinete para email (estilos inline, compatible Gmail)."""
    if not gabinete:
        return ""

    sectores: dict[str, list] = {}
    for cartera, data in gabinete.items():
        s = data.get("sector", "Otros")
        sectores.setdefault(s, []).append((cartera, data))

    filas = ""
    for sector in SECTORES_ORDEN:
        if sector not in sectores:
            continue
        filas += (
            f'<tr><td colspan="4" style="font-size:9px;text-transform:uppercase;'
            f'letter-spacing:.06em;color:#bbb;font-family:Helvetica,Arial,sans-serif;'
            f'font-weight:600;padding:12px 0 3px">{html.escape(sector)}</td></tr>'
        )
        for cartera, data in sectores[sector]:
            np  = html.escape(data.get("nombre_principal", "") or "—")
            na  = data.get("nombre_alternativo", "")
            est = data.get("estado", "vacante")
            fue = html.escape(data.get("fuente", ""))
            na_html = ""
            if na:
                na_html = (
                    f'<br><span style="font-size:10px;color:#999;font-style:italic;'
                    f'font-family:Helvetica,Arial,sans-serif">También: {html.escape(na)}</span>'
                )
            chip = _chip_gabinete_inline(est)
            filas += (
                f'<tr style="border-top:1px solid #d4cfc6">'
                f'<td style="padding:8px 8px 8px 0;font-size:13px;font-weight:bold;'
                f'color:#1a1208;font-family:Georgia,serif;vertical-align:top">{html.escape(cartera)}</td>'
                f'<td style="padding:8px 8px 8px 0;font-size:12px;color:#444;'
                f'font-family:Helvetica,Arial,sans-serif;vertical-align:top">{np}{na_html}</td>'
                f'<td style="padding:8px 8px 8px 0;text-align:center;vertical-align:top">{chip}</td>'
                f'<td style="padding:8px 0;font-size:9px;color:#bbb;'
                f'font-family:Helvetica,Arial,sans-serif;text-align:right;vertical-align:top">{fue}</td>'
                f'</tr>'
            )

    leyenda_chip_conf = _chip_gabinete_inline("confirmado")
    leyenda_chip_sue  = _chip_gabinete_inline("suena")
    leyenda_chip_vac  = _chip_gabinete_inline("vacante")
    lbl_style = "font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif;margin-left:5px"

    return (
        f'<tr><td style="padding:22px 0 0;border-top:2px solid {C_AZUL}">'
        f'<p style="margin:0 0 10px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;'
        f'color:{C_AZUL};font-weight:bold;font-family:Helvetica,Arial,sans-serif">Conformación del gabinete</p>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">'
        f'<tr style="border-bottom:2px solid {C_AZUL}">'
        f'<th style="text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:.06em;'
        f'color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:600;padding:0 8px 6px 0;width:26%">Cartera</th>'
        f'<th style="text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:.06em;'
        f'color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:600;padding:0 8px 6px 0;width:40%">Nombre(s)</th>'
        f'<th style="text-align:center;font-size:9px;text-transform:uppercase;letter-spacing:.06em;'
        f'color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:600;padding:0 8px 6px 0;width:16%">Estado</th>'
        f'<th style="text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:.06em;'
        f'color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:600;padding:0 0 6px 0;width:18%">Fuente</th>'
        f'</tr>'
        f'{filas}'
        f'</table>'
        f'<table cellpadding="0" cellspacing="0" style="margin-top:10px;padding-top:8px;'
        f'border-top:0.5px solid #d4cfc6"><tr>'
        f'<td style="padding-right:12px">{leyenda_chip_conf}<span style="{lbl_style}">Oficial</span></td>'
        f'<td style="padding-right:12px">{leyenda_chip_sue}<span style="{lbl_style}">En medios</span></td>'
        f'<td>{leyenda_chip_vac}<span style="{lbl_style}">Sin info</span></td>'
        f'</tr></table>'
        f'</td></tr>'
    )


# ── HTML web ──────────────────────────────────────────────────────────────────

def generar_html(briefing: dict, gabinete: dict) -> str:
    ahora        = datetime.datetime.now(tz=COLOMBIA_TZ)
    dias_s       = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    meses_s      = ["","enero","febrero","marzo","abril","mayo","junio","julio",
                    "agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_bonita = f"{dias_s[ahora.weekday()]} {ahora.day} de {meses_s[ahora.month]} de {ahora.year}"
    hora_str     = ahora.strftime("%H:%M")
    dias_pos     = (POSESION - ahora.date()).days

    e       = briefing.get("empalme", {})
    titular = html.escape(briefing.get("titular_del_dia", ""))
    atento  = html.escape(briefing.get("para_estar_atento", ""))
    nota_e  = html.escape(e.get("nota", ""))
    editorial = html.escape(briefing.get("editorial", ""))
    noticias  = briefing.get("noticias", [])
    gab_conf, gab_sue, gab_vac = _stats_gabinete(gabinete)
    gab_total = len(gabinete) or len(CARTERAS_BASE)

    def chip(val, campo):
        return _chip_empalme_css(campo, val)

    def render_noticias(items):
        if not items:
            return ""
        cards = ""
        for it in items:
            t2  = html.escape(it.get("titular", ""))
            r2  = html.escape(it.get("contexto", "") or it.get("resumen", ""))
            fu  = html.escape(it.get("fuente", ""))
            url = it.get("url", "")
            ver = (
                f'<a class="ver-nota" href="{html.escape(url)}" target="_blank">Ver nota &#8594;</a>'
                if url else ""
            )
            badge = f'<span class="badge">{fu}</span>' if fu else ""
            cards += (
                f'<div class="card">'
                f'<div class="card-head"><span class="card-titular">{t2}</span>{badge}</div>'
                f'<p class="card-resumen">{r2}</p>{ver}'
                f'</div>'
            )
        return (
            f'<div class="seccion">'
            f'<div class="sec-lbl"><span class="sec-line"></span>Noticias del momento</div>'
            f'{cards}'
            f'</div>'
        )

    noticias_html = render_noticias(noticias)
    gabinete_html = _render_gabinete_web(gabinete)

    bloque_ed = (
        "<div class=\"editorial\">"
        "<div class=\"editorial-lbl\">An&aacute;lisis</div>"
        "<p class=\"editorial-txt\">" + editorial + "</p>"
        "</div>"
    ) if editorial else ""

    bloque_nota = (
        "<div class=\"thermo-sep\"></div>"
        "<span class=\"thermo-nota\">" + nota_e + "</span>"
    ) if nota_e else ""

    bloque_atento = (
        "<div class=\"atento\">"
        "<div class=\"atento-lbl\">Para estar atento</div>"
        "<p>" + atento + "</p>"
        "</div>"
    ) if atento else ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>Bit&aacute;cora del Empalme &middot; {fecha_bonita}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Georgia,'Times New Roman',serif;background:#F4F1EC;color:#1a1208;min-height:100vh}}
.wrap{{max-width:680px;margin:0 auto;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.12)}}
.flag{{display:flex;height:6px}}
.flag-y{{flex:2;background:{C_AMARILLO}}}
.flag-b{{flex:1;background:{C_AZUL}}}
.flag-r{{flex:1;background:{C_ROJO}}}
.masthead{{background:{C_AZUL};padding:10px 28px;display:flex;align-items:center;justify-content:space-between}}
.masthead-title{{color:{C_AMARILLO};font-size:13px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.masthead-date{{color:rgba(255,255,255,.7);font-size:11px;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.body{{padding:28px 28px 0}}
.scoreboard{{border-top:3px solid {C_AZUL};border-bottom:1px solid #d4cfc6;padding:12px 0;margin-bottom:20px;display:flex;gap:0}}
.score-item{{flex:1;text-align:center;padding:0 10px;border-right:1px solid #d4cfc6}}
.score-item:last-child{{border-right:none}}
.score-lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:600}}
.score-val{{font-size:22px;font-weight:bold;line-height:1.2;margin-top:2px}}
.score-sub{{font-size:10px;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;margin-top:1px}}
.titular-wrapper{{border-top:3px solid #1a1208;padding:14px 0 16px}}
.titular-kicker{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:{C_AZUL};font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:6px}}
.titular-txt{{font-size:26px;font-weight:bold;line-height:1.25;color:#1a1208}}
.editorial{{padding:14px 0;border-top:1px solid #d4cfc6;border-bottom:1px solid #d4cfc6;margin-bottom:16px}}
.editorial-lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#1a1208;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:5px}}
.editorial-txt{{font-size:13px;color:#1a1208;line-height:1.8}}
.termometro{{background:#F4F1EC;border:1px solid #d4cfc6;padding:10px 14px;margin:0 0 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.thermo-item{{display:flex;align-items:center;gap:7px;font-size:12px;color:#555;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.thermo-sep{{width:1px;height:20px;background:#d4cfc6}}
.thermo-nota{{font-size:11px;color:#777;flex:1;min-width:120px;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-style:italic}}
.chip{{font-size:9px;padding:2px 8px;font-weight:700;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;letter-spacing:.03em}}
.chip-azul{{background:{C_AZUL};color:#fff}}
.chip-amarillo{{background:{C_AMARILLO};color:#7a5c00}}
.chip-rojo{{background:{C_ROJO};color:#fff}}
.chip-verde{{background:#2D6A1F;color:#fff}}
.chip-gris{{background:#888;color:#fff}}
.seccion{{margin-bottom:24px}}
.sec-lbl{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:{C_AZUL};font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px}}
.sec-line{{display:inline-block;width:28px;height:2px;background:{C_AMARILLO};flex-shrink:0}}
.card{{border-top:1px solid #d4cfc6;padding:12px 0}}
.card:last-child{{border-bottom:1px solid #d4cfc6}}
.card-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:5px}}
.card-titular{{font-size:15px;font-weight:bold;line-height:1.3;color:#1a1208}}
.badge{{font-size:9px;padding:2px 7px;border:1px solid #d4cfc6;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;white-space:nowrap;flex-shrink:0;margin-top:2px;letter-spacing:.03em;text-transform:uppercase}}
.card-resumen{{font-size:13px;color:#444;line-height:1.7;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.ver-nota{{font-size:11px;color:{C_AZUL};text-decoration:none;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;display:inline-block;margin-top:5px;font-weight:600}}
.ver-nota:hover{{text-decoration:underline}}
.atento{{background:#FFFBEA;border-left:3px solid {C_AMARILLO};padding:12px 14px;margin:8px 0 28px}}
.atento-lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#7a5c00;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:5px}}
.atento p{{font-size:12px;color:#5a4200;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.gb-wrapper{{margin-bottom:28px}}
table.gb{{width:100%;border-collapse:collapse;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-size:12px}}
table.gb thead tr{{border-bottom:2px solid {C_AZUL}}}
table.gb thead th{{font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:#888;font-weight:600;padding:0 8px 7px 0;text-align:left}}
table.gb tbody tr{{border-top:1px solid #d4cfc6}}
.gb-sector{{font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:#bbb;font-weight:600;padding:12px 0 3px}}
.gb-cartera{{font-size:13px;font-weight:bold;color:#1a1208;font-family:Georgia,serif;padding:8px 8px 8px 0;vertical-align:top}}
.gb-nombre{{font-size:12px;color:#444;padding:8px 8px 8px 0;vertical-align:top}}
.gb-nombre-alt{{font-size:10px;color:#999;font-style:italic}}
.gb-fuente{{font-size:9px;color:#bbb;text-align:right;padding:8px 0;vertical-align:top}}
.gb-leyenda{{display:flex;gap:14px;margin-top:12px;padding-top:10px;border-top:0.5px solid #d4cfc6;flex-wrap:wrap}}
.gb-ley-item{{display:flex;align-items:center;gap:5px;font-size:10px;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.footer{{background:{C_AZUL_OSC};padding:14px 28px;display:flex;align-items:center;justify-content:space-between}}
.footer-txt{{font-size:10px;color:rgba(255,255,255,.45);font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;text-transform:uppercase;letter-spacing:.06em}}
.footer-dias{{font-size:18px;font-weight:bold;color:{C_AMARILLO}}}
.footer-dias-lbl{{font-size:9px;color:rgba(255,255,255,.35);font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;text-transform:uppercase;letter-spacing:.06em;margin-top:1px}}
</style>
</head>
<body>
<div class="wrap">

  <div class="flag"><div class="flag-y"></div><div class="flag-b"></div><div class="flag-r"></div></div>

  <div class="masthead">
    <span class="masthead-title">Bit&aacute;cora del Empalme &middot; Colombia 2026</span>
    <span class="masthead-date">{fecha_bonita} &middot; {hora_str}</span>
  </div>

  <div class="body">

    <div class="scoreboard">
      <div class="score-item">
        <div class="score-lbl">7 agosto 2026</div>
        <div class="score-val" style="color:{C_AMARILLO};font-size:32px">{dias_pos}</div>
        <div class="score-sub">d&iacute;as para posesi&oacute;n</div>
      </div>
      <div class="score-item">
        <div class="score-lbl">Confirmados</div>
        <div class="score-val" style="color:{C_AZUL}">{gab_conf}</div>
        <div class="score-sub">de {gab_total} carteras</div>
      </div>
      <div class="score-item">
        <div class="score-lbl">Suenan</div>
        <div class="score-val" style="color:#C8860A">{gab_sue}</div>
        <div class="score-sub">en evaluaci&oacute;n</div>
      </div>
      <div class="score-item">
        <div class="score-lbl">Vacantes</div>
        <div class="score-val" style="color:#888">{gab_vac}</div>
        <div class="score-sub">sin definir</div>
      </div>
    </div>

    <div class="titular-wrapper">
      <div class="titular-kicker">Titular del d&iacute;a</div>
      <div class="titular-txt">{titular}</div>
    </div>

    {bloque_ed}

    <div class="termometro">
      <div class="thermo-item">Gabinete &nbsp;{chip(e.get('gabinete','pendiente'), 'gabinete')}</div>
      <div class="thermo-sep"></div>
      <div class="thermo-item">Reconocimiento &nbsp;{chip(e.get('reconocimiento','pendiente'), 'reconocimiento')}</div>
      {bloque_nota}
    </div>

    {noticias_html}

    {bloque_atento}

    {gabinete_html}

  </div>

  <div class="footer">
    <div>
      <div class="footer-txt">Monitor de Transici&oacute;n &middot; Colombia 2026</div>
      <div class="footer-txt" style="margin-top:2px;opacity:.4">Generado con Claude API &middot; {hora_str}</div>
    </div>
    <div style="text-align:right">
      <div class="footer-dias">{dias_pos}</div>
      <div class="footer-dias-lbl">d&iacute;as para posesi&oacute;n</div>
    </div>
  </div>

</div>
</body>
</html>"""


# ── HTML email ────────────────────────────────────────────────────────────────

def generar_html_email(briefing: dict, gabinete: dict) -> str:
    """HTML con estilos inline para Gmail."""
    ahora        = datetime.datetime.now(tz=COLOMBIA_TZ)
    dias_s       = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    meses_s      = ["","enero","febrero","marzo","abril","mayo","junio","julio",
                    "agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_bonita = f"{dias_s[ahora.weekday()]} {ahora.day} de {meses_s[ahora.month]} de {ahora.year}"
    hora_str     = ahora.strftime("%H:%M")
    dias_pos     = (POSESION - ahora.date()).days

    e        = briefing.get("empalme", {})
    titular  = html.escape(briefing.get("titular_del_dia", ""))
    atento   = html.escape(briefing.get("para_estar_atento", ""))
    nota_e   = html.escape(e.get("nota", ""))
    editorial_e = html.escape(briefing.get("editorial", ""))
    noticias_e  = briefing.get("noticias", [])
    gab_conf, gab_sue, gab_vac = _stats_gabinete(gabinete)
    gab_total = len(gabinete) or len(CARTERAS_BASE)

    def noticias_email(items):
        if not items:
            return ""
        out = (
            f'<tr><td style="padding:18px 0 8px;border-top:2px solid {C_AZUL}">'
            f'<p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.1em;'
            f'color:{C_AZUL};font-weight:bold;font-family:Helvetica,Arial,sans-serif">Noticias del momento</p>'
            f'</td></tr>'
        )
        for it in items:
            t2  = html.escape(it.get("titular", ""))
            r2  = html.escape(it.get("contexto", "") or it.get("resumen", ""))
            fu  = html.escape(it.get("fuente", ""))
            url = it.get("url", "")
            ver = (
                f'<a href="{html.escape(url)}" style="font-size:11px;color:{C_AZUL};'
                f'text-decoration:none;font-weight:bold;font-family:Helvetica,Arial,sans-serif">Ver nota &#8594;</a>'
                if url else ""
            )
            badge = (
                f'<span style="font-size:9px;padding:2px 6px;border:1px solid #d4cfc6;'
                f'color:#888;font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;'
                f'letter-spacing:.03em">{fu}</span>'
                if fu else ""
            )
            out += (
                f'<tr><td style="padding:12px 0;border-top:1px solid #d4cfc6">'
                f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
                f'<td><p style="margin:0 0 5px;font-size:15px;font-weight:bold;color:#1a1208;'
                f'line-height:1.3;font-family:Georgia,serif">{t2}</p></td>'
                f'<td align="right" style="vertical-align:top;padding-left:8px">{badge}</td>'
                f'</tr></table>'
                f'<p style="margin:4px 0 6px;font-size:12px;color:#444;line-height:1.7;'
                f'font-family:Helvetica,Arial,sans-serif">{r2}</p>'
                f'{ver}</td></tr>'
            )
        return out

    secciones = noticias_email(noticias_e)
    gabinete_rows = _render_gabinete_email(gabinete)

    td_nota  = f'padding-left:12px;border-left:1px solid #d4cfc6'
    sp_nota  = f'font-size:11px;color:#777;font-style:italic;font-family:Helvetica,Arial,sans-serif'
    bloque_nota_e = (
        f'<td style="{td_nota}"><span style="{sp_nota}">{nota_e}</span></td>'
    ) if nota_e else ""

    bloque_ed_e = (
        f'<tr><td style="padding:14px 0;border-top:1px solid #d4cfc6;border-bottom:1px solid #d4cfc6">'
        f'<p style="margin:0 0 5px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;'
        f'color:#1a1208;font-weight:bold;font-family:Helvetica,Arial,sans-serif">An&#225;lisis</p>'
        f'<p style="margin:0;font-size:13px;color:#1a1208;line-height:1.8;font-family:Georgia,serif">'
        f'{editorial_e}</p></td></tr>'
    ) if editorial_e else ""

    bloque_atento_e = (
        f"<tr><td style='padding:4px 0 20px'>"
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='background:#FFFBEA;border-left:3px solid {C_AMARILLO}'>"
        f"<tr><td style='padding:12px 14px'>"
        f"<p style='margin:0 0 5px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;"
        f"color:#7a5c00;font-weight:bold;font-family:Helvetica,Arial,sans-serif'>Para estar atento</p>"
        f"<p style='margin:0;font-size:12px;color:#5a4200;line-height:1.6;"
        f"font-family:Helvetica,Arial,sans-serif'>{atento}</p>"
        f"</td></tr></table></td></tr>"
    ) if atento else ""

    chip_gab = _chip_empalme_inline("gabinete", e.get("gabinete", "pendiente"))
    chip_rec = _chip_empalme_inline("reconocimiento", e.get("reconocimiento", "pendiente"))

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F1EC;font-family:Georgia,serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F1EC;padding:0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff">

  <!-- Franja tricolor -->
  <tr>
    <td width="50%" style="background:{C_AMARILLO};height:5px;font-size:1px">&nbsp;</td>
    <td width="25%" style="background:{C_AZUL};height:5px;font-size:1px">&nbsp;</td>
    <td width="25%" style="background:{C_ROJO};height:5px;font-size:1px">&nbsp;</td>
  </tr>

  <!-- Masthead -->
  <tr><td colspan="3" style="background:{C_AZUL};padding:10px 24px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><p style="margin:0;color:{C_AMARILLO};font-size:12px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase;font-family:Helvetica,Arial,sans-serif">Bit&aacute;cora del Empalme &middot; Colombia 2026</p></td>
      <td align="right"><p style="margin:0;color:rgba(255,255,255,.7);font-size:10px;font-family:Helvetica,Arial,sans-serif">{fecha_bonita} &middot; {hora_str}</p></td>
    </tr></table>
  </td></tr>

  <!-- Body -->
  <tr><td colspan="3" style="padding:20px 24px 0">
  <table width="100%" cellpadding="0" cellspacing="0">

    <!-- Scoreboard -->
    <tr><td style="border-top:3px solid {C_AZUL};border-bottom:1px solid #d4cfc6;padding:10px 0 12px">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td width="25%" style="text-align:center;border-right:1px solid #d4cfc6;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">7 agosto 2026</p>
          <p style="margin:3px 0 1px;font-size:28px;font-weight:bold;color:{C_AMARILLO};font-family:Helvetica,Arial,sans-serif">{dias_pos}</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">d&iacute;as posesi&oacute;n</p>
        </td>
        <td width="25%" style="text-align:center;border-right:1px solid #d4cfc6;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">Confirmados</p>
          <p style="margin:3px 0 1px;font-size:26px;font-weight:bold;color:{C_AZUL};font-family:Helvetica,Arial,sans-serif">{gab_conf}</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">de {gab_total} carteras</p>
        </td>
        <td width="25%" style="text-align:center;border-right:1px solid #d4cfc6;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">Suenan</p>
          <p style="margin:3px 0 1px;font-size:26px;font-weight:bold;color:#C8860A;font-family:Helvetica,Arial,sans-serif">{gab_sue}</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">en evaluaci&oacute;n</p>
        </td>
        <td width="25%" style="text-align:center;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">Vacantes</p>
          <p style="margin:3px 0 1px;font-size:26px;font-weight:bold;color:#888;font-family:Helvetica,Arial,sans-serif">{gab_vac}</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">sin definir</p>
        </td>
      </tr></table>
    </td></tr>

    <!-- Titular -->
    <tr><td style="padding:16px 0 0">
      <p style="margin:0 0 6px;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:{C_AZUL};font-weight:bold;font-family:Helvetica,Arial,sans-serif">Titular del d&iacute;a</p>
      <p style="margin:0;font-size:24px;font-weight:bold;color:#1a1208;line-height:1.25;font-family:Georgia,serif">{titular}</p>
    </td></tr>

    <!-- Editorial -->
    {bloque_ed_e}

    <!-- Panel empalme -->
    <tr><td style="padding:14px 0">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F1EC;border:1px solid #d4cfc6">
      <tr><td style="padding:10px 14px">
        <table cellpadding="0" cellspacing="0"><tr>
          <td style="padding-right:12px;white-space:nowrap">
            <span style="font-size:12px;color:#555;font-family:Helvetica,Arial,sans-serif">Gabinete &nbsp;</span>{chip_gab}
          </td>
          <td style="padding:0 12px;border-left:1px solid #d4cfc6;white-space:nowrap">
            <span style="font-size:12px;color:#555;font-family:Helvetica,Arial,sans-serif">Reconocimiento &nbsp;</span>{chip_rec}
          </td>
          {bloque_nota_e}
        </tr></table>
      </td></tr>
      </table>
    </td></tr>

    <!-- Noticias -->
    {secciones}

    <!-- Para estar atento -->
    {bloque_atento_e}

    <!-- Gabinete -->
    {gabinete_rows}

  </table>
  </td></tr>

  <!-- Footer -->
  <tr><td colspan="3" style="background:{C_AZUL_OSC};padding:14px 24px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td>
        <p style="margin:0;font-size:10px;color:rgba(255,255,255,.45);text-transform:uppercase;letter-spacing:.06em;font-family:Helvetica,Arial,sans-serif">Monitor de Transici&oacute;n &middot; Colombia 2026</p>
        <p style="margin:2px 0 0;font-size:9px;color:rgba(255,255,255,.3);font-family:Helvetica,Arial,sans-serif">Generado con Claude API &middot; {hora_str}</p>
      </td>
      <td align="right">
        <p style="margin:0;font-size:20px;font-weight:bold;color:{C_AMARILLO};font-family:Helvetica,Arial,sans-serif">{dias_pos}</p>
        <p style="margin:1px 0 0;font-size:9px;color:rgba(255,255,255,.35);text-transform:uppercase;letter-spacing:.06em;font-family:Helvetica,Arial,sans-serif">d&iacute;as para posesi&oacute;n</p>
      </td>
    </tr></table>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ── Email ─────────────────────────────────────────────────────────────────────

def enviar_email(html_content: str, titular: str, destinatarios: list, gmail_pass: str):
    if not destinatarios:
        log("Sin destinatarios — email omitido.")
        return

    ahora  = datetime.datetime.now(tz=COLOMBIA_TZ)
    meses  = ["","enero","febrero","marzo","abril","mayo","junio",
              "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha  = f"{ahora.day} de {meses[ahora.month]}"
    hora   = ahora.strftime("%H:%M")
    asunto = f"Bitácora del Empalme {fecha} {hora} · {titular}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = f"{EMAIL_NOMBRE} <{EMAIL_REMITENTE}>"
    msg["To"]      = EMAIL_REMITENTE  # To visible solo al remitente
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_REMITENTE, gmail_pass)
            server.sendmail(EMAIL_REMITENTE, destinatarios, msg.as_string())
        log(f"Email enviado a {len(destinatarios)} destinatario(s)")
    except Exception as e:
        log(f"ERROR al enviar email: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    api_key    = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    cfg        = leer_config()
    modo       = os.environ.get("MODO", cfg.get("MODO", "produccion")).strip().lower()

    if not api_key:
        log("ERROR: Variable ANTHROPIC_API_KEY no encontrada.")
        sys.exit(1)
    if not gmail_pass:
        log("AVISO: GMAIL_APP_PASSWORD no encontrada. Se generará el HTML pero no se enviará email.")

    log("=== Iniciando Bitácora del Empalme ===")

    try:
        _, gabinete_actual = cargar_memoria()

        contexto = recopilar_medios()
        log("Medios recopilados. Llamando a la API...")

        briefing       = llamar_api(contexto, api_key, gabinete_actual)
        titular        = briefing.get("titular_del_dia", "")
        gabinete_nuevo = actualizar_gabinete(
            gabinete_actual,
            briefing.get("gabinete_update", {})
        )
        log(f"Bitácora generada: {titular[:60]}")

        if modo != "pruebas":
            guardar_memoria(briefing, gabinete_nuevo)
            log("Memoria actualizada.")
        else:
            log("MODO PRUEBAS — memoria no actualizada.")

        html_web = generar_html(briefing, gabinete_nuevo)
        OUTPUT_HTML.write_text(html_web, encoding="utf-8")
        log(f"HTML guardado en: {OUTPUT_HTML}")

        if gmail_pass:
            destinatarios = leer_destinatarios()
            enviar_email(
                generar_html_email(briefing, gabinete_nuevo),
                titular,
                destinatarios,
                gmail_pass
            )

        print(f"\n✓ Bitácora lista → {OUTPUT_HTML}\n")

    except Exception as e:
        log(f"ERROR: {e}")
        error_html = (
            "<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
            "<title>Error</title></head>"
            "<body style='font-family:sans-serif;padding:2rem'>"
            f"<h2>Error al generar la bitácora</h2><p>{html.escape(str(e))}</p>"
            "<p>Revisa el archivo bitacora.log para más detalles.</p>"
            "</body></html>"
        )
        OUTPUT_HTML.write_text(error_html, encoding="utf-8")
        sys.exit(1)


if __name__ == "__main__":
    main()
