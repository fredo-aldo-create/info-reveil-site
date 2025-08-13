#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, base64, re, sys, unicodedata, shutil
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI

# ---- chemins / constantes
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
IMAGES = ROOT / "images"
TEMPLATES = ROOT / "templates"
TEMPLATE = TEMPLATES / "article_template_ir.html"  # <= le nouveau template harmonisé

AUTHOR = "Rédaction INFO-RÉVEIL"

def die(msg): print(f"❌ {msg}"); sys.exit(1)

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+","-", text).strip("-").lower()
    return text or "article"

# ---- vérifs
for p in [INDEX, TEMPLATE]:
    if not p.exists(): die(f"Fichier manquant: {p.relative_to(ROOT)}")
ARTICLES.mkdir(exist_ok=True); IMAGES.mkdir(exist_ok=True)

# ---- OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key: die("OPENAI_API_KEY manquant")
client = OpenAI(api_key=api_key)

# ---- 1) Générer le corps HTML (avec <h1>, <h2>, <p> et [1][2]…)
prompt_article = """
Rédige un article HTML de 600 à 1000 mots en français, ton engagé (droite),
sur un sujet d'actualité (IA, économie, politique ou société). Contraintes :
- Commence par un <h1> clair.
- Structure avec des <h2>.
- Paragraphes en <p> avec citations [1][2][3]... dans le texte.
- Ne mets PAS <html>, <head> ni <body>.
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
    die(f"Echec génération texte: {e}")

# ---- 2) Extraire le titre, lead (1er <p> après le <h1>) et le reste
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

DESCRIPTION = "Résumé court de l’article (150–160 caractères)."
HERO_ALT = "Illustration de l’article"
today = datetime.now(timezone.utc).astimezone()
date_str = today.strftime("%d/%m/%Y")
stamp = today.strftime("%Y-%m-%d %H:%M:%S %z")
slug = f"{today.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

# ---- 3) Générer l'image héro (ou fallback)
img_prompt = f"Illustration réaliste, style photojournalisme, pour un article intitulé « {TITLE} »"
try:
    img_resp = client.images.generate(model="gpt-image-1", prompt=img_prompt, size="1024x1024")
    image_b64 = img_resp.data[0].b64_json
    (IMAGES / hero_filename).write_bytes(base64.b64decode(image_b64))
    print(f"✅ Image générée: images/{hero_filename}")
except Exception as e:
    print(f"⚠️ Échec image IA ({e}) — fallback sur une image locale si dispo.")
    fallback = IMAGES / "eolienne.jpg"
    if fallback.exists(): shutil.copyfile(fallback, IMAGES / hero_filename)
    else: (IMAGES / hero_filename).write_bytes(b"")

# ---- 4) Préparer la liste des sources (placeholder pour l’instant)
# (option: faire générer une liste <li>…</li> par l’IA et l'injecter)
sources_list = "<li>[1] Source à compléter</li>"

# ---- 5) Composer l'article final avec le template harmonisé
tpl = TEMPLATE.read_text(encoding="utf-8")
article_html = (tpl
    .replace("{{TITLE}}", TITLE)
    .replace("{{HERO_FILENAME}}", hero_filename)
    .replace("{{HERO_ALT}}", HERO_ALT)
    .replace("{{LEAD_HTML}}", LEAD_HTML)
    .replace("{{BODY_HTML}}", BODY_HTML)
    .replace("{{SOURCES_LIST}}", sources_list)
)
(ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
print(f"✅ Article écrit: articles/{article_filename}")

# ---- 6) Insérer la carte en haut du feed (inchangé)
idx_html = INDEX.read_text(encoding="utf-8")
if "<!-- FEED:start -->" not in idx_html or "<!-- FEED:end -->" not in idx_html:
    grid_open = re.search(r"<(main|div)([^>]*\\bclass=[\"'][^\"']*\\bgrid\\b[^\"']*[\"'][^>]*)>", idx_html, flags=re.I)
    if grid_open:
        pos = grid_open.end()
        idx_html = idx_html[:pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + idx_html[pos:]
    else:
        body_open = re.search(r"<body[^>]*>", idx_html, flags=re.I)
        if not body_open: die("Impossible de trouver <body> pour insérer le feed.")
        pos = body_open.end()
        idx_html = idx_html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + idx_html[pos:]

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

idx_html = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, idx_html, count=1, flags=re.S)
INDEX.write_text(idx_html + f"\n<!-- automated-build {stamp} -->\n", encoding="utf-8")
print("✅ Vignette insérée + index.html mis à jour.")
