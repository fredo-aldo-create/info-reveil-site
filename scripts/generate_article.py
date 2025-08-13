#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import openai
import datetime as dt
from pathlib import Path
import re
import sys
import base64
import unicodedata

# --- Chemins ---
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
TEMPLATES = ROOT / "templates"
IMAGES = ROOT / "images"
TEMPLATE = TEMPLATES / "article_template.html"
AUTHOR = "Rédaction INFO-RÉVEIL"

# --- Fonctions utilitaires ---
def die(msg):
    print(f"❌ {msg}")
    sys.exit(1)

def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+","-", text).strip("-").lower()
    return text or "article"

# --- Vérification fichiers ---
for p in [INDEX, TEMPLATE]:
    if not p.exists():
        die(f"Fichier manquant: {p.relative_to(ROOT)}")
ARTICLES.mkdir(exist_ok=True)
IMAGES.mkdir(exist_ok=True)

# --- Clé API OpenAI ---
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    die("Clé API OpenAI absente (OPENAI_API_KEY).")

# --- 1) Génération du texte de l'article ---
prompt_article = """
Rédige un article HTML de 600 à 1000 mots en français sur un sujet d'actualité
concernant l'IA, l'économie, la politique ou la société, avec un ton engagé (droite).
Structure ainsi :
- un <h1> clair en tête
- plusieurs <h2> pour structurer
- paragraphes <p> avec citations [1][2][3]...
Ne pas inclure <html>, <head> ou <body>.
"""
resp = openai.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role":"user", "content": prompt_article}],
    temperature=0.7
)
body_html = resp.choices[0].message.content.strip()
print("✅ Article généré par l'IA.")

# --- 2) Extraction du titre & slug ---
m_title = re.search(r"<h1[^>]*>(.*?)</h1>", body_html, flags=re.I|re.S)
TITLE = m_title.group(1).strip() if m_title else "Titre provisoire"
DESCRIPTION = "Résumé court de l’article."
CHAPO = "Chapo de 2–3 phrases accrocheuses."
HERO_ALT = "Illustration de l’article"
HERO_CAPTION = "Crédit : IA/Info-Réveil"

today = dt.datetime.now().astimezone()
date_str = today.strftime("%d/%m/%Y")
stamp = today.strftime("%Y-%m-%d %H:%M:%S %z")
slug = f"{today.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

# --- 3) Génération de l'image héro ---
img_prompt = f"Illustration réaliste, style photojournalisme, pour un article intitulé '{TITLE}'"
img_resp = openai.images.generate(
    model="gpt-image-1",
    prompt=img_prompt,
    size="1024x1024"
)
image_b64 = img_resp.data[0].b64_json
image_bytes = base64.b64decode(image_b64)
(IMAGES / hero_filename).write_bytes(image_bytes)
print(f"✅ Image héro générée: images/{hero_filename}")

# --- 4) Composition de l'article final ---
tpl = TEMPLATE.read_text(encoding="utf-8")
sources_list = "<li>[1] Exemple de source (à compléter)</li>"
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

# --- 5) Insertion de la vignette dans index.html ---
html = INDEX.read_text(encoding="utf-8")
if "<!-- FEED:start -->" not in html or "<!-- FEED:end -->" not in html:
    grid_open = re.search(r"<(main|div)([^>]*\\bclass=[\"'][^\"']*\\bgrid\\b[^\"']*[\"'][^>]*)>", html, flags=re.I)
    if grid_open:
        pos = grid_open.end()
        html = html[:pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + html[pos:]
    else:
        body_open = re.search(r"<body[^>]*>", html, flags=re.I)
        if not body_open:
            die("Impossible de trouver <body> pour insérer le flux.")
        pos = body_open.end()
        html = html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + html[pos:]

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
INDEX.write_text(new_html, encoding="utf-8")
with INDEX.open("a", encoding="utf-8") as f:
    f.write(f"\n<!-- automated-build {stamp} -->\n")
print("✅ Vignette insérée + index.html mis à jour.")
