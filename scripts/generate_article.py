#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, base64, unicodedata
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
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

def ensure_dirs():
    if not INDEX.exists():
        die(f"Fichier manquant: {INDEX.relative_to(ROOT)}")
    if not TEMPLATE.exists():
        die(f"Fichier manquant: {TEMPLATE.relative_to(ROOT)}")
    ARTICLES.mkdir(exist_ok=True)
    IMAGES.mkdir(exist_ok=True)

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""

# =========================
# OpenAI client
# =========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    die("OPENAI_API_KEY manquant (Secrets GitHub > Actions).")
client = OpenAI(api_key=api_key)

# =========================
# Génération IMAGE robuste
# =========================
def save_bytes(path: Path, data: bytes):
    path.write_bytes(data)

def try_download(url: str, timeout=30) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"ℹ️ Téléchargement image échec: {e}")
        return None

def generate_image_with_retries(title: str, out_path: Path) -> bool:
    """
    Tente plusieurs tailles et récupérations (b64_json puis url).
    Retourne True si le fichier a été écrit.
    """
    prompts = [
        f"Illustration photojournalisme, réalisme soigné, contraste modéré, pour l’article « {title} »",
        f"Photo d’illustration éditoriale, sujet correspondant au titre : « {title} », composition nette",
    ]
    sizes = ["768x768", "1024x576", "1024x1024"]  # formats compatibles
    for p in prompts:
        for size in sizes:
            try:
                print(f"→ Génération image ({size})…")
                img = client.images.generate(model="gpt-image-1", prompt=p, size=size)
                d = img.data[0]
                # 1) b64_json
                if getattr(d, "b64_json", None):
                    save_bytes(out_path, base64.b64decode(d.b64_json))
                    print(f"✅ Image écrite (b64) : {out_path}")
                    return True
                # 2) url
                if getattr(d, "url", None):
                    content = try_download(d.url)
                    if content:
                        save_bytes(out_path, content)
                        print(f"✅ Image écrite (url) : {out_path}")
                        return True
            except Exception as e:
                print(f"ℹ️ Tentative image échouée ({size}): {e}")
                continue
    print("⚠️ Impossible de générer l’image après plusieurs tentatives.")
    return False

# =========================
# 1) Génération du corps HTML de l’article (prompt exact)
# =========================
def generate_article_body() -> str:
    prompt_article = """
Rédige un article HTML de 600 à 1000 mots en français sur un sujet d'actualité
contenant un sujet au choix à propos de : 
  - géopolitique mondiale (pro Trump),
  - IA (avancées mais aussi dangers liés à l'IA),
  - disparition de nos libertés,
  - l'arnaque écologique,
  - dette de la France,
  - dilapidation de l'argent des Français,
  - décisions politiques anormales ou contre productives pour la France,
  - dénonciation des hausses d'impôts et de la vie chère,
  - dénonciation du comportement de nos hommes et femmes politiques en France ou au niveau de l'Europe qui n'est pas en adéquation avec ce qu'ils prônent, 
  - tous cas de trahison de la France (vente d'entreprises stratégiques françaises, concession d'exploitation de ressources naturelles françaises par des entreprises étrangères, etc),
Ton : journalistique et engagé à droite.
Contraintes strictes :
- Commence par un <h1> clair (titre).
- Structure ensuite en <h2> + <p>.
- N'ajoute AUCUNE numérotation de référence (pas de [1], [2], [3], etc.).
- N'inclus PAS de section "Références" ni "Sources" dans le corps de l'article.
- Ne mets PAS de <!doctype>, <html>, <head> ni <body>.
Réponds UNIQUEMENT avec le HTML du corps de l’article.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt_article}],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

# =========================
# Main build
# =========================
def main():
    ensure_dirs()

    # 1) Article
    try:
        body_html = generate_article_body()
        print("✅ Article généré (texte).")
    except Exception as e:
        die(f"Échec génération texte: {e}")

    # 2) Titre / lead / corps (et nettoyage “Sources/Références” potentiels)
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

    # 3) Image héro — robustifiée
    has_image = generate_image_with_retries(TITLE, IMAGES / hero_filename)

    # 4) SOURCES — **SUPPRIMÉ** : tu les ajoutes manuellement dans l’article après publication
    sources_list = ""  # Laisse la <ol> vide dans le template

    # 5) Composer l’article final (template harmonisé)
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
        # Force chemin absolu dans l’article (il vit sous /articles/)
        article_html = re.sub(
            r'src=["\']/?images/\{\{HERO_FILENAME\}\}["\']',
            f'src="/images/{hero_filename}"',
            article_html,
            flags=re.I
        )
    else:
        # Si image absente malgré les tentatives, on laisse un petit espace
        article_html = re.sub(
            r'\s*<figure\s+class="img">[\s\S]*?</figure>\s*',
            '\n<div style="height:24px"></div>\n',
            article_html,
            flags=re.I
        )

    (ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
    print(f"✅ Article écrit: articles/{article_filename}")

    # 6) Mettre à jour l’index (vignette tout en haut)
    idx_html = INDEX.read_text(encoding="utf-8")
    if "<!-- FEED:start -->" not in idx_html or "<!-- FEED:end -->" not in idx_html:
        body_open = re.search(r"<body[^>]*>", idx_html, flags=re.I)
        pos = body_open.end() if body_open else 0
        idx_html = idx_html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + idx_html[pos:]

    thumb = (
        f'<img src="images/{hero_filename}" alt="{HERO_ALT}">'
        if has_image else
        '<div style="aspect-ratio:16/9;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.03)"></div>'
    )

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

if __name__ == "__main__":
    main()
