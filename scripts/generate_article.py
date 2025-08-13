#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, base64, re, sys, unicodedata
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI

# =========================
# Chemins / constantes
# =========================
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
IMAGES = ROOT / "images"
TEMPLATES = ROOT / "templates"
TEMPLATE = TEMPLATES / "article_template_ir.html"  # <-- on utilise ce template à chaque article

AUTHOR = "Rédaction INFO-RÉVEIL"

def die(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+","-", text).strip("-").lower()
    return text or "article"

# Vérifs de présence
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
# 1) Génération du corps HTML de l’article
# =========================
prompt_article = """
Rédige un article HTML de 600 à 1000 mots en français sur un sujet d'actualité
contenant IA, arnaque écologique, dette de la France, décision politiques anormales ou contre productives pour la France, dénonciation des hausses d’impôts et de la vie chère, dénonciation du comportement de nos hommes et femmes politiques en France ou au niveau de l'Europe qui n'est pas en adéquation avec ce qu'ils prônent, tous cas de trahison de la France (vente d'entreprises stratégiques françaises, concession d'exploitation de ressources naturelles françaises par des entreprises étrangères, etc), avec un ton journalistique et engagé à droite.
Contraintes strictes :
- Commence par un <h1> clair (titre).
- Structure ensuite en <h2> + <p>.
- Ajoute des références [1][2][3]… dans le texte là où c’est pertinent.
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
    print("✅ Article généré (texte).")
except Exception as e:
    die(f"Échec génération texte: {e}")

# =========================
# 2) Titre, lead (1er <p>) et reste du corps
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

# Génération automatique d'un résumé court (150–160 caractères) pour la vignette
prompt_desc = f"""
À partir de l'article HTML suivant, écris un résumé concis et engageant en français
de 150 à 160 caractères maximum (pas de HTML, pas de guillemets).
Article :
{body_html}
"""

try:
    resp_desc = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user", "content": prompt_desc}],
        temperature=0.5,
    )
    DESCRIPTION = resp_desc.choices[0].message.content.strip()
    print(f"✅ Résumé généré pour la vignette : {DESCRIPTION}")
except Exception as e:
    DESCRIPTION = TITLE  # fallback : on met le titre si erreur
    print(f"⚠️ Échec génération résumé : {e}")

HERO_ALT = "Illustration de l’article"

now = datetime.now(timezone.utc).astimezone()
date_str = now.strftime("%d/%m/%Y")
stamp = now.strftime("%Y-%m-%d %H:%M:%S %z")
slug = f"{now.date().isoformat()}-{slugify(TITLE)[:60]}"
article_filename = f"{slug}.html"
hero_filename = f"{slug}-hero.jpg"

# =========================
# 3) Génération de l'image héro (AUCUN fallback)
# =========================
has_image = False
img_prompt = f"Illustration réaliste, style photojournalisme, pour un article intitulé « {TITLE} »"
try:
    img_resp = client.images.generate(model="gpt-image-1", prompt=img_prompt, size="1024x1024")
    image_b64 = img_resp.data[0].b64_json
    (IMAGES / hero_filename).write_bytes(base64.b64decode(image_b64))
    has_image = True
    print(f"✅ Image générée: images/{hero_filename}")
except Exception as e:
    # Aucun fallback : on laissera un espace vide dans l'article et la vignette
    has_image = False
    print(f"ℹ️ Pas d'image générée ({e}). Un espace vide sera affiché.")

# =========================
# 4) Génération de la liste de sources cliquables
# =========================
prompt_sources = f"""
À partir de l'article HTML ci-dessous, produis une liste HTML <li>…</li> de 3 à 8 sources FIABLES,
avec des liens cliquables complets : <li><a href="URL" target="_blank" rel="noopener noreferrer">Titre de la source</a></li>.
Exclusivement des <li> (pas de texte autour).
Article :
{body_html}
"""
try:
    resp_sources = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt_sources}],
        temperature=0.3,
    )
    sources_list_raw = resp_sources.choices[0].message.content.strip()
    lis = re.findall(r"<li[\s\S]*?</li>", sources_list_raw, flags=re.I)
    sources_list = "\n".join(lis) if lis else '<li><a href="#" target="_blank" rel="noopener noreferrer">Source à compléter</a></li>'
    print("✅ Sources cliquables générées.")
except Exception as e:
    print(f"⚠️ Échec génération sources ({e}); placeholder utilisé.")
    sources_list = '<li><a href="#" target="_blank" rel="noopener noreferrer">Source à compléter</a></li>'

# =========================
# 5) Composer l'article final avec le template harmonisé
#    - Si image absente : on remplace <figure class="img">…</figure> par un espace vide.
#    - Sinon : on force le chemin absolu /images/<fichier>
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
    # Corriger le chemin pour être absolu depuis la racine
    article_html = re.sub(
        r'src=["\']images/\{\{HERO_FILENAME\}\}["\']',
        f'src="/images/{hero_filename}"',
        article_html,
        flags=re.I
    )
else:
    # Supprimer la figure d'image et la remplacer par un espace vide
    article_html = re.sub(
        r'\s*<figure\s+class="img">[\s\S]*?</figure>\s*',
        '\n<div style="height:24px"></div>\n',
        article_html,
        flags=re.I
    )

(ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
print(f"✅ Article écrit: articles/{article_filename}")

# =========================
# 6) Insérer la carte en haut du flux d'index.html
#    - Si pas d'image, on met un bloc vide au lieu d’un <img>.
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
    # Bloc vide 16/9 pour éviter l’icône d’image cassée
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
idx_html = idx_html + f"\n<!-- automated-build {stamp} -->\n"
INDEX.write_text(idx_html, encoding="utf-8")
print("✅ Vignette insérée + index.html mis à jour.")
