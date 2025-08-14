#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, base64, re, sys, unicodedata, requests
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote

# =========================
# Chemins / constantes
# =========================
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
IMAGES = ROOT / "images"
TEMPLATES = ROOT / "templates"
TEMPLATE = TEMPLATES / "article_template_ir.html"  # template harmonisé

AUTHOR = "Rédaction INFO-RÉVEIL"

# Domains autorisés pour les sources (à ajuster selon tes préférences)
WHITELIST_DOMAINS = [
    "lemonde.fr","lefigaro.fr","lesechos.fr","latribune.fr","lepoint.fr",
    "bfmtv.com","francetvinfo.fr","liberation.fr","ouest-france.fr",
    "eur-lex.europa.eu","ec.europa.eu","europarl.europa.eu",
    "assemblee-nationale.fr","senat.fr","impots.gouv.fr","insee.fr",
    "banque-france.fr","courdescomptes.fr","ecologie.gouv.fr",
    "reuters.com","apnews.com","bbc.com","ft.com","bloomberg.com",
]

# =========================
# Utilitaires
# =========================
def die(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+","-", text).strip("-").lower()
    return text or "article"

def html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)

def make_excerpt(lead_html: str, body_html: str, min_len=150, max_len=160) -> str:
    txt = (html_to_text(lead_html) + " " + html_to_text(body_html)).strip()
    txt = re.sub(r"\s+", " ", txt)
    if len(txt) <= max_len:
        return txt
    cut = txt.rfind(" ", 0, max_len)
    if cut < min_len:
        cut = max_len
    return txt[:cut].strip()

def extract_domain(url: str) -> str:
    m = re.match(r"^https?://([^/]+)", url.strip(), flags=re.I)
    return (m.group(1).lower() if m else "").lstrip("www.")

# ====== DuckDuckGo utilitaires ======
def ddg_decode_url(href: str) -> str:
    """Décode les liens /l/?uddg=... de DuckDuckGo."""
    try:
        if href.startswith("https://duckduckgo.com/l/?"):
            qs = parse_qs(urlparse(href).query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        return href
    except Exception:
        return href

def build_queries_from_article(html: str, max_queries: int = 4) -> list[str]:
    """Construit 2–4 requêtes à partir du titre, h2 et 1ers paragraphes."""
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I|re.S)
    title = re.sub(r"<[^>]+>", " ", title_m.group(1)).strip() if title_m else ""
    h2s = [re.sub(r"<[^>]+>"," ", m).strip() for m in re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.I|re.S)]
    first_paras = [re.sub(r"<[^>]+>"," ", p).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.I|re.S)[:2]]
    seeds = [title] + h2s + first_paras
    seeds = [re.sub(r"\s+"," ", s) for s in seeds if s]
    return seeds[:max_queries] if seeds else ["actualité politique France", "dette publique France"]

def search_duckduckgo(query: str, whitelist: list[str], max_results: int = 5) -> list[str]:
    """Recherche DuckDuckGo HTML et retourne des <li> cliquables filtrés par whitelist."""
    url = "https://duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0"}
    data = {"q": query}
    r = requests.post(url, data=data, headers=headers, timeout=12)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for a in soup.select("a.result__a"):
        href_raw = (a.get("href") or "").strip()
        title = a.get_text(strip=True)
        href = ddg_decode_url(href_raw)
        dom = extract_domain(href)
        if not href or not title or not dom:
            continue
        if not any(dom.endswith(wd) or wd in dom for wd in whitelist):
            continue
        items.append(f'<li><a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a></li>')
        if len(items) >= max_results:
            break
    return items

# =========================
# Vérifs de base
# =========================
for p in [INDEX, TEMPLATE]:
    if not p.exists():
        die(f"Fichier manquant: {p.relative_to(ROOT)}")

ARTICLES.mkdir(exist_ok=True)
IMAGES.mkdir(exist_ok=True)

# =========================
# Client OpenAI
# =========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    die("OPENAI_API_KEY manquant (Secrets GitHub > Actions).")
client = OpenAI(api_key=api_key)

# =========================
# 1) Génération de l'article HTML (texte)
# =========================
prompt_article = """
Rédige un article HTML de 600 à 1000 mots en français sur un sujet d'actualité
contenant géopolitique mondiale (pro Trump), IA (avancées mais aussi dangers liés à l'IA), disparition de nos libertés, l'arnaque écologique, dette de la France, dilapidation de l'argent des Français, décisions politiques anormales ou contre productives pour la France, dénonciation des hausses d’impôts et de la vie chère, dénonciation du comportement de nos hommes et femmes politiques en France ou au niveau de l'Europe qui n'est pas en adéquation avec ce qu'ils prônent, tous cas de trahison de la France.
Contraintes strictes :
- Commence par un <h1> clair (titre).
- Structure ensuite en <h2> + <p>.
- Ajoute des références [1][2][3]… dans le texte.
- N'inclus PAS de section "Références" ni "Sources".
- Pas de <!doctype>, <html>, <head>, <body>.
Réponds UNIQUEMENT avec le HTML du corps.
"""
try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt_article}],
        temperature=0.7,
    )
    body_html = resp.choices[0].message.content.strip()
    print("✅ Article généré (texte).")
except Exception as e:
    die(f"Échec génération texte: {e}")

# =========================
# 2) Titre, lead et corps
# =========================
m_title = re.search(r"<h1[^>]*>(.*?)</h1>", body_html, flags=re.I|re.S)
TITLE = (m_title.group(1).strip() if m_title else "Titre provisoire")
after_h1 = body_html[m_title.end():] if m_title else body_html

m_first_p = re.search(r"<p[^>]*>.*?</p>", after_h1, flags=re.I|re.S)
if m_first_p:
    LEAD_HTML = m_first_p.group(0).replace("<p", "<p class=\"lead\"", 1)
    BODY_HTML = after_h1[m_first_p.end():].strip()
else:
    LEAD_HTML = "<p class=\"lead\">—</p>"
    BODY_HTML = after_h1.strip()

BODY_HTML = re.sub(
    r'(<h2[^>]*>\s*(références?|sources?)\s*</h2>[\s\S]*?)((<h2\b)|$)',
    lambda m: m.group(3) if m.group(3) else '',
    BODY_HTML,
    flags=re.I
)

DESCRIPTION = make_excerpt(LEAD_HTML, BODY_HTML, 150, 160)
HERO_ALT = "Illustration de l’article"

now = datetime.now(timezone.utc).astimezone()
date_str = now.strftime("%d/%m/%Y")
stamp = now.strftime("%Y-%m-%d %H:%M:%S %z")
slug = f"{now.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

# =========================
# 3) Génération de l'image héro
# =========================
has_image = False
img_prompt = f"Illustration réaliste, style photojournalisme, pour un article intitulé « {TITLE} »"
try:
    img_resp = client.images.generate(model="gpt-image-1", prompt=img_prompt, size="768x768")
    image_b64 = img_resp.data[0].b64_json
    (IMAGES / hero_filename).write_bytes(base64.b64decode(image_b64))
    has_image = True
    print(f"✅ Image générée: images/{hero_filename}")
except Exception as e:
    print(f"ℹ️ Pas d'image générée ({e}). Un espace vide sera affiché.")

# =========================
# 4) Génération des sources via DuckDuckGo
# =========================
queries = build_queries_from_article(body_html, max_queries=4)
collected, seen = [], set()
for q in queries:
    try:
        results = search_duckduckgo(q, WHITELIST_DOMAINS, max_results=5)
    except Exception as e:
        print(f"⚠️ DuckDuckGo erreur sur '{q}': {e}")
        results = []
    for li in results:
        m = re.search(r'href="([^"]+)".*?>(.*?)</a>', li, flags=re.I|re.S)
        if not m:
            continue
        url = m.group(1)
        title_txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
        key = extract_domain(url) + "|" + title_txt.lower()
        if key in seen:
            continue
        seen.add(key)
        collected.append(li)
        if len(collected) >= 6:
            break
    if len(collected) >= 6:
        break

sources_list = "\n".join(collected) if collected else '<li><a href="#" target="_blank" rel="noopener noreferrer">Sources à compléter</a></li>'
print("✅ Sources générées via DuckDuckGo.")

# =========================
# 5) Composition de l'article final
# =========================
tpl = TEMPLATE.read_text(encoding="utf-8")
article_html = (tpl
    .replace("{{TITLE}}", TITLE)
    .replace("{{LEAD_HTML}}", LEAD_HTML)
    .replace("{{BODY_HTML}}", BODY_HTML)
    .replace("{{SOURCES_LIST}}", sources_list)
    .replace("{{HERO_ALT}}", HERO_ALT)
    .replace("{{HERO_FILENAME}}", hero_filename if has_image else "")
)

if has_image:
    article_html = re.sub(
        r'src=["\']/?images/\{\{HERO_FILENAME\}\}["\']',
        f'src="/images/{hero_filename}"',
        article_html,
        flags=re.I
    )
else:
    article_html = re.sub(
        r'\s*<figure\s+class="img">[\s\S]*?</figure>\s*',
        '\n<div style="height:24px"></div>\n',
        article_html,
        flags=re.I
    )

(ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
print(f"✅ Article écrit: articles/{article_filename}")

# =========================
# 6) Insertion vignette dans index.html
# =========================
idx_html = INDEX.read_text(encoding="utf-8")
if "<!-- FEED:start -->" not in idx_html or "<!-- FEED:end -->" not in idx_html:
    grid_open = re.search(r"<(main|div)([^>]*\bclass=[\"'][^\"']*\bgrid\b[^\"']*[\"'][^>]*)>", idx_html, flags=re.I)
    if grid_open:
        pos = grid_open.end()
        idx_html = idx_html[:pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + idx_html[pos:]
    else:
        body_open = re.search(r"<body[^>]*>", idx_html, flags=re.I)
        if not body_open:
            die("Impossible de trouver <body> pour insérer le feed.")
        pos = body_open.end()
        idx_html = idx_html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + idx_html[pos:]

if has_image:
    thumb_block = f'''<a class="thumb" href="articles/{article_filename}" aria-label="Lire : {TITLE}">
          <img src="images/{hero_filename}" alt="{HERO_ALT}">
        </a>'''
else:
    thumb_block = f'''<a class="thumb" href="articles/{article_filename}" aria-label="Lire : {TITLE}">
          <div style="aspect-ratio:16/9;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.03)"></div>
        </a>'''

card_html = f"""
      <!-- card-{slug} -->
      <article class="card">
        {thumb_block}
        <div class="card-body">
          <h2 class="title">{TITLE}</h2>
          <p class="excerpt">{DESCRIPTION}</p>
          <div class="meta">
            <span class="badge">Article</span>
            <span>Publié le {date_str}</span>
          </div>
          <a class="link" href="articles/{article_filename}">Lire l’article</a>
        </div>
      </article>
""".rstrip()

idx_html = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, idx_html, count=1, flags=re.S)
idx_html += f"\n<!-- automated-build {stamp} -->\n"
INDEX.write_text(idx_html, encoding="utf-8")
print("✅ Vignette insérée + index.html mis à jour.")
