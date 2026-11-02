"""Sección MERCADOS de Finanzas Express.

Lo corre GitHub Actions varias veces al día (ver .github/workflows/markets.yml) y genera markets.json,
que es lo que lee mercados.html. No necesita librerías externas (solo Python estándar).

Qué hace:
 1. Baja 5 años de precios diarios de ~80 activos de todo el mundo (índices, sectores, acciones,
    materias primas, divisas, cripto y bonos) desde Yahoo Finance (con Stooq como respaldo).
 2. Calcula indicadores: rentabilidad 1D/1S/1M/3M/YTD/1A, volatilidad, RSI, medias de 50 y 200 días.
 3. MODELO TÉCNICO CALIBRADO: arma una puntuación de momentum/tendencia y mira en 5 años de historia
    qué tan seguido subieron los activos el mes siguiente cuando tenían una puntuación parecida.
    Eso da una PROBABILIDAD HISTÓRICA de subir en 1 mes y un rango probable de rentabilidad.
    La precisión se mide fuera de muestra (se calibra con el 70 % más antiguo y se evalúa con el 30 % reciente).
 4. NOTICIAS: lee titulares de Google News por tema (IA, bancos, petróleo, oro, China, Colombia...),
    les pone nota de sentimiento (con IA de Claude si hay ANTHROPIC_API_KEY, si no con diccionario)
    y los conecta con los activos de cada tema.
 5. CORRELACIÓN NOTICIAS→PRECIO: guarda cada día el sentimiento por tema y los precios en
    markets_history.json. Con el tiempo calcula cuánto se correlaciona el sentimiento de hoy con lo que
    hacen los precios después, y le da más o menos peso a las noticias según eso (aprende solo).
 6. Correlaciones entre activos (qué se mueve con qué) y un resumen del día con IA.

Nada de esto es asesoría financiera: son probabilidades estadísticas, no certezas.
"""
import json, math, os, re, sys, time, urllib.request, urllib.error, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

COL = timezone(timedelta(hours=-5))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SALIDA = "markets.json"
HISTORIAL = "markets_history.json"
HORIZONTE = 21          # días hábiles (~1 mes) para la probabilidad
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODELO = os.environ.get("MODELO_IA", "claude-haiku-5-5")

# ----------------------------------------------------------------------------------------------
# UNIVERSO DE ACTIVOS: (símbolo Yahoo, nombre, tipo, región, temas de noticias, símbolo Stooq de respaldo)
# ----------------------------------------------------------------------------------------------
ACTIVOS = [
    # Índices
    ("^GSPC", "S&P 500", "Índices", "EE. UU.", ["global", "fed"], "^spx"),
    ("^IXIC", "Nasdaq", "Índices", "EE. UU.", ["global", "tech", "fed"], "^ndq"),
    ("^DJI", "Dow Jones", "Índices", "EE. UU.", ["global", "fed"], "^dji"),
    ("^STOXX50E", "Euro Stoxx 50", "Índices", "Europa", ["europa"], None),
    ("^GDAXI", "DAX (Alemania)", "Índices", "Europa", ["europa"], "^dax"),
    ("^FTSE", "FTSE 100 (Reino Unido)", "Índices", "Europa", ["europa"], "^ukx"),
    ("^N225", "Nikkei 225 (Japón)", "Índices", "Asia", ["japon"], "^nkx"),
    ("^HSI", "Hang Seng (Hong Kong)", "Índices", "Asia", ["china"], "^hsi"),
    ("000001.SS", "Shanghai Composite", "Índices", "Asia", ["china"], None),
    ("^BSESN", "Sensex (India)", "Índices", "Asia", ["india"], None),
    ("^BVSP", "Bovespa (Brasil)", "Índices", "Latinoamérica", ["latam"], None),
    ("^MXX", "IPC (México)", "Índices", "Latinoamérica", ["latam"], None),
    # Países (ETF en dólares)
    ("GXG", "Colombia (ETF)", "Países", "Latinoamérica", ["colombia", "petroleo"], "gxg.us"),
    ("ECH", "Chile (ETF)", "Países", "Latinoamérica", ["chile", "cobre"], "ech.us"),
    ("EWZ", "Brasil (ETF)", "Países", "Latinoamérica", ["latam"], "ewz.us"),
    ("EWW", "México (ETF)", "Países", "Latinoamérica", ["latam"], "eww.us"),
    ("ARGT", "Argentina (ETF)", "Países", "Latinoamérica", ["latam"], "argt.us"),
    ("INDA", "India (ETF)", "Países", "Asia", ["india"], "inda.us"),
    ("FXI", "China (ETF)", "Países", "Asia", ["china"], "fxi.us"),
    ("EWJ", "Japón (ETF)", "Países", "Asia", ["japon"], "ewj.us"),
    ("EWY", "Corea del Sur (ETF)", "Países", "Asia", ["chips"], "ewy.us"),
    ("VGK", "Europa (ETF)", "Países", "Europa", ["europa"], "vgk.us"),
    ("EEM", "Emergentes (ETF)", "Países", "Global", ["global", "china", "latam"], "eem.us"),
    # Sectores (EE. UU., ETF)
    ("XLK", "Tecnología", "Sectores", "EE. UU.", ["tech", "ia"], "xlk.us"),
    ("SMH", "Semiconductores", "Sectores", "EE. UU.", ["chips", "ia"], "smh.us"),
    ("XLF", "Financiero / bancos", "Sectores", "EE. UU.", ["bancos", "fed"], "xlf.us"),
    ("XLE", "Energía / petróleo", "Sectores", "EE. UU.", ["petroleo"], "xle.us"),
    ("XLV", "Salud", "Sectores", "EE. UU.", ["salud"], "xlv.us"),
    ("XLI", "Industria", "Sectores", "EE. UU.", ["industria"], "xli.us"),
    ("ITA", "Defensa y aeroespacial", "Sectores", "EE. UU.", ["defensa"], "ita.us"),
    ("XLY", "Consumo (lujo, retail)", "Sectores", "EE. UU.", ["consumo"], "xly.us"),
    ("XLP", "Consumo básico", "Sectores", "EE. UU.", ["consumo"], "xlp.us"),
    ("XLU", "Servicios públicos", "Sectores", "EE. UU.", ["fed", "limpia"], "xlu.us"),
    ("XLB", "Materiales", "Sectores", "EE. UU.", ["cobre", "industria"], "xlb.us"),
    ("XLRE", "Inmobiliario", "Sectores", "EE. UU.", ["inmobiliario", "fed"], "xlre.us"),
    ("XLC", "Comunicaciones / redes", "Sectores", "EE. UU.", ["tech"], "xlc.us"),
    ("ICLN", "Energía limpia", "Sectores", "Global", ["limpia"], "icln.us"),
    ("URA", "Uranio / nuclear", "Sectores", "Global", ["limpia", "ia"], "ura.us"),
    ("LIT", "Litio y baterías", "Sectores", "Global", ["cobre", "limpia"], "lit.us"),
    # Acciones
    ("NVDA", "Nvidia", "Acciones", "EE. UU.", ["chips", "ia"], "nvda.us"),
    ("MSFT", "Microsoft", "Acciones", "EE. UU.", ["tech", "ia"], "msft.us"),
    ("AAPL", "Apple", "Acciones", "EE. UU.", ["tech"], "aapl.us"),
    ("GOOGL", "Alphabet (Google)", "Acciones", "EE. UU.", ["tech", "ia"], "googl.us"),
    ("AMZN", "Amazon", "Acciones", "EE. UU.", ["tech", "consumo"], "amzn.us"),
    ("META", "Meta", "Acciones", "EE. UU.", ["tech", "ia"], "meta.us"),
    ("TSLA", "Tesla", "Acciones", "EE. UU.", ["tech", "limpia"], "tsla.us"),
    ("JPM", "JPMorgan", "Acciones", "EE. UU.", ["bancos"], "jpm.us"),
    ("LLY", "Eli Lilly", "Acciones", "EE. UU.", ["salud"], "lly.us"),
    ("TSM", "TSMC (Taiwán)", "Acciones", "Asia", ["chips", "ia"], "tsm.us"),
    ("MELI", "Mercado Libre", "Acciones", "Latinoamérica", ["latam", "consumo"], "meli.us"),
    ("NU", "Nubank", "Acciones", "Latinoamérica", ["latam", "bancos"], "nu.us"),
    ("EC", "Ecopetrol", "Acciones", "Latinoamérica", ["colombia", "petroleo"], "ec.us"),
    ("CIB", "Bancolombia", "Acciones", "Latinoamérica", ["colombia", "bancos"], "cib.us"),
    ("SQM", "SQM (litio, Chile)", "Acciones", "Latinoamérica", ["chile", "cobre"], "sqm.us"),
    ("PBR", "Petrobras", "Acciones", "Latinoamérica", ["latam", "petroleo"], "pbr.us"),
    # Materias primas
    ("GC=F", "Oro", "Materias primas", "Global", ["oro"], "gc.f"),
    ("SI=F", "Plata", "Materias primas", "Global", ["oro"], "si.f"),
    ("CL=F", "Petróleo WTI", "Materias primas", "Global", ["petroleo"], "cl.f"),
    ("BZ=F", "Petróleo Brent", "Materias primas", "Global", ["petroleo"], None),
    ("NG=F", "Gas natural", "Materias primas", "Global", ["petroleo"], "ng.f"),
    ("HG=F", "Cobre", "Materias primas", "Global", ["cobre", "china"], "hg.f"),
    ("KC=F", "Café", "Materias primas", "Global", ["cafe", "colombia"], "kc.f"),
    ("ZS=F", "Soya", "Materias primas", "Global", ["agro"], "zs.f"),
    ("ZW=F", "Trigo", "Materias primas", "Global", ["agro"], "zw.f"),
    # Divisas (sube = el dólar se encarece frente a esa moneda)
    ("DX-Y.NYB", "Índice dólar (DXY)", "Divisas", "Global", ["dolar", "fed"], None),
    ("EURUSD=X", "Euro / dólar", "Divisas", "Europa", ["europa", "dolar"], "eurusd"),
    ("USDCOP=X", "Dólar en Colombia (COP)", "Divisas", "Latinoamérica", ["colombia", "dolar"], "usdcop"),
    ("USDCLP=X", "Dólar en Chile (CLP)", "Divisas", "Latinoamérica", ["chile", "dolar"], "usdclp"),
    ("USDMXN=X", "Dólar en México (MXN)", "Divisas", "Latinoamérica", ["latam", "dolar"], "usdmxn"),
    ("USDBRL=X", "Dólar en Brasil (BRL)", "Divisas", "Latinoamérica", ["latam", "dolar"], "usdbrl"),
    ("USDJPY=X", "Dólar / yen", "Divisas", "Asia", ["japon", "dolar"], "usdjpy"),
    # Cripto
    ("BTC-USD", "Bitcoin", "Cripto", "Global", ["cripto"], "btcusd"),
    ("ETH-USD", "Ethereum", "Cripto", "Global", ["cripto"], "ethusd"),
    ("SOL-USD", "Solana", "Cripto", "Global", ["cripto"], None),
    # Bonos y tasas
    ("TLT", "Bonos EE. UU. 20+ años", "Bonos", "EE. UU.", ["fed"], "tlt.us"),
    ("^TNX", "Tasa bono 10 años EE. UU.", "Bonos", "EE. UU.", ["fed"], None),
    ("HYG", "Bonos corporativos (high yield)", "Bonos", "EE. UU.", ["fed", "bancos"], "hyg.us"),
]
# En estos "subir" no significa ganar plata invirtiendo en ellos (son precios de divisas o tasas)
NO_INVERTIBLES = {"Divisas", "^TNX"}

# Activos que se muestran en la matriz de correlaciones
CLAVE_CORR = ["^GSPC", "^IXIC", "VGK", "^N225", "FXI", "EWZ", "GXG", "ECH", "GC=F", "CL=F", "HG=F", "KC=F",
              "BTC-USD", "DX-Y.NYB", "USDCOP=X", "TLT"]

# GRÁFICAS DE VELAS POR PAÍS: clave -> (nombre en la pestaña, activos que se grafican, en orden)
PAISES_GRAFICAS = [
    ("co", "🇨🇴 Colombia", ["GXG", "USDCOP=X", "EC", "CIB", "KC=F", "CL=F"]),
    ("cl", "🇨🇱 Chile", ["ECH", "USDCLP=X", "SQM", "HG=F", "LIT"]),
    ("us", "🇺🇸 EE. UU.", ["^GSPC", "^IXIC", "^DJI", "NVDA", "XLK", "TLT"]),
    ("br", "🇧🇷 Brasil", ["^BVSP", "EWZ", "USDBRL=X", "PBR", "NU", "MELI"]),
    ("mx", "🇲🇽 México", ["^MXX", "EWW", "USDMXN=X"]),
    ("ar", "🇦🇷 Argentina", ["ARGT", "MELI"]),
    ("eu", "🇪🇺 Europa", ["^STOXX50E", "^GDAXI", "^FTSE", "VGK", "EURUSD=X"]),
    ("cn", "🇨🇳 China", ["000001.SS", "^HSI", "FXI", "HG=F"]),
    ("jp", "🇯🇵 Japón", ["^N225", "EWJ", "USDJPY=X"]),
    ("in", "🇮🇳 India", ["^BSESN", "INDA"]),
    ("as", "🇰🇷 Corea y Taiwán", ["EWY", "TSM"]),
    ("cr", "₿ Cripto", ["BTC-USD", "ETH-USD", "SOL-USD"]),
    ("mp", "🛢️ Materias primas", ["GC=F", "CL=F", "HG=F", "KC=F", "SI=F", "NG=F"]),
]

# ----------------------------------------------------------------------------------------------
# TEMAS DE NOTICIAS: clave -> (nombre, búsqueda en inglés, búsqueda en español)
# ----------------------------------------------------------------------------------------------
TEMAS = {
    "global": ("Mercado global", '"stock market" OR "Wall Street" OR stocks OR equities', '"Wall Street" OR bolsas OR "mercados financieros"'),
    "fed": ("Tasas y Reserva Federal", '"Federal Reserve" OR Fed OR "interest rates" OR Treasury yields OR inflation', '"Reserva Federal" OR "tasas de interés" OR inflación Estados Unidos'),
    "tech": ("Big Tech", 'Apple OR Microsoft OR Alphabet OR Amazon OR Meta OR "big tech"', '"gigantes tecnológicos" OR Apple OR Microsoft OR Amazon'),
    "ia": ("Inteligencia artificial", '"artificial intelligence" OR "AI stocks" OR OpenAI OR "AI spending" OR "data centers"', '"inteligencia artificial" inversión OR "centros de datos"'),
    "chips": ("Semiconductores", 'Nvidia OR semiconductor OR chips OR TSMC OR AMD OR Broadcom', 'semiconductores OR chips OR Nvidia'),
    "bancos": ("Bancos", 'banks OR "bank earnings" OR JPMorgan OR lenders OR "credit"', 'bancos OR banca utilidades'),
    "petroleo": ("Petróleo y gas", 'oil prices OR OPEC OR crude OR Brent OR "natural gas"', 'petróleo OR OPEP OR crudo OR Brent'),
    "oro": ("Oro y plata", 'gold prices OR "gold price" OR silver OR "safe haven"', 'oro precio OR plata OR "refugio"'),
    "cobre": ("Cobre y litio", 'copper OR lithium OR "metal prices" OR mining', 'cobre OR litio OR minería precios'),
    "cripto": ("Cripto", 'bitcoin OR ethereum OR crypto OR "crypto ETF"', 'bitcoin OR criptomonedas OR ethereum'),
    "salud": ("Salud y farma", 'pharma OR biotech OR "drug approval" OR "Eli Lilly" OR "weight loss drug"', 'farmacéuticas OR biotecnología OR "Eli Lilly"'),
    "consumo": ("Consumo y retail", 'retail sales OR "consumer spending" OR retailers OR "consumer confidence"', '"consumo" OR "ventas minoristas" OR retail'),
    "industria": ("Industria", 'manufacturing OR PMI OR industrials OR "factory orders"', 'manufactura OR industria OR PMI'),
    "defensa": ("Defensa", '"defense stocks" OR "defense spending" OR Lockheed OR NATO spending', '"gasto en defensa" OR armamento OR OTAN'),
    "inmobiliario": ("Inmobiliario", '"housing market" OR "real estate" OR "mortgage rates" OR REIT', '"mercado inmobiliario" OR vivienda OR hipotecas'),
    "limpia": ("Energía limpia y nuclear", '"renewable energy" OR solar OR "nuclear power" OR uranium OR "electric vehicles"', '"energías renovables" OR solar OR nuclear OR "carros eléctricos"'),
    "dolar": ("Dólar", '"US dollar" OR "dollar index" OR forex OR currencies', 'dólar OR divisas OR "tipo de cambio"'),
    "europa": ("Europa", '"European stocks" OR ECB OR "euro zone" OR DAX OR "Stoxx 600"', '"Banco Central Europeo" OR "bolsas europeas" OR eurozona'),
    "china": ("China", 'China economy OR "Chinese stocks" OR "Hang Seng" OR Beijing stimulus', 'China economía OR "bolsa china" OR estímulos China'),
    "japon": ("Japón", 'Japan stocks OR Nikkei OR "Bank of Japan" OR yen', 'Japón OR Nikkei OR yen'),
    "india": ("India", 'India stocks OR Sensex OR Nifty OR "Indian economy"', 'India economía OR Sensex'),
    "latam": ("Latinoamérica", '"Latin America" markets OR Brazil OR Mexico OR "emerging markets"', 'Latinoamérica mercados OR Brasil OR México OR emergentes'),
    "colombia": ("Colombia", 'Colombia economy OR Colombian peso OR Ecopetrol', 'Colombia dólar OR "Banco de la República" OR Ecopetrol OR "Bolsa de Colombia"'),
    "chile": ("Chile", 'Chile economy OR Chilean peso OR Codelco', 'Chile dólar OR "Banco Central de Chile" OR Codelco OR IPSA'),
    "cafe": ("Café", 'coffee prices OR arabica OR "coffee futures"', 'café precio OR "precio del café"'),
    "agro": ("Agro", 'wheat OR soybeans OR corn prices OR grains', 'trigo OR soya OR maíz precios'),
}

# ----------------------------------------------------------------------------------------------
# DICCIONARIO DE SENTIMIENTO (respaldo si no hay IA)
# ----------------------------------------------------------------------------------------------
POSITIVAS = """surge surges surged soar soars soared rally rallies rallied jump jumps jumped gain gains gained rise rises
rising rose climb climbs climbed record high highs beat beats boost boosts boosted upgrade upgrades upgraded strong
stronger growth grows grew bullish rebound rebounds rebounded recovery optimism optimistic outperform outperforms
expands expansion profit profits profitable win wins approval approved deal breakthrough easing stimulus
best top advance advances advanced higher
sube suben subió subieron alza alzas dispara disparan disparó récord gana ganan ganó ganancias crece crecen creció
crecimiento repunta repunte recupera recuperación optimismo máximo máximos impulsa impulso mejora mejoró fuerte
aprobación acuerdo avanza avanzan avance estímulo valoriza valorizó""".split()
NEGATIVAS = """fall falls fell drop drops dropped plunge plunges plunged slump slumps slumped sink sinks sank tumble
tumbles tumbled slide slides slid crash crashes loss losses lose loses weak weaker weakness miss misses missed
downgrade downgrades downgraded bearish fear fears worry worries concern concerns risk risks recession slowdown
layoffs warning warns probe lawsuit tariff tariffs sanctions selloff sell-off decline declines declined lower
lowest crisis default inflation volatile volatility turmoil war hike hikes shortage bubble
cae caen cayó cayeron caída baja bajan bajó desploma desplome pierde pierden pérdidas perdió débil debilidad
recesión desaceleración temor temores miedo riesgo riesgos crisis aranceles arancel sanciones despidos guerra
mínimo mínimos incertidumbre volatilidad inflación alerta advierte quiebra""".split()
POS, NEG = set(POSITIVAS), set(NEGATIVAS)


def sentimiento_lexico(titulo):
    palabras = re.findall(r"[a-záéíóúñ\-]+", titulo.lower())
    p = sum(1 for w in palabras if w in POS)
    n = sum(1 for w in palabras if w in NEG)
    return 0.0 if p + n == 0 else (p - n) / (p + n)


# ----------------------------------------------------------------------------------------------
# DESCARGA DE DATOS
# ----------------------------------------------------------------------------------------------
def http(url, timeout=30, intentos=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,es;q=0.8"})
    ultimo = None
    for i in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            ultimo = e
            time.sleep(2 * (i + 1))
    raise ultimo


YAHOO_FALLOS = [0]  # si Yahoo falla muchas veces seguidas, se deja de intentar y se usa Stooq directo


def precios_yahoo(sym):
    """Devuelve (serie [(fecha, cierre)], velas [[fecha, apertura, máximo, mínimo, cierre]], moneda)."""
    if YAHOO_FALLOS[0] >= 6:
        return None, None, ""
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=5y&interval=1d&includePrePost=false"
        try:
            d = json.loads(http(url, timeout=15, intentos=2))
            res = d["chart"]["result"][0]
            ts = res.get("timestamp") or []
            q = res["indicators"]["quote"][0]
            cierres = q.get("close") or []
            n = len(cierres)
            aperturas = q.get("open") or [None] * n
            maximos = q.get("high") or [None] * n
            minimos = q.get("low") or [None] * n
            serie, velas, vistos = [], [], set()
            for t, o, h, l, c in zip(ts, aperturas, maximos, minimos, cierres):
                if c is None or c <= 0:
                    continue
                f = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
                o = o if o and o > 0 else c
                h = max(h if h and h > 0 else c, o, c)
                l = min(l if l and l > 0 else c, o, c)
                if f in vistos:
                    serie[-1] = (f, float(c))
                    velas[-1] = [f, velas[-1][1], max(velas[-1][2], h), min(velas[-1][3], l), float(c)]
                    continue
                vistos.add(f)
                serie.append((f, float(c)))
                velas.append([f, float(o), float(h), float(l), float(c)])
            if len(serie) > 60:
                YAHOO_FALLOS[0] = 0
                return serie, velas, res.get("meta", {}).get("currency", "")
        except Exception as e:
            print(f"  yahoo {host} {sym}: {e}")
    YAHOO_FALLOS[0] += 1
    return None, None, ""


STOOQ_FALLOS = [0]


def precios_stooq(sym):
    if STOOQ_FALLOS[0] >= 6:
        return None, None
    url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&i=d"
    try:
        texto = http(url, timeout=20, intentos=2).decode()
    except Exception as e:
        print(f"  stooq {sym}: {e}")
        STOOQ_FALLOS[0] += 1
        return None, None
    filas = texto.strip().splitlines()[1:]
    desde = (datetime.now() - timedelta(days=5 * 366)).strftime("%Y-%m-%d")
    serie, velas = [], []
    for fila in filas:
        partes = fila.split(",")
        if len(partes) >= 5 and partes[0] >= desde:
            try:
                o, h, l, c = (float(x) for x in partes[1:5])
                serie.append((partes[0], c))
                velas.append([partes[0], o, max(h, o, c), min(l, o, c), c])
            except ValueError:
                pass
    if len(serie) > 60:
        STOOQ_FALLOS[0] = 0
        return serie, velas
    STOOQ_FALLOS[0] += 1
    return None, None


def descargar_precios():
    datos = {}
    for sym, nombre, tipo, region, temas, stooq in ACTIVOS:
        serie, velas, moneda = precios_yahoo(sym)
        if not serie and stooq:
            serie, velas = precios_stooq(stooq)
            moneda = ""
        if serie:
            datos[sym] = {"serie": serie, "velas": velas, "moneda": moneda}
            print(f"[precios] {nombre}: {len(serie)} días")
        else:
            print(f"[precios] {nombre}: SIN DATOS")
        time.sleep(0.25)
    return datos


def buscar_noticias(q, idioma):
    if idioma == "en":
        params = {"q": f"({q}) when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    else:
        params = {"q": f"({q}) when:2d", "hl": "es-419", "gl": "CO", "ceid": "CO:es-419"}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    try:
        raiz = ET.fromstring(http(url))
    except Exception as e:
        print(f"  noticias '{q[:40]}': {e}")
        return []
    salida = []
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        fuente = (item.findtext("source") or "").strip()
        if fuente and titulo.endswith(" - " + fuente):
            titulo = titulo[: -len(" - " + fuente)]
        try:
            fecha = parsedate_to_datetime(item.findtext("pubDate")).astimezone(COL).isoformat()
        except Exception:
            fecha = None
        salida.append({"titulo": titulo, "fuente": fuente, "link": (item.findtext("link") or "").strip(),
                       "fecha": fecha, "idioma": idioma})
    time.sleep(1)
    return salida


def descargar_noticias():
    temas = {}
    vistos = set()
    for clave, (nombre, q_en, q_es) in TEMAS.items():
        items = buscar_noticias(q_en, "en")[:12] + buscar_noticias(q_es, "es")[:8]
        unicos = []
        for it in items:
            k = re.sub(r"\W+", "", it["titulo"].lower())[:70]
            if not it["titulo"] or k in vistos:
                continue
            vistos.add(k)
            it["s"] = round(sentimiento_lexico(it["titulo"]), 2)
            unicos.append(it)
        unicos.sort(key=lambda n: n["fecha"] or "", reverse=True)
        temas[clave] = unicos[:14]
        print(f"[noticias] {nombre}: {len(temas[clave])}")
    return temas


# ----------------------------------------------------------------------------------------------
# IA (Claude) — opcional
# ----------------------------------------------------------------------------------------------
def pedir_ia(instruccion, max_tokens=4000):
    def llamar(extra, tokens):
        body = json.dumps({"model": MODELO, "max_tokens": tokens, **extra,
                           "messages": [{"role": "user", "content": instruccion}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
            "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    try:
        res = llamar({"thinking": {"type": "disabled"}}, max_tokens)
    except urllib.error.HTTPError as e:
        if e.code == 400:
            res = llamar({}, max_tokens * 4)
        else:
            raise RuntimeError(f"la API respondió {e.code}: {e.read().decode(errors='ignore')[:300]}")
    texto = "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text").strip()
    i, f = texto.find("{"), texto.rfind("}")
    if i == -1 or f == -1:
        raise RuntimeError(f"la IA no devolvió JSON: {texto[:200]!r}")
    return json.loads(texto[i: f + 1])


def sentimiento_ia(noticias):
    """La IA lee los titulares y pone nota de -1 a 1 a cada tema y a cada titular."""
    bloques, idx = [], []
    for clave, items in noticias.items():
        if not items:
            continue
        lineas = []
        for j, it in enumerate(items[:10]):
            idx.append((clave, j))
            lineas.append(f"  {len(idx)}. {it['titulo']}")
        bloques.append(f"[{clave}] {TEMAS[clave][0]}\n" + "\n".join(lineas))
    if not bloques:
        return
    instruccion = (
        "Eres analista de mercados. Para cada titular, evalúa si es POSITIVO o NEGATIVO para los precios de los "
        "activos de su tema en las próximas semanas (no si es buena noticia en general: por ejemplo, 'suben las tasas' "
        "es negativo para acciones e inmobiliario; 'sube el petróleo' es positivo para el tema petróleo; "
        "'el dólar se dispara' es positivo para el tema dólar).\n\n" + "\n\n".join(bloques) +
        "\n\nResponde SOLO con JSON: {\"titulares\": {\"1\": nota, \"2\": nota, ...}, \"temas\": {\"clave\": nota, ...}} "
        "donde cada nota es un número entre -1 (muy negativo) y 1 (muy positivo), 0 si es neutro."
    )
    try:
        r = pedir_ia(instruccion, 6000)
    except Exception as e:
        print(f"[IA] sentimiento falló, se usa diccionario: {e}")
        return
    for k, v in (r.get("titulares") or {}).items():
        try:
            clave, j = idx[int(k) - 1]
            noticias[clave][j]["s"] = round(max(-1, min(1, float(v))), 2)
        except Exception:
            pass
    print("[IA] sentimiento de titulares listo")


def resumen_ia(salida):
    activos = {a["sym"]: a for a in salida["activos"]}
    def linea(a):
        return (f"{a['nombre']} ({a['tipo']}): 1D {a['r1d']:+.1f}%, 1M {a['r21d']:+.1f}%, 3M {a['r63d']:+.1f}%, "
                f"prob. subir 1 mes {round(a['p']*100)}%, noticias {a['noticias']:+.2f}")
    top = [linea(activos[s]) for s in salida["top_subir"]]
    bajo = [linea(activos[s]) for s in salida["top_bajar"]]
    sect = [linea(activos[s["sym"]]) for s in salida["sectores"]]
    temas = [f"{t['nombre']}: sentimiento {t['sent']:+.2f}; titulares: " + " | ".join(n["titulo"] for n in t["titulares"][:4])
             for t in salida["temas"] if t["titulares"]]
    instruccion = (
        "Eres el editor de mercados de Finanzas Express, un newsletter para jóvenes latinoamericanos (Colombia, Chile, "
        "Venezuela). Explica el mercado mundial en español sencillo, directo y con algo de humor, como Morning Brew.\n\n"
        "DATOS DEL MODELO (probabilidades calculadas con 5 años de historia + sentimiento de noticias):\n"
        "Con mayor probabilidad de subir:\n" + "\n".join(top) +
        "\n\nCon mayor probabilidad de bajar:\n" + "\n".join(bajo) +
        "\n\nSectores:\n" + "\n".join(sect) +
        "\n\nNoticias por tema:\n" + "\n".join(temas) +
        "\n\nEscribe JSON con estas claves:\n"
        '- "titulo": titular corto con gancho (máx 9 palabras).\n'
        '- "resumen": 3-4 frases (máx 90 palabras): qué está pasando en los mercados del mundo hoy y por qué.\n'
        '- "creciendo": lista de 3-4 frases cortas: qué está creciendo AHORA y por qué (cita la noticia o el dato).\n'
        '- "puede_crecer": lista de 3-4 frases: qué PUEDE crecer en las próximas semanas, con su probabilidad en % del modelo.\n'
        '- "riesgos": lista de 2-3 frases: qué puede salir mal o qué está bajando.\n'
        '- "latam": 1-2 frases sobre qué significa para Colombia/Chile/Latinoamérica (dólar, petróleo, cobre, café).\n'
        "REGLAS: usa SOLO los datos y titulares dados, no inventes cifras. Usa las probabilidades tal cual vienen. "
        "Nunca prometas ganancias ni digas 'compra'/'vende' como orden; habla de probabilidades. "
        "Responde SOLO con el JSON."
    )
    try:
        r = pedir_ia(instruccion, 3000)
        out = {k: r.get(k) for k in ("titulo", "resumen", "creciendo", "puede_crecer", "riesgos", "latam")}
        out["fuente"] = "ia"
        return out
    except Exception as e:
        print(f"[IA] resumen falló, se usa el automático: {e}")
        return None


# ----------------------------------------------------------------------------------------------
# CÁLCULOS
# ----------------------------------------------------------------------------------------------
def acumulado(xs):
    s = [0.0]
    for x in xs:
        s.append(s[-1] + x)
    return s


class Indicadores:
    """Precalcula sumas acumuladas para obtener indicadores en cualquier día t en O(1)."""
    def __init__(self, cierres):
        self.c = cierres
        self.r = [0.0] + [math.log(cierres[i] / cierres[i - 1]) for i in range(1, len(cierres))]
        self.S = acumulado(cierres)
        self.R = acumulado(self.r)
        self.R2 = acumulado([x * x for x in self.r])
        sube = [0.0] + [max(0.0, cierres[i] - cierres[i - 1]) for i in range(1, len(cierres))]
        baja = [0.0] + [max(0.0, cierres[i - 1] - cierres[i]) for i in range(1, len(cierres))]
        self.G, self.L = acumulado(sube), acumulado(baja)

    def sma(self, t, n):
        return (self.S[t + 1] - self.S[t + 1 - n]) / n

    def vol(self, t, n=63):
        m = (self.R[t + 1] - self.R[t + 1 - n]) / n
        v = (self.R2[t + 1] - self.R2[t + 1 - n]) / n - m * m
        return math.sqrt(max(v, 1e-12) * 252)

    def rsi(self, t, n=14):
        g = self.G[t + 1] - self.G[t + 1 - n]
        l = self.L[t + 1] - self.L[t + 1 - n]
        return 50.0 if g + l == 0 else 100 * g / (g + l)

    def ret(self, t, n):
        return self.c[t] / self.c[t - n] - 1

    def puntaje(self, t):
        """Puntaje técnico de -1 (muy bajista) a 1 (muy alcista). Requiere t >= 252."""
        vol = max(self.vol(t), 0.03)
        m3 = self.ret(t, 63) / (vol * math.sqrt(63 / 252))           # momentum 3 meses ajustado por riesgo
        m12 = ((1 + self.ret(t, 252)) / (1 + self.ret(t, 21)) - 1) / vol  # momentum 12-1 meses
        p, s50, s200 = self.c[t], self.sma(t, 50), self.sma(t, 200)
        tendencia = (0.5 if p > s200 else -0.5) + (0.5 if s50 > s200 else -0.5)
        rsi = self.rsi(t)
        extremo = -(rsi - 70) / 30 if rsi > 70 else (30 - rsi) / 30 if rsi < 30 else 0.0
        return 0.35 * math.tanh(m3 / 1.5) + 0.25 * math.tanh(m12) + 0.25 * tendencia + 0.15 * extremo


def percentil(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def calibrar(precios):
    """Arma el 'mapa' puntaje -> probabilidad de subir a 1 mes, con toda la historia de todos los activos.
    Se calibra con el 70 % más antiguo y se mide la precisión con el 30 % más reciente (fuera de muestra)."""
    muestras = []  # (fecha, puntaje, rent_futura, sym)
    base = {}
    for sym, d in precios.items():
        if sym in NO_INVERTIBLES or tipo_de(sym) in NO_INVERTIBLES:
            continue
        c = [x[1] for x in d["serie"]]
        fechas = [x[0] for x in d["serie"]]
        if len(c) < 252 + HORIZONTE + 30:
            continue
        ind = Indicadores(c)
        subidas = total = 0
        for t in range(252, len(c) - HORIZONTE, 5):
            fut = c[t + HORIZONTE] / c[t] - 1
            muestras.append((fechas[t], ind.puntaje(t), fut, sym))
            subidas += fut > 0
            total += 1
        base[sym] = subidas / total if total else 0.5
    if len(muestras) < 200:
        return None
    muestras.sort(key=lambda m: m[0])
    corte = int(len(muestras) * 0.7)
    entreno, prueba = muestras[:corte], muestras[corte:]

    def armar(ms):
        puntajes = sorted(m[1] for m in ms)
        bordes = [percentil(puntajes, q / 10) for q in range(1, 10)]
        bins = [[] for _ in range(10)]
        for m in ms:
            bins[sum(m[1] > b for b in bordes)].append(m[2])
        tabla = []
        for b in bins:
            tabla.append({"p": sum(x > 0 for x in b) / len(b) if b else 0.5,
                          "p25": percentil(b, 0.25), "p50": percentil(b, 0.5), "p75": percentil(b, 0.75), "n": len(b)})
        global_up = sum(m[2] > 0 for m in ms) / len(ms)
        return {"bordes": bordes, "tabla": tabla, "base": global_up}

    mapa_entreno = armar(entreno)
    # Precisión fuera de muestra: cuando el modelo dice >=60 % o <=40 %, ¿acertó la dirección?
    aciertos = señales = 0
    for f, s, fut, sym in prueba:
        b = mapa_entreno["tabla"][sum(s > x for x in mapa_entreno["bordes"])]
        p = b["p"] + (base.get(sym, 0.5) - mapa_entreno["base"])
        if p >= 0.6 or p <= 0.4:
            señales += 1
            aciertos += (p >= 0.6) == (fut > 0)
    mapa = armar(muestras)  # el mapa final usa toda la historia
    mapa["base_activo"] = base
    mapa["precision"] = round(aciertos / señales, 3) if señales else None
    mapa["senales_prueba"] = señales
    mapa["muestras"] = len(muestras)
    mapa["desde"] = muestras[0][0]
    # Ganancia del modelo frente a "siempre decir que sube"
    mapa["base_prueba"] = round(sum(m[2] > 0 for m in prueba) / len(prueba), 3)
    return mapa


def tipo_de(sym):
    for a in ACTIVOS:
        if a[0] == sym:
            return a[2]
    return ""


def correlacion(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return None if sx == 0 or sy == 0 else sxy / (sx * sy)


def retornos_diarios(serie, n=126):
    """dict fecha -> retorno log diario de los últimos n días."""
    s = serie[-(n + 1):]
    return {s[i][0]: math.log(s[i][1] / s[i - 1][1]) for i in range(1, len(s))}


def corr_pares(ra, rb):
    comunes = sorted(set(ra) & set(rb))
    if len(comunes) < 30:
        return None
    return correlacion([ra[f] for f in comunes], [rb[f] for f in comunes])


# ----------------------------------------------------------------------------------------------
# HISTORIAL: aprende la relación noticias -> precio
# ----------------------------------------------------------------------------------------------
def cargar_historial():
    try:
        with open(HISTORIAL, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_historial(hist, hoy, sent_temas, precios_hoy, probs):
    hist = [h for h in hist if h["fecha"] != hoy]
    hist.append({"fecha": hoy, "sent": sent_temas, "px": precios_hoy, "p": probs})
    hist.sort(key=lambda h: h["fecha"])
    hist = hist[-400:]
    with open(HISTORIAL, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
    return hist


def aprender_noticias(hist):
    """Para cada tema: correlación entre el sentimiento de un día y el retorno de sus activos en los 5 días siguientes."""
    activos_por_tema = {k: [a[0] for a in ACTIVOS if k in a[4] and a[2] not in NO_INVERTIBLES and a[0] not in NO_INVERTIBLES]
                        for k in TEMAS}
    resultado = {}
    for tema, syms in activos_por_tema.items():
        xs, ys = [], []
        for i, h in enumerate(hist):
            j = i + 5
            if j >= len(hist) or tema not in h.get("sent", {}):
                continue
            rets = [hist[j]["px"][s] / h["px"][s] - 1 for s in syms
                    if s in h.get("px", {}) and s in hist[j].get("px", {}) and h["px"][s]]
            if rets:
                xs.append(h["sent"][tema])
                ys.append(sum(rets) / len(rets))
        c = correlacion(xs, ys) if len(xs) >= 10 else None
        resultado[tema] = {"corr": round(c, 3) if c is not None else None, "n": len(xs)}
    return resultado


def aciertos_en_vivo(hist, precios_hoy):
    """Compara las probabilidades de hace ~1 mes (21+ registros diarios atrás) con lo que realmente pasó."""
    if not hist:
        return None
    limite = (datetime.now(COL) - timedelta(days=30)).strftime("%Y-%m-%d")
    viejos = [h for h in hist if h["fecha"] <= limite and h.get("p")]
    if not viejos:
        return None
    h = viejos[-1]
    ok = total = 0
    for s, p in h["p"].items():
        if s in h["px"] and s in precios_hoy and (p >= 0.6 or p <= 0.4):
            total += 1
            ok += (p >= 0.6) == (precios_hoy[s] > h["px"][s])
    return {"desde": h["fecha"], "aciertos": ok, "total": total, "tasa": round(ok / total, 3) if total else None}


# ----------------------------------------------------------------------------------------------
# PRINCIPAL
# ----------------------------------------------------------------------------------------------
def sig(x, cifras=5):
    """Redondea a 5 cifras significativas (para que markets.json no pese tanto)."""
    if not x:
        return x
    return round(x, max(0, cifras - 1 - int(math.floor(math.log10(abs(x))))))


def r(x, n=2):
    return None if x is None else round(x, n)


def armar_salida(precios, noticias, hist):
    ahora = datetime.now(COL)
    hoy = ahora.strftime("%Y-%m-%d")
    mapa = calibrar(precios)

    # Sentimiento por tema (promedio encogido hacia 0 si hay pocos titulares)
    sent_temas = {}
    for k, items in noticias.items():
        ss = [it["s"] for it in items]
        sent_temas[k] = round(sum(ss) / (len(ss) + 3), 3) if ss else 0.0

    aprendido = aprender_noticias(hist)
    activos = []
    retornos = {}
    for sym, nombre, tipo, region, temas, _ in ACTIVOS:
        d = precios.get(sym)
        if not d:
            continue
        serie = d["serie"]
        c = [x[1] for x in serie]
        t = len(c) - 1
        if t < 30:
            continue
        ind = Indicadores(c)
        retornos[sym] = retornos_diarios(serie)
        def ret(n):
            return (c[t] / c[t - n] - 1) * 100 if t >= n else None
        ano = serie[-1][0][:4]
        prev = [x for x in serie if x[0][:4] < ano]
        ytd = (c[t] / prev[-1][1] - 1) * 100 if prev else None
        vol = ind.vol(t) if t > 63 else None
        rsi = ind.rsi(t) if t > 14 else 50
        s200 = ind.sma(t, 200) if t >= 200 else None
        s50 = ind.sma(t, 50) if t >= 50 else None
        max52 = max(c[-252:]); min52 = min(c[-252:])

        # Sentimiento de noticias del activo = promedio de sus temas
        sn = sum(sent_temas.get(k, 0) for k in temas) / len(temas) if temas else 0
        # Peso de las noticias: base 0.10; si el historial muestra que el tema SÍ anticipa precios, sube hasta 0.25
        corrs = [aprendido[k]["corr"] for k in temas if aprendido.get(k, {}).get("corr") is not None]
        peso_noticias = 0.10 + (0.15 * max(0, sum(corrs) / len(corrs)) if corrs else 0)

        puntaje = ind.puntaje(t) if t >= 252 else None
        p, rango, p_hist = 0.5, None, None
        if mapa and puntaje is not None:
            b = mapa["tabla"][sum(puntaje > x for x in mapa["bordes"])]
            base_a = mapa["base_activo"].get(sym, mapa["base"])
            p_hist = max(0.05, min(0.95, b["p"] + (base_a - mapa["base"])))
            rango = [r(b["p25"] * 100, 1), r(b["p50"] * 100, 1), r(b["p75"] * 100, 1)]
            p = p_hist
        p = max(0.05, min(0.95, p + peso_noticias * sn))
        senal = "Sube" if p >= 0.6 else "Baja" if p <= 0.4 else "Neutral"

        razones = []
        if s200:
            razones.append(("Por encima" if c[t] > s200 else "Por debajo") + " de su media de 200 días (tendencia " +
                           ("alcista)" if c[t] > s200 else "bajista)"))
        if ret(63) is not None:
            razones.append(f"{'Subió' if ret(63) >= 0 else 'Bajó'} {abs(ret(63)):.1f}% en 3 meses")
        if rsi > 70:
            razones.append(f"RSI {rsi:.0f}: sobrecomprado, puede tomar un respiro")
        elif rsi < 30:
            razones.append(f"RSI {rsi:.0f}: sobrevendido, puede rebotar")
        if abs(sn) >= 0.08:
            tema_fuerte = max(temas, key=lambda k: abs(sent_temas.get(k, 0)))
            razones.append(f"Noticias {'positivas' if sn > 0 else 'negativas'} sobre {TEMAS[tema_fuerte][0]}")
        if p_hist is not None:
            razones.append(f"En 5 años, señales parecidas subieron {round(p_hist*100)}% de las veces al mes siguiente")

        activos.append({
            "sym": sym, "nombre": nombre, "tipo": tipo, "region": region, "temas": temas,
            "invertible": tipo not in NO_INVERTIBLES and sym not in NO_INVERTIBLES,
            "precio": r(c[t], 4 if c[t] < 10 else 2), "moneda": d.get("moneda", ""), "fecha": serie[-1][0],
            "r1d": r(ret(1)), "r5d": r(ret(5)), "r21d": r(ret(21)), "r63d": r(ret(63)), "r252d": r(ret(252)), "ytd": r(ytd),
            "vol": r(vol * 100 if vol else None, 1), "rsi": r(rsi, 0),
            "sma200": r((c[t] / s200 - 1) * 100 if s200 else None, 1),
            "tendencia": None if not s200 else ("alcista" if c[t] > s200 and (s50 or 0) > s200 else "bajista" if c[t] < s200 and (s50 or 0) < s200 else "mixta"),
            "desde_max52": r((c[t] / max52 - 1) * 100, 1), "desde_min52": r((c[t] / min52 - 1) * 100, 1),
            "puntaje": r(puntaje, 3), "p_hist": r(p_hist, 3), "noticias": r(sn, 3), "peso_noticias": r(peso_noticias, 3),
            "p": r(p, 3), "senal": senal, "rango": rango, "razones": razones,
            "spark": [r(x, 4) for x in c[-126::3]],
            "velas": [[v[0]] + [sig(x) for x in v[1:]] for v in (d.get("velas") or [])[-130:]],
        })

    # Qué se mueve con qué (correlación de 6 meses de retornos diarios)
    for a in activos:
        pares = []
        for b in activos:
            if b["sym"] == a["sym"]:
                continue
            cc = corr_pares(retornos[a["sym"]], retornos[b["sym"]])
            if cc is not None:
                pares.append((cc, b["nombre"]))
        pares.sort(reverse=True)
        a["se_mueve_con"] = [{"nombre": n, "corr": r(cc)} for cc, n in pares[:3]]
        a["opuesto_a"] = [{"nombre": n, "corr": r(cc)} for cc, n in sorted(pares)[:2] if cc < -0.2]

    claves = [s for s in CLAVE_CORR if s in retornos]
    nombres = {a["sym"]: a["nombre"] for a in activos}
    matriz = [[r(1.0 if x == y else corr_pares(retornos[x], retornos[y]) or 0) for y in claves] for x in claves]

    invertibles = [a for a in activos if a["invertible"]]
    ordenados = sorted(invertibles, key=lambda a: a["p"], reverse=True)
    suben = sum(1 for a in invertibles if (a["r1d"] or 0) > 0)
    p_medio = sum(a["p"] for a in invertibles) / len(invertibles) if invertibles else 0.5
    sent_global = sum(sent_temas.values()) / len(sent_temas) if sent_temas else 0
    termometro = max(0, min(100, round(50 + (p_medio - 0.5) * 250 + sent_global * 60)))
    etiqueta = ("Euforia" if termometro >= 75 else "Optimismo" if termometro >= 58 else "Neutral" if termometro > 42
                else "Miedo" if termometro > 25 else "Pánico")

    temas_out = []
    for k, (nombre, _, _) in TEMAS.items():
        temas_out.append({"key": k, "nombre": nombre, "sent": sent_temas.get(k, 0), "n": len(noticias.get(k, [])),
                          "aprendido": aprendido.get(k), "titulares": noticias.get(k, [])[:8],
                          "activos": [nombres[a[0]] for a in ACTIVOS if k in a[4] and a[0] in nombres][:6]})
    temas_out.sort(key=lambda t: -abs(t["sent"]) * (t["n"] > 0))

    sectores = sorted([{"sym": a["sym"], "nombre": a["nombre"], "r1d": a["r1d"], "r21d": a["r21d"], "r63d": a["r63d"],
                        "ytd": a["ytd"], "p": a["p"], "senal": a["senal"], "noticias": a["noticias"]}
                       for a in activos if a["tipo"] == "Sectores"], key=lambda s: -s["p"])
    regiones = sorted([{"sym": a["sym"], "nombre": a["nombre"], "region": a["region"], "r1d": a["r1d"], "r21d": a["r21d"],
                        "ytd": a["ytd"], "p": a["p"], "senal": a["senal"]}
                       for a in activos if a["tipo"] in ("Países",)], key=lambda s: -s["p"])

    precios_hoy = {a["sym"]: c for a in activos for c in [precios[a["sym"]]["serie"][-1][1]]}
    probs = {a["sym"]: a["p"] for a in invertibles}
    vivo = aciertos_en_vivo(hist, precios_hoy)

    salida = {
        "actualizado": ahora.isoformat(timespec="minutes"),
        "horizonte_dias": HORIZONTE,
        "modelo": None if not mapa else {
            "precision": mapa["precision"], "base_prueba": mapa["base_prueba"], "senales_prueba": mapa["senales_prueba"],
            "muestras": mapa["muestras"], "desde": mapa["desde"],
            "tabla": [{"p": r(b["p"], 3), "p50": r(b["p50"] * 100, 1), "n": b["n"]} for b in mapa["tabla"]],
        },
        "en_vivo": vivo,
        "dias_historial": len(hist) + 1,
        "termometro": {"valor": termometro, "etiqueta": etiqueta, "suben_hoy": suben, "total": len(invertibles),
                       "sent_global": r(sent_global, 3)},
        "top_subir": [a["sym"] for a in ordenados[:8]],
        "top_bajar": [a["sym"] for a in ordenados[::-1][:6]],
        "activos": activos,
        "sectores": sectores,
        "regiones": regiones,
        "temas": temas_out,
        "paises": [{"key": k, "nombre": n, "activos": [x for x in syms if x in nombres]}
                   for k, n, syms in PAISES_GRAFICAS if any(x in nombres for x in syms)],
        "correlaciones": {"simbolos": claves, "nombres": [nombres[s] for s in claves], "matriz": matriz},
        "resumen": None,
        "ia": bool(ANTHROPIC_KEY),
    }
    return salida, hoy, sent_temas, precios_hoy, probs


def resumen_automatico(s):
    act = {a["sym"]: a for a in s["activos"]}
    top = [act[x] for x in s["top_subir"][:4]]
    bajo = [act[x] for x in s["top_bajar"][:3]]
    mejor_mes = sorted([a for a in s["activos"] if a["invertible"] and a["r21d"] is not None], key=lambda a: -a["r21d"])[:4]
    t = s["termometro"]
    temas_pos = [x["nombre"] for x in s["temas"] if x["sent"] > 0.05][:3]
    temas_neg = [x["nombre"] for x in s["temas"] if x["sent"] < -0.05][:3]
    return {
        "titulo": f"Termómetro del mercado: {t['etiqueta'].lower()} ({t['valor']}/100)",
        "resumen": (f"Hoy {t['suben_hoy']} de {t['total']} activos que seguimos van en verde. "
                    + (f"Las noticias más positivas son sobre {', '.join(temas_pos)}. " if temas_pos else "")
                    + (f"Las más negativas, sobre {', '.join(temas_neg)}." if temas_neg else "")),
        "creciendo": [f"{a['nombre']}: {a['r21d']:+.1f}% en el último mes" for a in mejor_mes],
        "puede_crecer": [f"{a['nombre']}: {round(a['p']*100)}% de probabilidad de subir en 1 mes" for a in top],
        "riesgos": [f"{a['nombre']}: solo {round(a['p']*100)}% de probabilidad de subir" for a in bajo],
        "latam": None,
        "fuente": "auto",
    }


def main():
    precios = descargar_precios()
    if len(precios) < 10:
        print("Muy pocos datos de precios; no se actualiza markets.json para no dejar la página vacía.")
        sys.exit(1)
    noticias = descargar_noticias()
    if ANTHROPIC_KEY:
        sentimiento_ia(noticias)
    hist = cargar_historial()
    salida, hoy, sent_temas, precios_hoy, probs = armar_salida(precios, noticias, hist)
    salida["resumen"] = (resumen_ia(salida) if ANTHROPIC_KEY else None) or resumen_automatico(salida)
    guardar_historial(hist, hoy, sent_temas, precios_hoy, probs)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Listo: {len(salida['activos'])} activos, modelo {salida['modelo'] and salida['modelo']['precision']}")


if __name__ == "__main__":
    main()
