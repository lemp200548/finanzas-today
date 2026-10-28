"""Busca las noticias del día y las guarda en news.json.
Lo corre GitHub Actions todos los días (ver .github/workflows/news.yml)."""
import json, os, re, urllib.request, urllib.error, urllib.parse, xml.etree.ElementTree as ET
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

# País -> categorías: nombre en la página -> (temas, palabra obligatoria, fuentes, días hacia atrás)
# La búsqueda queda así: (tema1 OR tema2 OR ...) palabra_obligatoria
PAISES = {
    "co": {
        "gl": "CO",
        "categorias": {
            "Economía": ('dólar OR inflación OR "Banco de la República" OR economía OR PIB OR "tasas de interés"', "Colombia", CO_NEGOCIOS, 1),
            "Empresas": ("empresa OR compañía OR ventas OR utilidades OR adquisición OR fusión", "Colombia", CO_NEGOCIOS, 1),
            "Petróleo y energía": ("Ecopetrol OR petróleo OR gas OR energía OR minería", "Colombia", CO_NEGOCIOS, 1),
            "Sector financiero": ('bancos OR Bancolombia OR Davivienda OR Superfinanciera OR CDT OR "Bolsa de Colombia" OR crédito', "Colombia", CO_NEGOCIOS, 1),
            "Tecnología": ('tecnología OR "inteligencia artificial" OR fintech OR digital OR app', "Colombia", CO_TECNOLOGIA, 1),
            "Emprendimiento": ('startup OR emprendimiento OR emprendedores OR "ronda de inversión" OR unicornio', "Colombia", CO_TECNOLOGIA, 3),
            "Nuevos CEO": ('"nuevo presidente" OR "nuevo CEO" OR nombramiento OR "asume la presidencia" OR "nueva presidenta"', "Colombia", CO_NEGOCIOS, 2),
            "Consultoría": ("consultoría OR consultora OR McKinsey OR Deloitte OR EY OR PwC OR KPMG", "Colombia", CO_NEGOCIOS, 3),
            "Deportes": ('fútbol OR "Selección Colombia" OR "Liga BetPlay" OR ciclismo OR tenis OR deportes', "Colombia", CO_DEPORTES, 1),
            "Planes en Bogotá": ('planes OR concierto OR festival OR feria OR evento OR "fin de semana" OR restaurante', "Bogotá", CO_PLANES, 3),
        },
    },
    "ve": {
        "gl": "VE",
        "categorias": {
            "Economía": ("dólar OR BCV OR inflación OR bolívar OR economía OR precios", "Venezuela", VE_NEGOCIOS, 1),
            "Empresas": ("empresa OR compañía OR ventas OR inversión OR comercio OR industria", "Venezuela", VE_NEGOCIOS, 1),
            "Petróleo y energía": ("PDVSA OR petróleo OR Chevron OR gas OR electricidad OR crudo", "Venezuela", VE_NEGOCIOS, 1),
            "Sector financiero": ('bancos OR banca OR "Bolsa de Valores de Caracas" OR crédito OR Sudeban', "Venezuela", VE_NEGOCIOS, 2),
            "Tecnología": ('tecnología OR fintech OR digital OR app OR "inteligencia artificial" OR telecomunicaciones', "Venezuela", VE_NEGOCIOS, 3),
            "Emprendimiento": ("emprendimiento OR emprendedores OR startup OR pymes OR emprendedor", "Venezuela", VE_NEGOCIOS, 3),
            "Nuevos CEO": ('"nuevo presidente" OR "nuevo CEO" OR nombramiento OR designado OR "nueva presidenta"', "Venezuela", VE_NEGOCIOS, 3),
            "Deportes": ("fútbol OR Vinotinto OR béisbol OR LVBP OR baloncesto OR deportes OR beisbol", "Venezuela", VE_DEPORTES, 1),
            "Planes en Caracas": ("planes OR concierto OR festival OR feria OR evento OR restaurante", "Caracas", VE_PLANES, 3),
        },
    },
}

# Si el titular nombra otro país y no el propio, se descarta (evita noticias de Chile, Perú, etc.)
OTROS_PAISES = ["Chile", "chilen", "Perú", "Peru", "peruan", "Brasil", "brasileñ", "Brazil", "Argentin", "México", "Mexico",
                "mexican", "Ecuador", "ecuatorian", "Bolivia", "bolivian", "Paraguay", "Uruguay", "Panamá", "Costa Rica",
                "Guatemala", "Honduras", "El Salvador", "España", "español", "Nicaragua", "República Dominicana", "Cuba",
                "Ucrania", "Rusia", "Noruega", "China", "Japón", "Europa", "HSBC", "Scaloni"]
NOMBRES_PROPIOS = {"CO": ["Colombia", "colombian", "Bogotá", "Medellín", "Cali", "Barranquilla"],
                   "VE": ["Venezuela", "venezolan", "Caracas", "Maracaibo", "Valencia"]}


def es_de_otro_pais(titulo, gl):
    t = titulo.lower()
    if any(p.lower() in t for p in NOMBRES_PROPIOS[gl]):
        return False
    return any(re.search(r"\b" + re.escape(p.lower()), t) for p in OTROS_PAISES)


POR_CATEGORIA = 6      # noticias finales por categoría
CANDIDATOS = 10        # se traen más para que la IA pueda descartar
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
    for cat, (temas, ancla, fuentes, dias) in pais["categorias"].items():
        try:
            items = list(leer(buscar(f"({temas}) {ancla}", fuentes, dias, pais["gl"])))
            items = [it for it in items if not es_de_otro_pais(it["titulo"], pais["gl"])]
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
            if n >= (CANDIDATOS if ANTHROPIC_KEY else POR_CATEGORIA):
                break
        print(f"[{pais['gl']} · {cat}] {n} noticias")
    return noticias


ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODELO = os.environ.get("MODELO_IA", "claude-haiku-5-5")
NOMBRE_PAIS = {"co": "Colombia", "ve": "Venezuela"}


def pedir_ia(instruccion, max_tokens=2000):
    body = json.dumps({"model": MODELO, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": instruccion}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"la API respondió {e.code}: {e.read().decode(errors='ignore')[:300]}")
    texto = "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text").strip()
    if not texto:
        tipos = [b.get("type") for b in res.get("content", [])]
        raise RuntimeError(f"respuesta sin texto (stop_reason={res.get('stop_reason')}, bloques={tipos})")
    return texto


REFERENCIAS = {
    "co": "TransMilenio, el tinto, la quincena, el trancón, la arepa, la Selección, Shakira, el reggaetón, el pico y placa",
    "ve": "la arepa, el Metro de Caracas, la cola, el dólar paralelo, la Vinotinto, el béisbol, las hallacas, el pabellón",
}


def resumir(pais, noticias):
    """Resumen corto del día con humor irónico estilo Morning Brew, basado SOLO en los titulares."""
    titulares = "\n".join(f"- [{n['categoria']}] {n['titulo']}" for n in noticias)
    instruccion = (
        f"Eres el editor de Finanzas Express, un newsletter de negocios para jóvenes de {NOMBRE_PAIS[pais]}. "
        "Escribes como Morning Brew: ingenioso, irónico, conversacional y fácil de leer, como un amigo que sabe "
        "de negocios y te cuenta las noticias con un chiste bueno.\n\n"
        f"Titulares de hoy:\n{titulares}\n\n"
        "TÉCNICAS DE HUMOR (las que usa Morning Brew):\n"
        "1. Juegos de palabras con frases, refranes o canciones que todo el mundo conoce.\n"
        "2. Humor de situaciones del día a día que cualquier joven vive (plata, transporte, comida, trabajo, estudio).\n"
        f"   Referencias locales que puedes usar: {REFERENCIAS[pais]}.\n"
        "3. Comparaciones exageradas pero claras ('subió más rápido que...', 'más perdido que...').\n"
        "4. Remates secos tipo 'la noticia que sorprendió exactamente a nadie' o 'plot twist:'.\n\n"
        "REGLA DE ORO: cada chiste se tiene que entender en 3 segundos por un joven de 20 años. "
        "Nada de metáforas raras o abstractas. Si el chiste necesita explicación, cámbialo por uno más simple.\n\n"
        "EJEMPLOS DEL TONO (inventados; NO los copies, solo imita el estilo):\n"
        '- Título: "El dólar bajó más rápido que tu quincena"\n'
        '- Título: "Shakira no es la única que factura"\n'
        '- Título: "Abuelo, ¿qué era un billete de mil?"\n'
        '- Resumen: "El dólar volvió a bajar y ya está cerca de los $3.100. Traducción: tu próximo celular importado sale '
        'un poquito más barato. Los exportadores, en cambio, hoy no están brindando."\n'
        '- Comentario: "Los bancos reportando ganancias récord: la noticia que sorprendió exactamente a nadie."\n'
        '- Comentario: "Si el pasaje sigue subiendo, vamos a tener que pagar el bus a cuotas."\n\n'
        "Escribe el resumen del día en JSON con exactamente estas claves:\n"
        '- "titulo": título corto con gancho, idealmente un juego de palabras (máximo 8 palabras).\n'
        '- "resumen": 2 o 3 frases cortas (máximo 60 palabras): qué pasó, qué significa para un joven y un remate gracioso.\n'
        '- "comentario": UNA frase corta, irónica y fácil de entender sobre el día (máximo 25 palabras).\n'
        '- "imagen": el nombre de la empresa, persona pública, lugar o cosa principal del resumen, tal como se llamaría '
        'su artículo en Wikipedia en español (ej. "Ecopetrol", "Petróleo", "Banco de la República (Colombia)", "Peso colombiano").\n\n'
        "REGLAS (obligatorias): usa SOLO la información de los titulares; no inventes cifras ni datos. "
        f"Habla SOLO de noticias que pasan en {NOMBRE_PAIS[pais]} o que la afectan directamente; ignora las de otros países. "
        "La ironía va contra situaciones, mercados, instituciones o lo absurdo del día, NUNCA contra personas concretas, "
        "víctimas, tragedias, muertes, enfermedades ni grupos sociales. No tomes partido político ni ataques a políticos. "
        "Si una noticia es trágica, no hagas chistes sobre ella: elige otra. Español sencillo y neutro. "
        "Responde SOLO con el JSON, sin texto adicional."
    )
    respuesta = pedir_ia(instruccion)
    inicio, fin = respuesta.find("{"), respuesta.rfind("}")
    if inicio == -1 or fin == -1:
        raise RuntimeError(f"la IA no devolvió JSON. Respondió: {respuesta[:300]!r}")
    datos = json.loads(respuesta[inicio: fin + 1])
    resumen = {k: str(datos.get(k, "")).strip() for k in ("titulo", "resumen", "comentario")}
    resumen["imagen"] = buscar_imagen(str(datos.get("imagen", "")).strip())
    return resumen


def buscar_imagen(termino):
    """Busca la foto principal del artículo de Wikipedia en español (fotos con licencia libre)."""
    if not termino:
        return None
    h = {"User-Agent": "FinanzasExpress/1.0 (https://lemp200548.github.io/finanzas-today/)"}
    try:
        url = "https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "generator": "search", "gsrsearch": termino, "gsrlimit": 1,
            "prop": "pageimages|info", "piprop": "thumbnail", "pithumbsize": 900, "inprop": "url", "format": "json"})
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            paginas = json.loads(r.read()).get("query", {}).get("pages", {})
        for pag in paginas.values():
            foto = (pag.get("thumbnail") or {}).get("source")
            if foto:
                return {"url": foto, "pagina": pag.get("fullurl", ""), "titulo": pag.get("title", termino)}
    except Exception as e:
        print(f"Sin foto para '{termino}': {e}")
    return None


DEFINICIONES = {
    "Economía": "economía del país: dólar, inflación, tasas, PIB, empleo, impuestos, presupuesto",
    "Empresas": "empresas del país: resultados, ventas, inversiones, compras, fusiones, cierres, nuevos negocios",
    "Petróleo y energía": "petróleo, gas, minería, electricidad y energía del país",
    "Sector financiero": "bancos, bolsa, créditos, ahorro, CDT, seguros, fintech financieras del país",
    "Tecnología": "tecnología, apps, inteligencia artificial, telecomunicaciones, transformación digital en el país",
    "Emprendimiento": "startups, emprendedores, pymes, rondas de inversión en el país",
    "Nuevos CEO": "SOLO nombramientos o salidas de presidentes, CEOs o directivos de EMPRESAS (no de gobierno ni sindicatos)",
    "Consultoría": "firmas de consultoría y auditoría (McKinsey, Deloitte, EY, PwC, KPMG, etc.) y su actividad en el país",
    "Deportes": "SOLO deportes: equipos, deportistas, ligas o selecciones del país, o deportistas del país en el exterior",
    "Planes en Bogotá": "conciertos, festivales, ferias, restaurantes, eventos culturales en Bogotá",
    "Planes en Caracas": "conciertos, festivales, ferias, restaurantes, eventos culturales en Caracas",
}


def clasificar(pais, codigo, noticias):
    """La IA revisa cada titular: confirma la categoría, la cambia o lo descarta."""
    if not noticias:
        return noticias
    cats = list(PAISES[codigo]["categorias"].keys())
    defs = "\n".join(f"- {c}: {DEFINICIONES.get(c, c)}" for c in cats)
    lista = "\n".join(f"{i}. [{n['categoria']}] {n['titulo']}" for i, n in enumerate(noticias))
    instruccion = (
        f"Eres editor de un medio de noticias de negocios de {NOMBRE_PAIS[pais]}. Revisa estos titulares y su categoría.\n\n"
        f"Categorías válidas:\n{defs}\n\nTitulares:\n{lista}\n\n"
        "Para cada titular decide UNA de dos cosas:\n"
        "1. La categoría correcta (de la lista de arriba, escrita exactamente igual). Si está mal clasificado, cámbialo.\n"
        '2. "descartar".\n\n'
        "REGLA PRINCIPAL: el titular tiene que tratar EXPLÍCITAMENTE sobre " + NOMBRE_PAIS[pais] + ": mencionar el país, "
        "una ciudad, región, empresa, institución, equipo o persona de " + NOMBRE_PAIS[pais] + ". "
        "Si no lo menciona, DESCARTA, aunque sea un tema que 'podría afectar' al país.\n"
        "Descarta SIEMPRE: noticias de mercados globales (Wall Street, la Fed, Microsoft, Alphabet, bolsas de otros países), "
        "precios internacionales del petróleo que no mencionen al país, noticias de otros países o ciudades extranjeras, "
        "y política, judicial o diplomacia sin relación directa con economía o negocios.\n\n"
        "EJEMPLOS:\n"
        '- "Petróleo de Texas subió 1,90% tras ataque a refinería saudita" -> descartar (no menciona el país)\n'
        '- "Wall Street cierra en verde por compra masiva en el sector de la IA" -> descartar\n'
        '- "Reunión de la Fed y resultados de Microsoft y Alphabet" -> descartar\n'
        '- "Madrid, Centro Empresarial de Iberoamérica" -> descartar (otra ciudad)\n'
        '- "Asesor de Marco Rubio deja el Departamento de Estado" -> descartar (política de otro país)\n'
        '- "Navegantes del Magallanes va de mal en peor" -> Deportes (es béisbol, no economía)\n'
        '- "Playas de La Guaira reanudarán sus actividades" -> Planes (si existe esa categoría) o descartar\n'
        '- "Sindicatos petroleros piden mejores salarios en Venezuela" -> Petróleo y energía (no es Nuevos CEO)\n'
        '- "Inversores privados presentan plan para rescatar plantas de PDVSA" -> Petróleo y energía\n\n'
        "Ante la duda, descarta. Es mejor mostrar menos noticias que noticias que no son del país.\n"
        'Responde SOLO con JSON con esta forma: {"0": "Economía", "1": "descartar", ...} incluyendo todos los números.'
    )
    respuesta = pedir_ia(instruccion, max_tokens=4000)
    inicio, fin = respuesta.find("{"), respuesta.rfind("}")
    decisiones = json.loads(respuesta[inicio: fin + 1])
    salida, cuenta, descartadas = [], {}, 0
    for i, n in enumerate(noticias):
        cat = str(decisiones.get(str(i), n["categoria"])).strip()
        if cat not in cats:
            descartadas += 1
            continue
        if cuenta.get(cat, 0) >= POR_CATEGORIA:
            continue
        cuenta[cat] = cuenta.get(cat, 0) + 1
        salida.append({**n, "categoria": cat})
    print(f"[{codigo}] revisión IA: {len(salida)} noticias quedan, {descartadas} descartadas")
    return salida


def recortar(noticias):
    cuenta, salida = {}, []
    for n in noticias:
        if cuenta.get(n["categoria"], 0) < POR_CATEGORIA:
            cuenta[n["categoria"]] = cuenta.get(n["categoria"], 0) + 1
            salida.append(n)
    return salida


def resumen_de(paises):
    if not ANTHROPIC_KEY:
        print("Sin resumen: falta el secreto ANTHROPIC_API_KEY")
        return {}
    salida = {}
    for codigo, lista in paises.items():
        if not lista:
            continue
        try:
            salida[codigo] = resumir(codigo, lista)
            print(f"[{codigo}] resumen listo")
        except Exception as e:
            print(f"[{codigo}] resumen con error: {e}")
    return salida


def main():
    paises = {codigo: noticias_de(pais) for codigo, pais in PAISES.items()}
    for codigo in paises:
        if ANTHROPIC_KEY:
            try:
                paises[codigo] = clasificar(codigo, codigo, paises[codigo])
                continue
            except Exception as e:
                print(f"[{codigo}] revisión IA con error, se usan las noticias sin revisar: {e}")
        paises[codigo] = recortar(paises[codigo])
    salida = {"actualizado": datetime.now(COL).isoformat(), "paises": paises, "resumen": resumen_de(paises)}
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
