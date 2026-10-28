"""Manda el correo diario con las noticias a los usuarios suscritos.
Lo corre GitHub Actions después de buscar las noticias (ver .github/workflows/news.yml).
Necesita estos secretos en GitHub: SUPABASE_URL, SUPABASE_SERVICE_KEY, BREVO_API_KEY, SENDER_EMAIL."""
import os, json, html, urllib.request
from datetime import datetime, timezone, timedelta

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BREVO_KEY = os.environ.get("BREVO_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")
SENDER_NAME = os.environ.get("SENDER_NAME", "Finanzas Today")
SITE = os.environ.get("SITE_URL", "https://lemp200548.github.io/finanzas-today/")
POR_CATEGORIA = 2
COL = timezone(timedelta(hours=-5))
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def pedir(url, headers, data=None, method="GET"):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def usuarios():
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
    todos, pagina = [], 1
    while True:
        res = pedir(f"{SUPABASE_URL}/auth/v1/admin/users?page={pagina}&per_page=1000", h)
        lote = res.get("users", [])
        todos += lote
        if len(lote) < 1000:
            return todos
        pagina += 1


def correo_html(noticias, pais):
    hoy = datetime.now(COL)
    fecha = f"{hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}"
    nombre_pais = "Venezuela" if pais == "ve" else "Colombia"
    por_cat = {}
    for n in noticias:
        por_cat.setdefault(n["categoria"], [])
        if len(por_cat[n["categoria"]]) < POR_CATEGORIA:
            por_cat[n["categoria"]].append(n)
    bloques = ""
    for cat, items in por_cat.items():
        filas = "".join(
            f'''<tr><td style="padding:0 0 16px">
              <a href="{html.escape(n['link'])}" style="color:#111;text-decoration:none;font-size:18px;font-weight:800;line-height:1.3">{html.escape(n['titulo'])}</a>
              <div style="font-family:Menlo,monospace;font-size:11px;color:#5E6470;letter-spacing:1px;text-transform:uppercase;margin-top:4px">{html.escape(n['fuente'])}</div>
            </td></tr>''' for n in items)
        bloques += f'''
          <tr><td style="padding:22px 0 10px;border-top:1px solid #E4E6EB">
            <div style="color:#1F5BD8;font-weight:800;font-size:13px;letter-spacing:1px;text-transform:uppercase">{html.escape(cat)}</div>
          </td></tr>{filas}'''
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head><body style="margin:0;background:#F8F7F3;font-family:Helvetica,Arial,sans-serif;color:#111">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F8F7F3"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border:1px solid #111">
  <tr><td style="height:8px;background:#1F5BD8"></td></tr>
  <tr><td style="padding:28px 28px 8px">
    <div style="font-size:26px;font-weight:900;letter-spacing:-1px">Finanzas<span style="color:#1F5BD8">Today</span></div>
    <div style="font-family:Menlo,monospace;font-size:11px;color:#5E6470;letter-spacing:1px;text-transform:uppercase;margin-top:6px">{fecha} · {nombre_pais}</div>
    <div style="font-size:22px;font-weight:800;margin-top:18px;line-height:1.2">Vuélvete más culto en 5 minutos ☕</div>
    <div style="color:#5E6470;font-size:15px;margin-top:6px">Esto es lo que tienes que saber hoy.</div>
  </td></tr>
  <tr><td style="padding:8px 28px 8px"><table width="100%" cellpadding="0" cellspacing="0">{bloques}</table></td></tr>
  <tr><td style="padding:8px 28px 28px" align="center">
    <a href="{SITE}" style="display:inline-block;background:#1F5BD8;color:#fff;text-decoration:none;font-weight:800;padding:14px 26px;border-radius:8px">Ver todas las noticias →</a>
  </td></tr>
  <tr><td style="padding:18px 28px;border-top:1px solid #E4E6EB;font-size:12px;color:#5E6470" align="center">
    Recibes este correo porque te suscribiste a Finanzas Today.<br>
    <a href="{SITE}baja.html" style="color:#5E6470">Dejar de recibir correos o cambiar de país</a>
  </td></tr>
</table></td></tr></table></body></html>'''


def main():
    faltan = [k for k, v in {"SUPABASE_URL": SUPABASE_URL, "SUPABASE_SERVICE_KEY": SERVICE_KEY,
                             "BREVO_API_KEY": BREVO_KEY, "SENDER_EMAIL": SENDER_EMAIL}.items() if not v]
    if faltan:
        print("No se mandan correos: faltan los secretos " + ", ".join(faltan))
        return

    with open("news.json", encoding="utf-8") as f:
        datos = json.load(f)
    paises = datos.get("paises", {})
    html_por_pais, asunto_por_pais = {}, {}
    for p, lista in paises.items():
        if not lista:
            continue
        recientes = sorted(lista, key=lambda n: n.get("fecha") or "", reverse=True)
        principal = next((n for n in recientes if "Planes" not in n["categoria"] and "Deportes" not in n["categoria"]), recientes[0])
        html_por_pais[p] = correo_html(lista, p)
        asunto_por_pais[p] = "☕ " + principal["titulo"][:90]

    enviados = saltados = errores = 0
    for u in usuarios():
        meta = u.get("user_metadata") or {}
        email = u.get("email")
        confirmado = u.get("email_confirmed_at") or u.get("confirmed_at")
        if not email or not confirmado or meta.get("newsletter") is False:
            saltados += 1
            continue
        p = meta.get("pais") if meta.get("pais") in html_por_pais else "co"
        if p not in html_por_pais:
            saltados += 1
            continue
        try:
            pedir("https://api.brevo.com/v3/smtp/email",
                  {"api-key": BREVO_KEY, "Content-Type": "application/json", "accept": "application/json"},
                  {"sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
                   "to": [{"email": email}],
                   "subject": asunto_por_pais[p],
                   "htmlContent": html_por_pais[p]}, method="POST")
            enviados += 1
        except Exception as e:
            errores += 1
            print(f"Error con {email}: {e}")
    print(f"Correos enviados: {enviados} · saltados: {saltados} · errores: {errores}")


if __name__ == "__main__":
    main()
