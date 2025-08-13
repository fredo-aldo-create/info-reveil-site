#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime as dt
from pathlib import Path
import re
import sys
import hashlib
import shutil
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
TEMPLATES = ROOT / "templates"
DRAFTS = ROOT / "drafts"
IMAGES = ROOT / "images"

TEMPLATE = TEMPLATES / "article_template.html"
DRAFT_BODY = DRAFTS / "today.html"
DRAFT_HERO = DRAFTS / "hero.jpg"  # image fournie par l'agent
AUTHOR = "Rédaction INFO-RÉVEIL"

def die(msg):
    print(f"❌ {msg}")
    sys.exit(1)

def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+","-", text).strip("-").lower()
    return text or "article"

# --- prérequis ---
for p in [INDEX, TEMPLATE]:
    if not p.exists():
        die(f"Fichier manquant: {p.relative_to(ROOT)}")

ARTICLES.mkdir(exist_ok=True)
IMAGES.mkdir(exist_ok=True)
DRAFTS.mkdir(exist_ok=True)

# --- récupérer le corps de l'article (HTML) ---
if not DRAFT_BODY.exists():
    # Brouillon minimal si l'agent n'a rien fourni
    DRAFT_BODY.write_text("<p>[Brouillon] Corps de l’article non fourni. Remplacez drafts/today.html.</p>", encoding="utf-8")

body_html = DRAFT_BODY.read_text(encoding="utf-8").strip()

# --- métadonnées minimales (à terme: l'agent les remplit) ---
today = dt.datetime.now().astimezone()
date_str = today.strftime("%d/%m/%Y")
stamp = today.strftime("%Y-%m-%d %H:%M:%S %z")

# heuristique titre = premier <h1> ou sinon phrase par défaut
m_title = re.search(r"<h1[^>]*>(.*?)</h1>", body_html, flags=re.I|re.S)
TITLE = m_title.group(1).strip() if m_title else "Titre provisoire"
DESCRIPTION = "Résumé court de l’article (150–160 caractères)."
CHAPO = "Chapo de 2–3 phrases accrocheuses."
HERO_ALT = "Illustration de l’article"
HERO_CAPTION = "Crédit : IA/Info-Réveil"

slug = f"{today.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

# --- image héro ---
if DRAFT_HERO.exists():
    shutil.copyfile(DRAFT_HERO, IMAGES / hero_filename)
    print(f"✅ Image héros copiée: images/{hero_filename}")
else:
    # fallback sur une image existante
    fallback = IMAGES / "eolienne.jpg"
    if fallback.exists():
        shutil.copyfile(fallback, IMAGES / hero_filename)
        print(f"ℹ️ Image héros absente, fallback utilisé: images/{hero_filename}")
    else:
        print("⚠️ Aucune image trouvée: la balise <img> référencera un fichier manquant.")

# --- composer l'article à partir du template ---
tpl = TEMPLATE.read_text(encoding="utf-8")
sources_list = "<li>[1] Exemple de source (remplacer)</li>"

article_html = (tpl
    .replace("{{TITLE}}", TITLE)
    .replace("{{DESCRIPTION}}", DESCRIPTION)
    .replace("{{AUTHOR}}", AUTHOR)
    .replace("{{DATE}}", date_str)
    .replace("{{HERO_FILENAME}}", hero_filename)
    .replace("{{HERO_ALT}}", HERO_ALT)
    .replace("{{HERO_CAPTION}}", HERO_CAPTION)
    .replace("{{CHAPO}}", CHAPO)
    .replace("{{BODY_HTML}}", body_html)
    .replace("{{SOURCES_LIST}}", sources_list)
)

(ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
print(f"✅ Article écrit: articles/{article_filename}")

# --- garantir FEED markers dans index.html ---
html = INDEX.read_text(encoding="utf-8")
if "<!-- FEED:start -->" not in html or "<!-- FEED:end -->" not in html:
    grid_open = re.search(r"<(main|div)([^>]*\\bclass=[\"'][^\"']*\\bgrid\\b[^\"']*[\"'][^>]*)>", html, flags=re.I)
    if grid_open:
        pos = grid_open.end()
        html = html[:pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + html[pos:]
        print("ℹ️ FEED markers ajoutés dans .grid.")
    else:
        body_open = re.search(r"<body[^>]*>", html, flags=re.I)
        if not body_open:
            die("Impossible de trouver <body> pour insérer le flux.")
        pos = body_open.end()
        html = html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + html[pos:]
        print("ℹ️ FEED markers ajoutés après <body>.")

# --- insérer la carte en haut du feed ---
card_html = f"""
      <!-- card-{slug} -->
      <article class="card">
        <a class="thumb" href="articles/{article_filename}" aria-label="Lire : {TITLE}">
          <img src="images/{hero_filename}" alt="{HERO_ALT}">
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

new_html = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, html, count=1, flags=re.S)
if new_html == html:
    die("Aucun changement détecté dans index.html (substitution non effectuée).")

INDEX.write_text(new_html, encoding="utf-8")
with INDEX.open("a", encoding="utf-8") as f:
    f.write(f"\n<!-- automated-build {stamp} -->\n")
print("✅ Vignette insérée + index.html mis à jour.")
