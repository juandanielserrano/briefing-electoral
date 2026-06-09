#!/usr/bin/env python3
"""
Briefing Electoral Colombia 2026
Genera un resumen diario de los principales medios colombianos
usando la API de Anthropic y lo envía por email.
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

# ── Zona horaria Colombia ────────────────────────────────────────────────────────
COLOMBIA_TZ = datetime.timezone(datetime.timedelta(hours=-5))

# ── Configuración ──────────────────────────────────────────────────────────────

SCRIPT_DIR      = Path(__file__).parent
OUTPUT_HTML     = SCRIPT_DIR / "briefing.html"
LOG_FILE        = SCRIPT_DIR / "briefing.log"
DESTINATARIOS_F = SCRIPT_DIR / "destinatarios.txt"
MEMORIA_F       = SCRIPT_DIR / "memoria.json"

EMAIL_REMITENTE = "juandanielserrano@gmail.com"
EMAIL_NOMBRE    = "Briefing Electoral"

MEDIOS = [
    ("El Tiempo",        "https://www.eltiempo.com/politica/elecciones-colombia-2026"),
    ("El Espectador",    "https://www.elespectador.com/politica/elecciones-2026"),
    ("La Silla Vacía",   "https://www.lasillavacia.com"),
    ("Caracol Noticias", "https://noticias.caracoltv.com/colombia/politica"),
    ("La FM",            "https://www.lafm.com.co/politica"),
    ("El Colombiano",    "https://www.elcolombiano.com/colombia/politica"),
    ("La República",     "https://www.larepublica.co/politica"),
    ("Dos Orillas",      "https://www.dosrillas.com"),
    ("Razón Pública",    "https://razonpublica.com/categoria/politica-y-gobierno-temas/"),
    ("Cuestión Pública", "https://cuestionpublica.com/categoria/politica/"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MODEL           = "claude-sonnet-4-5"
MAX_TOKENS      = 3000
TEXTO_POR_MEDIO = 1500

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.datetime.now(tz=COLOMBIA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── Destinatarios ──────────────────────────────────────────────────────────────

def leer_destinatarios() -> list:
    """Lee destinatarios desde variable de entorno DESTINATARIOS o desde destinatarios.txt."""
    env_dest = os.environ.get("DESTINATARIOS", "").strip()
    if env_dest:
        correos = [c.strip() for c in env_dest.split(",") if c.strip()]
        log(f"Destinatarios desde variable de entorno: {len(correos)}")
        return correos
    if not DESTINATARIOS_F.exists():
        log(f"AVISO: No se encontró {DESTINATARIOS_F} ni variable DESTINATARIOS. No se enviará email.")
        return []
    correos = []
    for linea in DESTINATARIOS_F.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            correos.append(linea)
    return correos

# ── Scraping ───────────────────────────────────────────────────────────────────

def fetch_texto(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        raw = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>.*?</style>",   " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)
        raw = re.sub(r"</?(p|br|h[1-6]|li|div|article|section)[^>]*>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = html.unescape(raw)
        lines = [l.strip() for l in raw.splitlines() if len(l.strip()) > 40]
        return "\n".join(lines)[:TEXTO_POR_MEDIO]
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

# ── Llamada a la API ───────────────────────────────────────────────────────────

def cargar_memoria() -> str:
    """Lee el resumen del último briefing guardado para evitar repetición."""
    if not MEMORIA_F.exists():
        return ""
    try:
        data = json.loads(MEMORIA_F.read_text(encoding="utf-8"))
        return data.get("resumen", "")
    except Exception:
        return ""

def guardar_memoria(briefing: dict):
    """Guarda un resumen compacto del briefing actual para la próxima ejecución."""
    titulares = []
    for seccion in briefing.get("secciones", {}).values():
        for it in seccion:
            t = it.get("titular", "").strip()
            if t:
                titulares.append(t)
    resumen = {
        "fecha": briefing.get("fecha", ""),
        "hora": briefing.get("hora", ""),
        "titular_del_dia": briefing.get("titular_del_dia", ""),
        "resumen": briefing.get("editorial", ""),
        "titulares": titulares[:10]
    }
    MEMORIA_F.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")

def llamar_api(contexto: str, api_key: str) -> dict:
    ahora = datetime.datetime.now(tz=COLOMBIA_TZ)
    dias  = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"][ahora.weekday()]
    meses = ["","enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_str = f"{dias} {ahora.day} de {meses[ahora.month]} de {ahora.year}"
    hora_str  = ahora.strftime("%H:%M")

    memoria = cargar_memoria()
    bloque_memoria = ""
    if memoria:
        bloque_memoria = f"""
CONTEXTO DEL BRIEFING ANTERIOR:
{memoria}

Con base en lo anterior, enfócate en lo que ha CAMBIADO o es NUEVO desde ese briefing. No repitas hechos ya cubiertos salvo que hayan tenido un desarrollo relevante.
"""

    prompt = f"""Eres un analista político colombiano senior con el estilo editorial del Financial Times: directo, analítico, sin adjetivos innecesarios, con visión de hacia dónde van los hechos. Hoy es {fecha_str}, {hora_str} (hora Colombia).
{bloque_memoria}
A continuación tienes el contenido extraído de los principales medios colombianos:

{contexto}

Genera un briefing ejecutivo sobre la campaña presidencial para la segunda vuelta del 21 de junio de 2026 entre:
- Abelardo de la Espriella (Defensores de la Patria, derecha, primera vuelta 43,74%)
- Iván Cepeda Castro (Pacto Histórico, izquierda/oficialismo, primera vuelta 40,90%)

Responde ÚNICAMENTE con un objeto JSON válido. Sin texto adicional, sin backticks, sin markdown. Estructura exacta:

{{
  "fecha": "{fecha_str}",
  "hora": "{hora_str}",
  "titular_del_dia": "Una frase corta que capture el tema dominante del momento",
  "editorial": "1-2 párrafos de síntesis analítica. Qué está pasando realmente en la campaña y hacia dónde va. Voz de analista senior, no de periodista. Sin bullets. Prosa fluida. Máximo 120 palabras.",
  "termometro": {{
    "espriella": "subiendo|estable|bajando",
    "cepeda": "subiendo|estable|bajando",
    "nota": "Una línea sobre la dinámica del momento"
  }},
  "noticias": [
    {{
      "titular": "Titular preciso que capture el hecho nuevo",
      "contexto": "1-2 frases: qué cambió o evolucionó respecto a lo ya sabido. Solo lo nuevo.",
      "fuente": "Nombre del medio",
      "url": ""
    }}
  ],
  "para_estar_atento": "1-2 frases sobre qué viene en las próximas horas o días"
}}

Reglas:
- El campo "editorial" es obligatorio y debe ser prosa analítica, no un resumen de titulares.
- En "noticias" incluye solo hechos nuevos o con desarrollo relevante desde el último briefing.
- Máximo 6 noticias. Sin repetir lo que ya se cubrió antes.
- No inventes hechos. Sé directo y preciso.
"""

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
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

# ── Generación HTML ────────────────────────────────────────────────────────────

def chip_termometro(val: str) -> str:
    if val == "subiendo":
        return '<span class="chip chip-verde">↑ Subiendo</span>'
    if val == "bajando":
        return '<span class="chip chip-rojo">↓ Bajando</span>'
    return '<span class="chip chip-azul">→ Estable</span>'

def render_seccion(titulo: str, items: list) -> str:
    if not items:
        return ""
    cards = ""
    for it in items:
        titular = html.escape(it.get("titular", ""))
        resumen  = html.escape(it.get("resumen", ""))
        fuente   = html.escape(it.get("fuente", ""))
        url      = it.get("url", "")
        ver_nota = f'<a class="ver-nota" href="{html.escape(url)}" target="_blank">Ver nota →</a>' if url else ""
        badge    = f'<span class="badge">{fuente}</span>' if fuente else ""
        cards += f"""
        <div class="card">
          <div class="card-head">
            <span class="card-titular">{titular}</span>
            {badge}
          </div>
          <div class="card-resumen">{resumen}</div>
          {ver_nota}
        </div>"""
    return f"""
    <div class="seccion">
      <div class="sec-lbl">{html.escape(titulo)}</div>
      {cards}
    </div>"""

def generar_html(briefing: dict) -> str:
    ahora = datetime.datetime.now(tz=COLOMBIA_TZ)
    dias_s = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    meses_s = ["","enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_bonita = f"{dias_s[ahora.weekday()]} {ahora.day} de {meses_s[ahora.month]} de {ahora.year}"
    hora_str = ahora.strftime("%H:%M")
    segunda = (datetime.date(2026,6,21) - datetime.datetime.now(tz=COLOMBIA_TZ).date()).days

    s = briefing.get("secciones", {})
    t = briefing.get("termometro", {})
    titular = html.escape(briefing.get("titular_del_dia", ""))
    atento  = html.escape(briefing.get("para_estar_atento", ""))
    nota_t  = html.escape(t.get("nota", ""))

    def chip(val):
        if val == "subiendo":
            return '<span class="chip chip-verde">&#8593; Subiendo</span>'
        if val == "bajando":
            return '<span class="chip chip-rojo">&#8595; Bajando</span>'
        return '<span class="chip chip-gris">&#8594; Estable</span>'

    editorial = html.escape(briefing.get("editorial", ""))
    noticias  = briefing.get("noticias", [])

    def render_noticias(items):
        if not items: return ""
        cards = ""
        for it in items:
            t2  = html.escape(it.get("titular",""))
            r2  = html.escape(it.get("contexto","") or it.get("resumen",""))
            fu  = html.escape(it.get("fuente",""))
            url = it.get("url","")
            ver = f'<a class="ver-nota" href="{html.escape(url)}" target="_blank">Ver nota &#8594;</a>' if url else ""
            badge = f'<span class="badge">{fu}</span>' if fu else ""
            cards += f'''<div class="card">
              <div class="card-head"><span class="card-titular">{t2}</span>{badge}</div>
              <p class="card-resumen">{r2}</p>{ver}
            </div>'''
        return f'''<div class="seccion">
          <div class="sec-lbl"><span class="sec-line"></span>Noticias del momento</div>
          {cards}
        </div>'''

    secciones_html = render_noticias(noticias)

    bloque_editorial = (
        "<div class=\"editorial\"><div class=\"editorial-lbl\">An&aacute;lisis</div>"
        "<p class=\"editorial-txt\">" + editorial + "</p></div>"
    ) if editorial else ""
    bloque_termometro_nota = (
        "<div class=\"thermo-sep\"></div><span class=\"thermo-nota\">" + nota_t + "</span>"
    ) if nota_t else ""
    bloque_atento = (
        "<div class=\"atento\"><div class=\"atento-lbl\">Para estar atento</div><p>"
        + atento + "</p></div>"
    ) if atento else ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>Briefing Electoral &middot; {fecha_bonita}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Georgia,'Times New Roman',serif;background:#F4F1EC;color:#1a1208;min-height:100vh}}
.wrap{{max-width:680px;margin:0 auto;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.12)}}

/* Franja superior roja estilo Economist */
.masthead{{background:#CC0000;padding:10px 28px;display:flex;align-items:center;justify-content:space-between}}
.masthead-title{{color:#fff;font-size:13px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.masthead-date{{color:rgba(255,255,255,.8);font-size:11px;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}

/* Cuerpo */
.body{{padding:28px 28px 0}}

/* Scoreboard */
.scoreboard{{border-top:3px solid #CC0000;border-bottom:1px solid #d4cfc6;padding:12px 0;margin-bottom:20px;display:flex;gap:0}}
.score-item{{flex:1;text-align:center;padding:0 10px;border-right:1px solid #d4cfc6}}
.score-item:last-child{{border-right:none}}
.score-lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:600}}
.score-val{{font-size:22px;font-weight:bold;line-height:1.2;margin-top:2px}}
.score-sub{{font-size:10px;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;margin-top:1px}}

/* Titular */
.titular-wrapper{{border-top:3px solid #1a1208;padding:14px 0 16px}}
.titular-kicker{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#CC0000;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:6px}}
.titular-txt{{font-size:26px;font-weight:bold;line-height:1.25;color:#1a1208}}
.titular-dek{{font-size:13px;color:#555;line-height:1.6;margin-top:8px;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}

/* Termómetro */
.termometro{{background:#F4F1EC;border:1px solid #d4cfc6;padding:10px 14px;margin:16px 0 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.thermo-item{{display:flex;align-items:center;gap:7px;font-size:12px;color:#555;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.thermo-sep{{width:1px;height:20px;background:#d4cfc6}}
.thermo-nota{{font-size:11px;color:#777;flex:1;min-width:120px;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-style:italic}}
.chip{{font-size:10px;padding:2px 8px;border-radius:2px;font-weight:700;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;letter-spacing:.03em}}
.chip-verde{{background:#2D6A1F;color:#fff}}
.chip-rojo{{background:#CC0000;color:#fff}}
.chip-gris{{background:#555;color:#fff}}

/* Secciones */
.seccion{{margin-bottom:24px}}
.sec-lbl{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#CC0000;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px}}
.sec-line{{display:inline-block;width:28px;height:2px;background:#CC0000;flex-shrink:0}}
.card{{border-top:1px solid #d4cfc6;padding:12px 0;margin-bottom:0}}
.card:last-child{{border-bottom:1px solid #d4cfc6}}
.card-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:5px}}
.card-titular{{font-size:15px;font-weight:bold;line-height:1.3;color:#1a1208}}
.badge{{font-size:9px;padding:2px 7px;border:1px solid #d4cfc6;color:#888;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;white-space:nowrap;flex-shrink:0;margin-top:2px;letter-spacing:.03em;text-transform:uppercase}}
.card-resumen{{font-size:13px;color:#444;line-height:1.7;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}
.ver-nota{{font-size:11px;color:#CC0000;text-decoration:none;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;display:inline-block;margin-top:5px;font-weight:600}}
.ver-nota:hover{{text-decoration:underline}}

/* Atento */
.atento{{background:#FFF8E7;border-left:3px solid #C8860A;padding:12px 14px;margin:8px 0 28px}}
.atento-lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#C8860A;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-weight:700;margin-bottom:5px}}
.atento p{{font-size:12px;color:#6b5000;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}}

/* Footer */
.footer{{background:#1a1208;padding:14px 28px;display:flex;align-items:center;justify-content:space-between}}
.footer-txt{{font-size:10px;color:rgba(255,255,255,.5);font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;text-transform:uppercase;letter-spacing:.06em}}
.footer-dias{{font-size:18px;font-weight:bold;color:#CC0000}}
.footer-dias-lbl{{font-size:9px;color:rgba(255,255,255,.4);font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;text-transform:uppercase;letter-spacing:.06em;margin-top:1px}}
</style>
</head>
<body>
<div class="wrap">

  <div class="masthead">
    <span class="masthead-title">Briefing Electoral &middot; Colombia 2026</span>
    <span class="masthead-date">{fecha_bonita} &middot; {hora_str}</span>
  </div>

  <div class="body">

    <div class="scoreboard">
      <div class="score-item">
        <div class="score-lbl">De la Espriella</div>
        <div class="score-val" style="color:#CC0000">43,74%</div>
        <div class="score-sub">primera vuelta</div>
      </div>
      <div class="score-item">
        <div class="score-lbl">Cepeda</div>
        <div class="score-val" style="color:#1a4a8a">40,90%</div>
        <div class="score-sub">primera vuelta</div>
      </div>
      <div class="score-item">
        <div class="score-lbl">AtlasIntel (2 jun)</div>
        <div class="score-val" style="font-size:16px">50,3&thinsp;&mdash;&thinsp;42,6</div>
        <div class="score-sub">De la E. +7,7 pts</div>
      </div>
    </div>

    <div class="titular-wrapper">
      <div class="titular-kicker">Titular del d&iacute;a</div>
      <div class="titular-txt">{titular}</div>
    </div>

    {bloque_editorial}

    <div class="termometro">
      <div class="thermo-item">De la Espriella &nbsp;{chip(t.get('espriella','estable'))}</div>
      <div class="thermo-sep"></div>
      <div class="thermo-item">Cepeda &nbsp;{chip(t.get('cepeda','estable'))}</div>
      {bloque_termometro_nota}
    </div>

    {secciones_html}

    {bloque_atento}

  </div>

  <div class="footer">
    <div>
      <div class="footer-txt">Monitor Electoral Colombia</div>
      <div class="footer-txt" style="margin-top:2px;opacity:.4">Generado con Claude API &middot; {hora_str}</div>
    </div>
    <div style="text-align:right">
      <div class="footer-dias">{segunda}</div>
      <div class="footer-dias-lbl">d&iacute;as para votar</div>
    </div>
  </div>

</div>
</body>
</html>"""




# ── HTML optimizado para email (estilos inline, compatible Gmail) ──────────────

def generar_html_email(briefing: dict) -> str:
    """HTML email estilo editorial FT/Economist — estilos inline para Gmail."""
    ahora = datetime.datetime.now(tz=COLOMBIA_TZ)
    dias_s  = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    meses_s = ["","enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_bonita = f"{dias_s[ahora.weekday()]} {ahora.day} de {meses_s[ahora.month]} de {ahora.year}"
    hora_str = ahora.strftime("%H:%M")
    segunda = (datetime.date(2026,6,21) - datetime.datetime.now(tz=COLOMBIA_TZ).date()).days

    s = briefing.get("secciones", {})
    t = briefing.get("termometro", {})
    titular = html.escape(briefing.get("titular_del_dia", ""))
    atento  = html.escape(briefing.get("para_estar_atento", ""))
    nota_t  = html.escape(t.get("nota", ""))

    def chip_e(val):
        if val == "subiendo":
            return '<span style="background:#2D6A1F;color:#fff;font-size:10px;padding:2px 8px;font-weight:bold;border-radius:2px;font-family:Helvetica,Arial,sans-serif">&#8593; Subiendo</span>'
        if val == "bajando":
            return '<span style="background:#CC0000;color:#fff;font-size:10px;padding:2px 8px;font-weight:bold;border-radius:2px;font-family:Helvetica,Arial,sans-serif">&#8595; Bajando</span>'
        return '<span style="background:#555;color:#fff;font-size:10px;padding:2px 8px;font-weight:bold;border-radius:2px;font-family:Helvetica,Arial,sans-serif">&#8594; Estable</span>'

    editorial_e = html.escape(briefing.get("editorial", ""))
    noticias_e  = briefing.get("noticias", [])

    def noticias_email(items):
        if not items: return ""
        out = '''<tr><td style="padding:18px 0 8px 0;border-top:2px solid #CC0000">
          <p style="margin:0;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#CC0000;font-weight:bold;font-family:Helvetica,Arial,sans-serif">Noticias del momento</p>
        </td></tr>'''
        for it in items:
            t2  = html.escape(it.get("titular",""))
            r2  = html.escape(it.get("contexto","") or it.get("resumen",""))
            fu  = html.escape(it.get("fuente",""))
            url = it.get("url","")
            ver = f'<a href="{html.escape(url)}" style="font-size:11px;color:#CC0000;text-decoration:none;font-weight:bold;font-family:Helvetica,Arial,sans-serif">Ver nota &#8594;</a>' if url else ""
            badge = f'<span style="font-size:9px;padding:2px 6px;border:1px solid #d4cfc6;color:#888;font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;letter-spacing:.03em">{fu}</span>' if fu else ""
            out += f'''<tr><td style="padding-bottom:12px;border-top:1px solid #d4cfc6;padding-top:12px">
              <table width="100%" cellpadding="0" cellspacing="0"><tr>
                <td><p style="margin:0 0 5px 0;font-size:15px;font-weight:bold;color:#1a1208;line-height:1.3;font-family:Georgia,serif">{t2}</p></td>
                <td align="right" style="vertical-align:top;padding-left:8px">{badge}</td>
              </tr></table>
              <p style="margin:4px 0 6px 0;font-size:12px;color:#444;line-height:1.7;font-family:Helvetica,Arial,sans-serif">{r2}</p>
              {ver}
            </td></tr>'''
        return out

    secciones = noticias_email(noticias_e)

    td_style_nota = "padding-left:12px;border-left:1px solid #d4cfc6"
    span_style_nota = "font-size:11px;color:#777;font-style:italic;font-family:Helvetica,Arial,sans-serif"
    bloque_nota_e = (
        "<td style=\"" + td_style_nota + "\"><span style=\"" + span_style_nota + "\">"
        + nota_t + "</span></td>"
    ) if nota_t else ""

    bloque_editorial_e = (
        "<tr><td style=\"padding:14px 0;border-top:1px solid #d4cfc6;border-bottom:1px solid #d4cfc6\">"
        "<p style=\"margin:0 0 5px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;"
        "color:#1a1208;font-weight:bold;font-family:Helvetica,Arial,sans-serif\">An&#225;lisis</p>"
        "<p style=\"margin:0;font-size:13px;color:#1a1208;line-height:1.8;font-family:Georgia,serif\">"
        + editorial_e + "</p></td></tr>"
    ) if editorial_e else ""

    bloque_atento_e = (
        "<tr><td style=\"padding:4px 0 24px\">"
        "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"background:#FFF8E7;border-left:3px solid #C8860A\">"
        "<tr><td style=\"padding:12px 14px\">"
        "<p style=\"margin:0 0 5px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;"
        "color:#C8860A;font-weight:bold;font-family:Helvetica,Arial,sans-serif\">Para estar atento</p>"
        "<p style=\"margin:0;font-size:12px;color:#6b5000;line-height:1.6;"
        "font-family:Helvetica,Arial,sans-serif\">" + atento + "</p>"
        "</td></tr></table></td></tr>"
    ) if atento else ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F1EC;font-family:Georgia,serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F1EC;padding:0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff">

  <!-- Masthead rojo -->
  <tr><td style="background:#CC0000;padding:10px 24px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><p style="margin:0;color:#fff;font-size:12px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase;font-family:Helvetica,Arial,sans-serif">Briefing Electoral &middot; Colombia 2026</p></td>
      <td align="right"><p style="margin:0;color:rgba(255,255,255,.75);font-size:10px;font-family:Helvetica,Arial,sans-serif">{fecha_bonita} &middot; {hora_str}</p></td>
    </tr></table>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:20px 24px 0">
  <table width="100%" cellpadding="0" cellspacing="0">

    <!-- Scoreboard -->
    <tr><td style="border-top:3px solid #CC0000;border-bottom:1px solid #d4cfc6;padding:10px 0 12px;margin-bottom:16px">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td width="33%" style="text-align:center;border-right:1px solid #d4cfc6;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">De la Espriella</p>
          <p style="margin:3px 0 1px;font-size:22px;font-weight:bold;color:#CC0000;font-family:Helvetica,Arial,sans-serif">43,74%</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">primera vuelta</p>
        </td>
        <td width="33%" style="text-align:center;border-right:1px solid #d4cfc6;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">Cepeda</p>
          <p style="margin:3px 0 1px;font-size:22px;font-weight:bold;color:#1a4a8a;font-family:Helvetica,Arial,sans-serif">40,90%</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">primera vuelta</p>
        </td>
        <td width="34%" style="text-align:center;padding:0 8px">
          <p style="margin:0;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-family:Helvetica,Arial,sans-serif;font-weight:bold">AtlasIntel (2 jun)</p>
          <p style="margin:3px 0 1px;font-size:16px;font-weight:bold;color:#1a1208;font-family:Helvetica,Arial,sans-serif">50,3 &mdash; 42,6%</p>
          <p style="margin:0;font-size:10px;color:#888;font-family:Helvetica,Arial,sans-serif">De la E. +7,7 pts</p>
        </td>
      </tr></table>
    </td></tr>

    <!-- Titular -->
    <tr><td style="padding:16px 0 0">
      <p style="margin:0 0 6px;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#CC0000;font-weight:bold;font-family:Helvetica,Arial,sans-serif">Titular del d&iacute;a</p>
      <p style="margin:0;font-size:24px;font-weight:bold;color:#1a1208;line-height:1.25;font-family:Georgia,serif">{titular}</p>
    </td></tr>

    <!-- Editorial -->
    {bloque_editorial_e}

    <!-- Termómetro -->
    <tr><td style="padding:14px 0">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F1EC;border:1px solid #d4cfc6">
      <tr><td style="padding:10px 14px">
        <table cellpadding="0" cellspacing="0"><tr>
          <td style="padding-right:12px;white-space:nowrap">
            <span style="font-size:12px;color:#555;font-family:Helvetica,Arial,sans-serif">De la Espriella &nbsp;</span>{chip_e(t.get("espriella","estable"))}
          </td>
          <td style="padding:0 12px;border-left:1px solid #d4cfc6;white-space:nowrap">
            <span style="font-size:12px;color:#555;font-family:Helvetica,Arial,sans-serif">Cepeda &nbsp;</span>{chip_e(t.get("cepeda","estable"))}
          </td>
          {bloque_nota_e}
        </tr></table>
      </td></tr>
      </table>
    </td></tr>

    <!-- Secciones -->
    {secciones}

    <!-- Para estar atento -->
    {"<tr><td style='padding:4px 0 24px'><table width='100%' cellpadding='0' cellspacing='0' style='background:#FFF8E7;border-left:3px solid #C8860A'><tr><td style='padding:12px 14px'><p style='margin:0 0 5px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#C8860A;font-weight:bold;font-family:Helvetica,Arial,sans-serif'>Para estar atento</p><p style='margin:0;font-size:12px;color:#6b5000;line-height:1.6;font-family:Helvetica,Arial,sans-serif'>" + atento + "</p></td></tr></table></td></tr>" if atento else ""}

  </table>
  </td></tr>

  <!-- Footer negro -->
  <tr><td style="background:#1a1208;padding:14px 24px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td>
        <p style="margin:0;font-size:10px;color:rgba(255,255,255,.5);text-transform:uppercase;letter-spacing:.06em;font-family:Helvetica,Arial,sans-serif">Monitor Electoral Colombia</p>
        <p style="margin:2px 0 0;font-size:9px;color:rgba(255,255,255,.3);font-family:Helvetica,Arial,sans-serif">Generado con Claude API &middot; {hora_str}</p>
      </td>
      <td align="right">
        <p style="margin:0;font-size:20px;font-weight:bold;color:#CC0000;font-family:Helvetica,Arial,sans-serif">{segunda}</p>
        <p style="margin:1px 0 0;font-size:9px;color:rgba(255,255,255,.4);text-transform:uppercase;letter-spacing:.06em;font-family:Helvetica,Arial,sans-serif">d&iacute;as para votar</p>
      </td>
    </tr></table>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

# ── Email ──────────────────────────────────────────────────────────────────────

def enviar_email(html_content: str, titular: str, destinatarios: list, gmail_pass: str):
    """Envía el briefing como email HTML a todos los destinatarios."""
    if not destinatarios:
        log("Sin destinatarios — email omitido.")
        return

    ahora   = datetime.datetime.now(tz=COLOMBIA_TZ)
    meses   = ["","enero","febrero","marzo","abril","mayo","junio",
               "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha   = f"{ahora.day} de {meses[ahora.month]}"
    hora    = ahora.strftime("%H:%M")
    asunto  = f"Briefing Electoral {fecha} {hora} · {titular}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = f"{EMAIL_NOMBRE} <{EMAIL_REMITENTE}>"
    msg["To"]      = ", ".join(destinatarios)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_REMITENTE, gmail_pass)
            server.sendmail(EMAIL_REMITENTE, destinatarios, msg.as_string())
        log(f"Email enviado a {len(destinatarios)} destinatario(s): {', '.join(destinatarios)}")
    except Exception as e:
        log(f"ERROR al enviar email: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    api_key    = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not api_key:
        log("ERROR: Variable ANTHROPIC_API_KEY no encontrada.")
        sys.exit(1)

    if not gmail_pass:
        log("AVISO: Variable GMAIL_APP_PASSWORD no encontrada. El briefing se generará pero no se enviará por email.")

    log("=== Iniciando briefing electoral ===")

    try:
        contexto     = recopilar_medios()
        log("Medios recopilados. Llamando a la API...")
        briefing     = llamar_api(contexto, api_key)
        titular      = briefing.get("titular_del_dia", "")
        log(f"Briefing generado: {titular[:60]}")
        guardar_memoria(briefing)
        html_content = generar_html(briefing)
        OUTPUT_HTML.write_text(html_content, encoding="utf-8")
        log(f"HTML guardado en: {OUTPUT_HTML}")

        if gmail_pass:
            destinatarios = leer_destinatarios()
            enviar_email(generar_html_email(briefing), titular, destinatarios, gmail_pass)

        print(f"\n✓ Briefing listo → {OUTPUT_HTML}\n")

    except Exception as e:
        log(f"ERROR: {e}")
        error_html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<title>Error</title></head><body style="font-family:sans-serif;padding:2rem">
<h2>Error al generar el briefing</h2><p>{html.escape(str(e))}</p>
<p>Revisa el archivo briefing.log para más detalles.</p></body></html>"""
        OUTPUT_HTML.write_text(error_html, encoding="utf-8")
        sys.exit(1)

if __name__ == "__main__":
    main()
