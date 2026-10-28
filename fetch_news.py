"""Busca las noticias del día y las guarda en news.json.
Lo corre GitHub Actions todos los días (ver .github/workflows/news.yml)."""
import json, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# Periódicos de donde se toman las noticias
FUENTES = "(site:larepublica.co OR site:portafolio.co OR site:bloomberglinea.com OR site:valoraanalitik.com OR site:eltiempo.com OR site:semana.com OR site:elcolombiano.com)"

# Categorías: nombre que se ve en la página -> qué buscar
CATEGORIAS = {
    "Economía": "dólar OR inflación OR \"Banco de la República\" OR economía Colombia",
    "Petróleo y energía": "Ecopetrol OR petróleo OR gas OR energía Colombia",
    "Sector financiero": "bancos OR Bancolombia OR Davivienda OR Superfinanciera OR CDT",
    "Nuevos CEO": "\"nuevo presidente\" OR \"nuevo CEO\" OR nombramiento OR \"asume la presidencia\" empresa",
    "Consultoría": "consultoría OR consultora OR McKinsey OR Deloitte OR EY OR PwC OR KPMG Colombia",
    "Bolsa y empresas": "\"Bolsa de Colombia\" OR acciones OR adquisición OR fusión empresa Colombia",
}
POR_CATEGORIA = 6
COL = timezone(timedelta(hours=-5))


def buscar(consulta):
    q = f"{consulta} {FUENTES} when:1d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "es-419", "gl": "CO", "ceid": "CO:es-419"})
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


def main():
    vistos, noticias = set(), []
    for cat, consulta in CATEGORIAS.items():
        try:
            items = list(leer(buscar(consulta)))
        except Exception as e:
            print(f"[{cat}] error: {e}")
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
        print(f"[{cat}] {n} noticias")
    salida = {"actualizado": datetime.now(COL).isoformat(), "noticias": noticias}
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
