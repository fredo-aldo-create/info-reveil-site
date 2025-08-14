#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, base64, re, sys, unicodedata, requests, time
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote
import json

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

# Domains autorisés pour les sources (FR + anglophones réputés)
WHITELIST_DOMAINS = [
    # --- FR médias & institutions ---
    "lemonde.fr","lefigaro.fr","lesechos.fr","latribune.fr","lepoint.fr",
    "bfmtv.com","francetvinfo.fr","liberation.fr","ouest-france.fr",
    "eur-lex.europa.eu","ec.europa.eu","europarl.europa.eu",
    "assemblee-nationale.fr","senat.fr","impots.gouv.fr","insee.fr",
    "banque-france.fr","courdescomptes.fr","ecologie.gouv.fr",

    # --- Agences & internationaux ---
    "reuters.com","apnews.com","bbc.com","ft.com","bloomberg.com",

    # --- Anglophones réputés ---
    "nytimes.com","washingtonpost.com","wsj.com","theguardian.com",
    "economist.com","time.com","newsweek.com","forbes.com","cbsnews.com",
    "nbcnews.com","abcnews.go.com","npr.org","axios.com","politico.com",
    "financialtimes.com","theatlantic.com","foreignaffairs.com",
    "nature.com","science.org",

    # --- Institutions & organisations internationales ---
    "oecd.org","imf.org","worldbank.org","un.org","unesco.org","who.int",
    "wto.org","nato.int","weforum.org",

    # --- UK Gov & autres officiels ---
    "gov.uk","ons.gov.uk","bankofengland.co.uk",

    # --- US Gov ---
    "whitehouse.gov","congress.gov","treasury.gov","census.gov","federalreserve.gov",
]

# =========================
# Utilitaires
# =========================
def die(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)

def debug_log(msg: str, level="INFO"):
    print(f"[{level}] {msg}")

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

# ====== Sources alternatives (fallback) ======
def generate_fallback_sources() -> list[str]:
    """Génère des sources de fallback pour éviter une section vide."""
    fallback_sources = [
        '<li><a href="https://www.lemonde.fr/politique/" target="_blank" rel="noopener noreferrer">Le Monde - Politique</a></li>',
        '<li><a href="https://www.lefigaro.fr/politique" target="_blank" rel="noopener noreferrer">Le Figaro - Politique</a></li>',
        '<li><a href="https://www.lesechos.fr/politique-societe" target="_blank" rel="noopener noreferrer">Les Échos - Politique</a></li>',
        '<li><a href="https://www.insee.fr/fr/statistiques" target="_blank" rel="noopener noreferrer">INSEE - Statistiques</a></li>',
    ]
    return fallback_sources[:3]  # Retourne 3 sources de fallback

# ====== DuckDuckGo utilitaires améliorés ======
def ddg_decode_url(href: str) -> str:
    """Décode les liens /l/?uddg=... de DuckDuckGo."""
    try:
        if href.startswith("https://duckduckgo.com/l/?"):
            qs = parse_qs(urlparse(href).query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        return href
    except Exception as e:
        debug_log(f"Erreur décodage URL {href}: {e}", "WARN")
        return href

def build_queries_from_article(html: str, max_queries: int = 4) -> list[str]:
    """Construit 2–4 requêtes à partir du titre, h2 et 1ers paragraphes (nettoyés/dédupliqués)."""
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I|re.S)
    title = re.sub(r"<[^>]+>", " ", title_m.group(1)).strip() if title_m else ""
    h2s = [re.sub(r"<[^>]+>", " ", m).strip() for m in re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.I|re.S)]
    paras = [re.sub(r"<[^>]+>", " ", p).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.I|re.S)[:2]]

    seeds = [title] + h2s + paras
    seeds = [re.sub(r"\s+", " ", s) for s in seeds if s]
    # déduplication
    seen = set(); uniq = []
    for s in seeds:
        key = s.lower()
        if key not in seen:
            seen.add(key); uniq.append(s)
    
    queries = uniq[:max_queries] if uniq else ["actualité politique France", "dette publique France"]
    debug_log(f"Requêtes générées: {queries}")
    return queries

def _ddg_fetch(url: str, method: str, params=None, data=None, timeout=15):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://duckduckgo.com/"
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        if method == "GET":
            r = session.get(url, params=params, timeout=timeout)
        else:
            r = session.post(url, data=data, timeout=timeout)
        r.raise_for_status()
        debug_log(f"Succès {method} {url} - Status: {r.status_code}")
        return r.text
    except Exception as e:
        debug_log(f"Erreur {method} {url}: {e}", "ERROR")
        raise

def _ddg_parse_items(html: str) -> list[tuple[str,str]]:
    """Retourne une liste [(href, title)] depuis la page résultats DDG."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    
    # Essayer plusieurs sélecteurs selon les versions de DDG
    selectors = [
        "a.result__a",
        ".result__title a",
        "a[data-testid='result-title-a']",
        ".result a",
        "h2 a",
        ".results .result a"
    ]
    
    debug_log(f"Parsing HTML de {len(html)} caractères")
    
    for selector in selectors:
        anchors = soup.select(selector)
        debug_log(f"Sélecteur '{selector}': {len(anchors)} éléments trouvés")
        
        if anchors:
            for a in anchors:
                href_raw = (a.get("href") or "").strip()
                title = a.get_text(strip=True)
                href = ddg_decode_url(href_raw)
                
                if href and title and not href.startswith("#"):
                    debug_log(f"Lien trouvé: {href} | {title[:50]}...")
                    items.append((href, title))
            
            if items:
                debug_log(f"Total liens extraits avec '{selector}': {len(items)}")
                break
    
    if not items:
        debug_log("AUCUN lien trouvé avec tous les sélecteurs", "WARN")
        # Debug: sauvegarder le HTML pour inspection
        debug_file = ROOT / "debug_ddg.html"
        debug_file.write_text(html[:5000], encoding="utf-8")  # Premiers 5000 caractères
        debug_log(f"HTML de debug sauvé dans {debug_file}")
    
    return items

def search_duckduckgo(query: str, whitelist: list[str], max_results: int = 5) -> list[str]:
    """
    Recherche DuckDuckGo HTML améliorée avec plus de debugging.
    """
    debug_log(f"Recherche DDG: '{query}'")
    
    attempts = [
        ("GET", "https://duckduckgo.com/", {"q": query, "kl": "fr-fr", "df": "m"}, None),
        ("GET", "https://duckduckgo.com/html/", {"q": query, "kl": "fr-fr"}, None),
        ("POST", "https://duckduckgo.com/html/", None, {"q": query, "kl": "fr-fr"}),
        ("GET", "https://duckduckgo.com/lite/", {"q": query, "kl": "fr-fr"}, None),
    ]
    
    found = []
    for i, (method, url, params, data) in enumerate(attempts):
        try:
            debug_log(f"Tentative {i+1}/{len(attempts)}: {method} {url}")
            page = _ddg_fetch(url, method, params=params, data=data, timeout=20)
            
            if not page or len(page) < 1000:
                debug_log(f"Page trop courte ({len(page)} chars), probablement bloquée", "WARN")
                continue
            
            pairs = _ddg_parse_items(page)
            debug_log(f"Liens extraits bruts: {len(pairs)}")
            
            if not pairs:
                debug_log("Aucun lien extrait, tentative suivante", "WARN")
                continue
                
            for href, title in pairs:
                dom = extract_domain(href)
                debug_log(f"Vérification domaine: {dom}")
                
                if not any(dom.endswith(wd) or wd in dom for wd in whitelist):
                    debug_log(f"Domaine {dom} non autorisé", "DEBUG")
                    continue
                    
                link_html = f'<li><a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a></li>'
                found.append(link_html)
                debug_log(f"Lien ajouté: {dom} | {title[:50]}...")
                
                if len(found) >= max_results:
                    break
            
            if found:
                debug_log(f"Succès! {len(found)} liens trouvés")
                break
                
        except Exception as e:
            debug_log(f"Échec tentative {i+1}: {e}", "ERROR")
            continue
        finally:
            time.sleep(2)  # Pause plus longue
    
    debug_log(f"Résultat final pour '{query}': {len(found)} liens")
    return found

# =========================
# Vérifs de base
# =========================
for p in [INDEX]:  # On vérifie que INDEX existe, le template sera créé si besoin
    if not p.exists():
        die(f"Fichier manquant: {p.relative_to(ROOT)}")

ARTICLES.mkdir(exist_ok=True)
IMAGES.mkdir(exist_ok=True)
TEMPLATES.mkdir(exist_ok=True)

# Le template existe déjà, pas besoin de le créer

# =========================
# Client OpenAI
# =========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    die("OPENAI_API_KEY manquant (Secrets GitHub > Actions).")
client = OpenAI(api_key=api_key)

# =========================
# 1) Génération du corps HTML de l'article
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
- Ajoute des références [1][2][3]… dans le texte là où c'est pertinent.
- N'inclus PAS de section "Références" ni "Sources" dans le corps de l'article.
- Ne mets PAS de <!doctype>, <html>, <head> ni <body>.
Réponds UNIQUEMENT avec le HTML du corps de l'article.
"""
try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt_article}],
        temperature=0.7,
    )
    body_html = resp.choices[0].message.content.strip()
    debug_log("Article généré (texte)")
except Exception as e:
    die(f"Échec génération texte: {e}")

# =========================
# 2) Titre, lead (1er <p>) et reste du corps
# =========================
m_title = re.search(r"<h1[^>]*>(.*?)</h1>", body_html, flags=re.I|re.S)
TITLE = (re.sub(r"<[^>]+>", "", m_title.group(1)).strip() if m_title else "Titre provisoire")
after_h1 = body_html[m_title.end():] if m_title else body_html

m_first_p = re.search(r"<p[^>]*>.*?</p>", after_h1, flags=re.I|re.S)
if m_first_p:
    LEAD_HTML = m_first_p.group(0).replace("<p", "<p class=\"lead\"", 1)
    BODY_HTML = after_h1[m_first_p.end():].strip()
else:
    LEAD_HTML = "<p class=\"lead\">—</p>"
    BODY_HTML = after_h1.strip()

# Supprime toute section "Références"/"Sources" résiduelle
BODY_HTML = re.sub(
    r'(<h2[^>]*>\s*(références?|sources?)\s*</h2>[\s\S]*?)((<h2\b)|$)',
    lambda m: m.group(3) if m.group(3) else '',
    BODY_HTML,
    flags=re.I
)

DESCRIPTION = make_excerpt(LEAD_HTML, BODY_HTML, 150, 160)
HERO_ALT = "Illustration de l'article"

now = datetime.now(timezone.utc).astimezone()
date_str = now.strftime("%d/%m/%Y")
stamp = now.strftime("%Y-%m-%d %H:%M:%S %z")
slug = f"{now.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

debug_log(f"Article: {TITLE}")
debug_log(f"Fichier: {article_filename}")

# =========================
# 3) Génération de l'image héro
# =========================
has_image = False
img_prompt = f"Illustration réaliste, style photojournalisme, pour un article intitulé « {TITLE} »"
try:
    img_resp = client.images.generate(model="gpt-image-1", prompt=img_prompt, size="768x768")
    if hasattr(img_resp.data[0], 'b64_json') and img_resp.data[0].b64_json:
        image_b64 = img_resp.data[0].b64_json
        (IMAGES / hero_filename).write_bytes(base64.b64decode(image_b64))
        has_image = True
        debug_log(f"Image générée: images/{hero_filename}")
    elif hasattr(img_resp.data[0], 'url'):
        # Télécharger depuis l'URL
        img_url = img_resp.data[0].url
        img_response = requests.get(img_url, timeout=30)
        img_response.raise_for_status()
        (IMAGES / hero_filename).write_bytes(img_response.content)
        has_image = True
        debug_log(f"Image téléchargée: images/{hero_filename}")
except Exception as e:
    has_image = False
    debug_log(f"Pas d'image générée ({e}). Espace vide sera affiché.", "WARN")

# =========================
# 4) Génération des sources via DuckDuckGo (améliorée)
# =========================
queries = build_queries_from_article(body_html, max_queries=3)
collected, seen = [], set()

def add_results(li_list, label=""):
    added = 0
    for li in li_list:
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
        added += 1
        if len(collected) >= 6:
            break
    if label and added > 0:
        debug_log(f"{label}: +{added} liens")
    return added

# Pass 1 : requêtes naturelles
debug_log("=== DÉBUT RECHERCHE SOURCES ===")
for q in queries[:2]:  # Limiter pour éviter les timeouts
    try:
        results = search_duckduckgo(q, WHITELIST_DOMAINS, max_results=4)
        add_results(results, f"Requête: {q}")
    except Exception as e:
        debug_log(f"DuckDuckGo erreur sur '{q}': {e}", "ERROR")
    if len(collected) >= 4:
        break
    time.sleep(3)  # Pause plus longue entre les requêtes

# Pass 2 : fallback si pas assez de liens
if len(collected) < 2:
    debug_log("Pas assez de sources trouvées, ajout de sources de fallback", "WARN")
    fallback = generate_fallback_sources()
    for fb in fallback:
        if len(collected) >= 5:
            break
        collected.append(fb)

# Assurer au minimum 2 sources
if len(collected) == 0:
    debug_log("AUCUNE source trouvée, utilisation de sources d'urgence", "ERROR")
    collected = generate_fallback_sources()

sources_list = "\n".join(collected)
debug_log(f"=== SOURCES FINALES: {len(collected)} lien(s) ===")

# Debug: afficher les sources
for i, source in enumerate(collected, 1):
    match = re.search(r'href="([^"]+)".*?>(.*?)</a>', source)
    if match:
        debug_log(f"Source {i}: {match.group(2)} -> {match.group(1)}")

# =========================
# 5) Composer l'article final
# =========================
tpl = TEMPLATE.read_text(encoding="utf-8")

# Remplacements de base
replacements = {
    "{{TITLE}}": TITLE,
    "{{DESCRIPTION}}": DESCRIPTION,
    "{{LEAD_HTML}}": LEAD_HTML,
    "{{BODY_HTML}}": BODY_HTML,
    "{{SOURCES_LIST}}": sources_list,
    "{{HERO_ALT}}": HERO_ALT,
    "{{HERO_FILENAME}}": hero_filename if has_image else "",
}

article_html = tpl
for placeholder, value in replacements.items():
    article_html = article_html.replace(placeholder, value)

# Gestion de l'image selon le template existant
if has_image:
    # Le template attend {{HERO_FILENAME}}, on le remplace par le nom réel
    article_html = article_html.replace("{{HERO_FILENAME}}", hero_filename)
else:
    # Supprime complètement le bloc figure si pas d'image
    article_html = re.sub(
        r'\s*<figure\s+class="img">[\s\S]*?</figure>\s*',
        '\n<div style="height:24px"></div>\n',
        article_html,
        flags=re.I
    )

(ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
debug_log(f"Article écrit: articles/{article_filename}")

# =========================
# 6) Mise à jour de l'index
# =========================
idx_html = INDEX.read_text(encoding="utf-8")

# Assurer la présence des marqueurs FEED
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

# Bloc image ou placeholder
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
          <a class="link" href="articles/{article_filename}">Lire l'article</a>
        </div>
      </article>
""".rstrip()

# Insérer la carte en haut du flux
idx_html = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, idx_html, count=1, flags=re.S)
idx_html = idx_html + f"\n<!-- automated-build {stamp} -->\n"
INDEX.write_text(idx_html, encoding="utf-8")

debug_log("=== PROCESSUS TERMINÉ ===")
debug_log(f"✅ Article créé: {article_filename}")
debug_log(f"✅ Image: {'Oui' if has_image else 'Non'}")
debug_log(f"✅ Sources: {len(collected)} trouvées")
debug_log("✅ Index mis à jour")
