"""Busca las noticias del día y las guarda en news.json.
Lo corre GitHub Actions todos los días (ver .github/workflows/news.yml)."""
import json, os, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# ---------------- COLOMBIA ----------------
CO_NEGOCIOS = ["larepublica.co", "portafolio.co", "bloomberglinea.com", "valoraanalitik.com",
               "eltiempo.com", "semana.com", "elcolombiano.com", "forbes.co"]
CO_TECNOLOGIA = CO_NEGOCIOS + ["impactotic.co", "enter.co"]
CO_PLANES = ["eltiempo.com", "semana.com", "bogota.gov.co", "infobae.com", "civico.com", "timeout.com"]

# ---------------- VENEZUELA ----------------
VE_NEGOCIOS = ["bancaynegocios.com", "finanzasdigital.com", "descifrado.com", "bloomberglinea.com",
               "eluniversal.com", "elestimulo.com", "talcualdigital.com", "efectococuyo.com", "elnacional.com"]
CO_DEPORTES = ["eltiempo.com", "semana.com", "elcolombiano.com", "futbolred.com", "infobae.com", "elespectador.com"]
VE_DEPORTES = ["meridiano.net", "liderendeportes.com", "eluniversal.com", "elnacional.com", "elestimulo.com"]
VE_PLANES = ["eluniversal.com", "elestimulo.com", "efectococuyo.com", "elnacional.com", "elpitazo.net"]

# País -> categorías: nombre que se ve en la página -> (qué buscar, fuentes, días hacia atrás)
PAISES = {
    "co": {
        "gl": "CO",
        "categorias": {
            "Economía": ("dólar OR inflación OR \"Banco de la República\" OR economía Colombia", CO_NEGOCIOS, 1),
            "Empresas": ("empresa OR compañía OR ventas OR utilidades OR adquisición OR fusión Colombia", CO_NEGOCIOS, 1),
            "Petróleo y energía": ("Ecopetrol OR petróleo OR gas OR energía Colombia", CO_NEGOCIOS, 1),
            "Sector financiero": ("bancos OR Bancolombia OR Davivienda OR Superfinanciera OR CDT OR \"Bolsa de Colombia\"", CO_NEGOCIOS, 1),
            "Tecnología": ("tecnología OR \"inteligencia artificial\" OR fintech OR digital OR app Colombia", CO_TECNOLOGIA, 1),
            "Emprendimiento": ("startup OR emprendimiento OR emprendedores OR \"ronda de inversión\" OR unicornio Colombia", CO_TECNOLOGIA, 3),
            "Nuevos CEO": ("\"nuevo presidente\" OR \"nuevo CEO\" OR nombramiento OR \"asume la presidencia\" empresa", CO_NEGOCIOS, 2),
            "Consultoría": ("consultoría OR consultora OR McKinsey OR Deloitte OR EY OR PwC OR KPMG Colombia", CO_NEGOCIOS, 3),
            "Deportes": ("fútbol OR \"Selección Colombia\" OR \"Liga BetPlay\" OR ciclismo OR tenis OR deportes", CO_DEPORTES, 1),
            "Planes en Bogotá": ("Bogotá planes OR concierto OR festival OR feria OR evento OR \"fin de semana\" OR restaurante", CO_PLANES, 3),
        },
    },
    "ve": {
        "gl": "VE",
        "categorias": {
            "Economía": ("dólar OR BCV OR inflación OR bolívar OR economía Venezuela", VE_NEGOCIOS, 1),
            "Empresas": ("empresa OR compañía OR ventas OR inversión OR comercio Venezuela", VE_NEGOCIOS, 1),
            "Petróleo y energía": ("PDVSA OR petróleo OR Chevron OR gas OR electricidad Venezuela", VE_NEGOCIOS, 1),
            "Sector financiero": ("bancos OR banca OR \"Bolsa de Valores de Caracas\" OR crédito OR Sudeban", VE_NEGOCIOS, 2),
            "Tecnología": ("tecnología OR fintech OR digital OR app OR \"inteligencia artificial\" Venezuela", VE_NEGOCIOS, 3),
            "Emprendimiento": ("emprendimiento OR emprendedores OR startup OR pymes Venezuela", VE_NEGOCIOS, 3),
            "Nuevos CEO": ("\"nuevo presidente\" OR \"nuevo CEO\" OR nombramiento OR designado empresa Venezuela", VE_NEGOCIOS, 3),
            "Deportes": ("fútbol OR Vinotinto OR béisbol OR LVBP OR baloncesto OR deportes Venezuela", VE_DEPORTES, 1),
            "Planes en Caracas": ("Caracas planes OR concierto OR festival OR feria OR evento OR restaurante", VE_PLANES, 3),
        },
    },
}
POR_CATEGORIA = 6
COL = timezone(timedelta(hours=-5))


def buscar(consulta, fuentes, dias, gl):
    sitios = " OR ".join("site:" + f for f in fuentes)
    q = f"{consulta} ({sitios}) when:{dias}d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "es-419", "gl": gl, "ceid": f"{gl}:es-419"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def leer(xml_bytes):
    raiz = ET.fromstring(xml_bytes)
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        fuente = (item.findtext("source") or "").strip()
        if fuente and titulo.endswith(" - " + fuente):
            titulo = titulo[: -len(" - " + fuente)]
        try:
            fecha = parsedate_to_datetime(item.findtext("pubDate")).astimezone(COL)
        except Exception:
            fecha = None
        yield {"titulo": titulo, "fuente": fuente,
               "link": (item.findtext("link") or "").strip(),
               "fecha": fecha.isoformat() if fecha else None}


def noticias_de(pais):
    vistos, noticias = set(), []
    for cat, (consulta, fuentes, dias) in pais["categorias"].items():
        try:
            items = list(leer(buscar(consulta, fuentes, dias, pais["gl"])))
        except Exception as e:
            print(f"[{pais['gl']} · {cat}] error: {e}")
            continue
        items.sort(key=lambda n: n["fecha"] or "", reverse=True)
        n = 0
        for it in items:
            clave = re.sub(r"\W+", "", it["titulo"].lower())[:60]
            if clave in vistos or not it["titulo"]:
                continue
            vistos.add(clave)
            noticias.append({"categoria": cat, **it})
            n += 1
            if n >= POR_CATEGORIA:
                break
        print(f"[{pais['gl']} · {cat}] {n} noticias")
    return noticias


ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODELO = os.environ.get("MODELO_IA", "claude-haiku-5-5")
NOMBRE_PAIS = {"co": "Colombia", "ve": "Venezuela"}


def analizar(pais, categoria, noticias):
    """Pide a la IA un análisis corto de la categoría, basado SOLO en los titulares del día."""
    titulares = "\n".join(f"- {n['titulo']} ({n['fuente']})" for n in noticias)
    instruccion = (
        f"Eres el editor de Finanzas Express, un medio de noticias de negocios para jóvenes de {NOMBRE_PAIS[pais]}. "
        f"Estos son los titulares de hoy en la categoría \"{categoria}\":\n{titulares}\n\n"
        "Escribe un análisis de 2 o 3 frases (máximo 70 palabras) que explique qué está pasando en general "
        "y por qué le importa a un joven (su plata, su trabajo o su ciudad). Reglas: usa SOLO la información "
        "de los titulares; no inventes cifras, nombres ni datos que no aparezcan; lenguaje sencillo, cercano y neutral; "
        "no opines de política; no uses viñetas ni títulos. Responde solo con el análisis."
    )
    body = json.dumps({"model": MODELO, "max_tokens": 300,
                       "messages": [{"role": "user", "content": instruccion}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read())
    return "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text").strip()


def analisis_de(paises):
    if not ANTHROPIC_KEY:
        print("Sin análisis: falta el secreto ANTHROPIC_API_KEY")
        return {}
    salida = {}
    for codigo, lista in paises.items():
        salida[codigo] = {}
        categorias = []
        for n in lista:
            if n["categoria"] not in categorias:
                categorias.append(n["categoria"])
        for cat in categorias:
            try:
                texto = analizar(codigo, cat, [n for n in lista if n["categoria"] == cat])
                if texto:
                    salida[codigo][cat] = texto
            except Exception as e:
                print(f"[{codigo} · {cat}] análisis con error: {e}")
        print(f"[{codigo}] {len(salida[codigo])} análisis")
    return salida


def main():
    paises = {codigo: noticias_de(pais) for codigo, pais in PAISES.items()}
    salida = {"actualizado": datetime.now(COL).isoformat(), "paises": paises, "analisis": analisis_de(paises)}
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
