#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, base64, time, unicodedata
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# =========================
# Chemins / constantes
# =========================
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
IMAGES = ROOT / "images"
TEMPLATES = ROOT / "templates"
TEMPLATE = TEMPLATES / "article_template_ir.html"

AUTHOR = "Rédaction INFO-RÉVEIL"
MAX_LINKS = 10

# Whitelist FR + EN (ajuste librement)
WHITELIST = {
    # FR médias & institutions
    "lemonde.fr","lefigaro.fr","lesechos.fr","latribune.fr","lepoint.fr",
    "bfmtv.com","francetvinfo.fr","liberation.fr","ouest-france.fr",
    "eur-lex.europa.eu","ec.europa.eu","europarl.europa.eu",
    "assemblee-nationale.fr","senat.fr","impots.gouv.fr","insee.fr",
    "banque-france.fr","courdescomptes.fr","ecologie.gouv.fr",
    # Agences & internationaux
    "reuters.com","apnews.com","bbc.com","ft.com","bloomberg.com",
    # EN médias réputés
    "nytimes.com","washingtonpost.com","wsj.com","theguardian.com",
    "economist.com","time.com","newsweek.com","forbes.com","cbsnews.com",
    "nbcnews.com","abcnews.go.com","npr.org","axios.com","politico.com",
    "financialtimes.com","theatlantic.com","foreignaffairs.com",
    "nature.com","science.org",
    # Organisations internationales / Gov
    "oecd.org","imf.org","worldbank.org","un.org","unesco.org","who.int",
    "wto.org","nato.int","weforum.org",
    "gov.uk","ons.gov.uk","bankofengland.co.uk",
    "whitehouse.gov","congress.gov","treasury.gov","census.gov","federalreserve.gov",
}

# =========================
# Utilitaires généraux
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

def domain_of(url: str) -> str:
    m = re.match(r"^https?://([^/]+)", url.strip(), flags=re.I)
    return (m.group(1).lower() if m else "").lstrip("www.")

def allow(url: str) -> bool:
    d = domain_of(url)
    return any(d.endswith(w) or w in d for w in WHITELIST)

def clean_dd_redirect(href: str) -> str:
    # utile si un moteur renvoie /l/?uddg=...
    try:
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            if "uddg" in qs: return unquote(qs["uddg"][0])
    except Exception:
        pass
    return href

# =========================
# Requêtes & Parsing des moteurs (sans API)
# =========================
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8", "Referer": "https://google.com/"}

def search_startpage(q: str, k: int = 6, timeout=10) -> list[tuple[str,str]]:
    # HTML : https://www.startpage.com/sp/search
    try:
        r = requests.get("https://www.startpage.com/sp/search", params={"query": q}, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for a in soup.select("a.result-link, a[data-testid='result-title-a'], .w-gl__result-title a"):
            href = clean_dd_redirect(a.get("href","").strip())
            title = a.get_text(strip=True)
            if href.startswith("/") or not href.startswith("http"): continue
            if allow(href) and title:
                out.append((href, title))
            if len(out) >= k: break
        return out
    except Exception:
        return []

def search_searx(q: str, k: int = 6, timeout=10) -> list[tuple[str,str]]:
    # Instance publique (peut varier) : searx.be, searx.tiekoetter.com, etc.
    # On tente 2-3 instances en parallèle simple.
    instances = [
        "https://searx.be/search",
        "https://searx.tiekoetter.com/search",
        "https://search.bus-hit.me/search",
    ]
    for url in instances:
        try:
            r = requests.get(url, params={"q": q, "language":"fr-FR", "format":"html"}, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            out=[]
            for a in soup.select("a.result_header, h3 a, .result a"):
                href = a.get("href","").strip()
                title = a.get_text(strip=True)
                if href.startswith("/") or not href.startswith("http"): continue
                if allow(href) and title:
                    out.append((href, title))
                if len(out) >= k: break
            if out: return out
        except Exception:
            continue
    return []

def search_yandex(q: str, k: int = 6, timeout=10) -> list[tuple[str,str]]:
    # Recherche simple non-API : https://yandex.com/search/
    try:
        r = requests.get("https://yandex.com/search/", params={"text": q, "lr": "87"}, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out=[]
        for a in soup.select("a.Link.Link_theme_normal.OrganicTitle-Link, a.Link_theme_normal, h2 a"):
            href = a.get("href","").strip()
            title = a.get_text(strip=True)
            if href.startswith("/") or not href.startswith("http"): continue
            if allow(href) and title:
                out.append((href, title))
            if len(out) >= k: break
        return out
    except Exception:
        return []

def search_marginalia(q: str, k: int = 6, timeout=10) -> list[tuple[str,str]]:
    # https://search.marginalia.nu/search
    try:
        r = requests.get("https://search.marginalia.nu/search", params={"query": q}, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out=[]
        for a in soup.select("a"):
            href = a.get("href","").strip()
            title = a.get_text(strip=True)
            if not title or not href.startswith("http"): continue
            if allow(href):
                out.append((href, title))
            if len(out) >= k: break
        return out
    except Exception:
        return []

SEARCH_ENGINES = [
    ("startpage", search_startpage),
    ("searx",      search_searx),
    ("yandex",     search_yandex),
    ("marginalia", search_marginalia),
]

# =========================
# Génération des requêtes & détection thématique
# =========================
def build_queries_from_article(html: str, maxq: int = 4) -> list[str]:
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I|re.S)
    title = re.sub(r"<[^>]+>", " ", title_m.group(1)).strip() if title_m else ""
    h2s = [re.sub(r"<[^>]+>", " ", m).strip() for m in re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.I|re.S)]
    paras = [re.sub(r"<[^>]+>", " ", p).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.I|re.S)[:2]]
    seeds = [title] + h2s + paras
    seeds = [re.sub(r"\s+"," ", s) for s in seeds if s]
    seen=set(); out=[]
    for s in seeds:
        k = s.lower()
        if k not in seen:
            seen.add(k); out.append(s)
        if len(out) >= maxq: break
    return out or ["actualité politique France", "dette publique France"]

def detect_theme(text: str) -> str:
    txt = text.lower()
    if any(w in txt for w in ["dette","économie","budget","déficit","inflation"]): return "eco"
    if any(w in txt for w in ["trump","usa","états-unis","biden","amérique"]): return "usa"
    if any(w in txt for w in ["ia","intelligence artificielle","algorithme","openai","chatgpt"]): return "ia"
    if any(w in txt for w in ["écologie","climat","co2","environnement","éolienne","transition"]): return "eco_env"
    return "generic"

THEMATIC_SOURCES = {
    "eco": [
        ("https://www.insee.fr/fr/accueil", "INSEE"),
        ("https://www.banque-france.fr/", "Banque de France"),
        ("https://www.lesechos.fr/", "Les Échos"),
    ],
    "usa": [
        ("https://www.reuters.com/world/us/", "Reuters US"),
        ("https://www.bbc.com/news/world/us_and_canada", "BBC America"),
        ("https://www.lefigaro.fr/international", "Le Figaro - International"),
    ],
    "ia": [
        ("https://www.nature.com/subjects/artificial-intelligence", "Nature - AI"),
        ("https://www.reuters.com/technology/", "Reuters Tech"),
        ("https://www.lesechos.fr/tech-medias", "Les Échos Tech"),
    ],
    "eco_env": [
        ("https://www.ecologie.gouv.fr/actualites", "Ministère Écologie"),
        ("https://www.lemonde.fr/planete/", "Le Monde - Planète"),
        ("https://www.actu-environnement.com/ae/news/liste.php", "Actu-Environnement"),
    ],
    "generic": [
        ("https://www.reuters.com/", "Reuters"),
        ("https://www.bbc.com/news", "BBC News"),
        ("https://www.lemonde.fr/", "Le Monde"),
    ],
}

def thematic_links(theme: str, max_items=4) -> list[str]:
    items = []
    for url, title in THEMATIC_SOURCES.get(theme, THEMATIC_SOURCES["generic"]):
        if allow(url):
            items.append(f'<li><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></li>')
        if len(items) >= max_items: break
    return items

# =========================
# Orchestrateur de recherche (parallèle)
# =========================
def search_all_sources(queries: list[str], max_total=MAX_LINKS) -> list[str]:
    results = []
    seen = set()

    def task(engine_name, fn, q):
        out = fn(q, k=6)
        return engine_name, q, out

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = []
        for q in queries:
            for name, fn in SEARCH_ENGINES:
                futures.append(ex.submit(task, name, fn, q))

        for fut in as_completed(futures, timeout=20):
            try:
                name, q, pairs = fut.result()
            except Exception:
                continue
            for href, title in pairs:
                key = domain_of(href) + "|" + title.lower()
                if key in seen: 
                    continue
                seen.add(key)
                results.append(f'<li><a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a></li>')
                if len(results) >= max_total:
                    return results
    return results

# =========================
# Vérifs / initialisation
# =========================
if not INDEX.exists():
    die(f"Fichier manquant: {INDEX.relative_to(ROOT)}")
ARTICLES.mkdir(exist_ok=True); IMAGES.mkdir(exist_ok=True)

# =========================
# Client OpenAI
# =========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    die("OPENAI_API_KEY manquant (Secrets GitHub > Actions).")
client = OpenAI(api_key=api_key)

# =========================
# 1) Génération du corps HTML de l’article (prompt exact demandé)
# =========================
prompt_article = """
Rédige un article HTML de 600 à 1000 mots en français sur un sujet d'actualité
contenant un sujet au choix à propos de : géopolitique mondiale (pro Trump),
IA (avancées mais aussi dangers liés à l'IA), disparition de nos libertés,
l'arnaque écologique, dette de la France, dilapidation de l'argent des Français,
décisions politiques anormales ou contre productives pour la France, dénonciation
des hausses d'impôts et de la vie chère, dénonciation du comportement de nos
hommes et femmes politiques en France ou au niveau de l'Europe qui n'est pas en
adéquation avec ce qu'ils prônent, tous cas de trahison de la France (vente
d'entreprises stratégiques françaises, concession d'exploitation de ressources
naturelles françaises par des entreprises étrangères, etc), avec un ton
journalistique et engagé à droite.
Contraintes strictes :
- Commence par un <h1> clair (titre).
- Structure ensuite en <h2> + <p>.
- Ajoute des références [1][2][3]… dans le texte là où c’est pertinent.
- N'inclus PAS de section "Références" ni "Sources" dans le corps de l'article.
- Ne mets PAS de <!doctype>, <html>, <head> ni <body>.
Réponds UNIQUEMENT avec le HTML du corps de l’article.
"""
try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt_article}],
        temperature=0.7,
    )
    body_html = resp.choices[0].message.content.strip()
except Exception as e:
    die(f"Échec génération texte: {e}")

# =========================
# 2) Titre / Lead / Corps (nettoyage doublons 'Sources')
# =========================
m_title = re.search(r"<h1[^>]*>(.*?)</h1>", body_html, flags=re.I|re.S)
TITLE = (re.sub(r"<[^>]+>", " ", m_title.group(1)).strip() if m_title else "Titre provisoire")
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

DESCRIPTION = make_excerpt(LEAD_HTML, BODY_HTML)
HERO_ALT = "Illustration de l’article"

now = datetime.now(timezone.utc).astimezone()
date_str = now.strftime("%d/%m/%Y")
stamp = now.strftime("%Y-%m-%d %H:%M:%S %z")
slug = f"{now.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

# =========================
# 3) Image héro (aucun fallback)
# =========================
has_image = False
try:
    img_resp = client.images.generate(model="gpt-image-1", prompt=f"Illustration photojournalisme pour « {TITLE} »", size="768x768")
    b64 = img_resp.data[0].b64_json
    (IMAGES / hero_filename).write_bytes(base64.b64decode(b64))
    has_image = True
except Exception:
    has_image = False

# =========================
# 4) SOURCES : moteurs parallèles → thématiques → fallback
# =========================
queries = build_queries_from_article(body_html, maxq=4)
links = search_all_sources(queries, max_total=MAX_LINKS)

if len(links) < 3:  # thématiques
    theme = detect_theme((TITLE + " " + html_to_text(LEAD_HTML)).lower())
    links += thematic_links(theme, max_items=4)

if not links:  # fallback générique
    links = [
        '<li><a href="https://www.reuters.com/" target="_blank" rel="noopener noreferrer">Reuters</a></li>',
        '<li><a href="https://www.bbc.com/news" target="_blank" rel="noopener noreferrer">BBC News</a></li>',
        '<li><a href="https://www.lemonde.fr/" target="_blank" rel="noopener noreferrer">Le Monde</a></li>',
    ]

# tronquer à MAX_LINKS
links = links[:MAX_LINKS]
sources_list = "\n".join(links)

# =========================
# 5) Composer l'article final
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

if not has_image:
    article_html = re.sub(r'\s*<figure\s+class="img">[\s\S]*?</figure>\s*', '\n<div style="height:24px"></div>\n', article_html, flags=re.I)

(ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
print(f"✅ Article écrit: articles/{article_filename}")

# =========================
# 6) Mettre à jour l'index (vignette en tête)
# =========================
idx_html = INDEX.read_text(encoding="utf-8")
if "<!-- FEED:start -->" not in idx_html or "<!-- FEED:end -->" not in idx_html:
    body_open = re.search(r"<body[^>]*>", idx_html, flags=re.I)
    pos = body_open.end() if body_open else 0
    idx_html = idx_html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + idx_html[pos:]

thumb = f'<img src="images/{hero_filename}" alt="{HERO_ALT}">' if has_image else '<div style="aspect-ratio:16/9;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.03)"></div>'

card_html = f"""
      <!-- card-{slug} -->
      <article class="card">
        <a class="thumb" href="articles/{article_filename}" aria-label="Lire : {TITLE}">
          {thumb}
        </a>
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
print("✅ index.html mis à jour")
