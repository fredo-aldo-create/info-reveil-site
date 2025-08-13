#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime as dt
from pathlib import Path
import re
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLE = ROOT / "article_exemple.html"
IMAGES = ROOT / "images"

def die(msg):
    print(f"❌ {msg}")
    sys.exit(1)

if not INDEX.exists():
    die("index.html introuvable à la racine du dépôt.")

# 0) S'assurer que l'image existe (on utilise eolienne.jpg comme placeholder)
if not (IMAGES / "eolienne.jpg").exists():
    print("ℹ️ images/eolienne.jpg manquante — la carte sera quand même insérée mais l'image ne s'affichera pas.")

# 1) Créer un petit article de test si absent
if not ARTICLE.exists():
    ARTICLE.write_text("""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Article de test</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="styles.css"></head>
<body><main class="wrap"><h1>Article de test</h1>
<p>Ceci est un article généré automatiquement pour valider le workflow.</p>
<p>Vous pouvez supprimer ce fichier après le test.</p>
</main></body></html>""", encoding="utf-8")
    print("✅ article_exemple.html créé.")

html = INDEX.read_text(encoding="utf-8")

# 2) Garantir la présence des marqueurs FEED
if "<!-- FEED:start -->" not in html or "<!-- FEED:end -->" not in html:
    # on essaye d'insérer dans le premier conteneur .grid ; sinon juste après <body>
    grid_open = re.search(r"<(main|div)([^>]*\\bclass=[\"'][^\"']*\\bgrid\\b[^\"']*[\"'][^>]*)>", html, flags=re.I)
    if grid_open:
        insert_pos = grid_open.end()
        html = html[:insert_pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + html[insert_pos:]
        print("ℹ️ Marqueurs FEED ajoutés dans le conteneur .grid.")
    else:
        body_open = re.search(r"<body[^>]*>", html, flags=re.I)
        if not body_open:
            die("Impossible de trouver <body> pour insérer le flux.")
        insert_pos = body_open.end()
        html = html[:insert_pos] + "\n<main class=\"grid\">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n" + html[insert_pos:]
        print("ℹ️ Marqueurs FEED ajoutés après <body> (création d’un <main class=\"grid\">).")

# 3) Construire une carte unique (hash du jour pour éviter les doublons exacts)
today = dt.datetime.now().astimezone()
stamp = today.strftime("%Y-%m-%d %H:%M:%S %z")
uid = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:8]

card_html = f"""
      <!-- card-{uid} -->
      <article class="card">
        <a class="thumb" href="article_exemple.html" aria-label="Lire : Article de test">
          <img src="images/eolienne.jpg" alt="Illustration de test">
        </a>
        <div class="card-body">
          <h2 class="title">[TEST] Carte insérée automatiquement</h2>
          <p class="excerpt">Vérification workflow GitHub Actions — {stamp}</p>
          <div class="meta">
            <span class="badge">Automatisation</span>
            <span>Publié le {today.strftime("%d/%m/%Y")}</span>
          </div>
          <a class="link" href="article_exemple.html">Lire l’article</a>
        </div>
      </article>
""".rstrip()

# 4) Éviter de réinsérer si une carte test récente existe déjà
if "article_exemple.html" in html and "Carte insérée automatiquement" in html:
    print("ℹ️ Une carte de test existe déjà. On insère quand même une nouvelle version horodatée pour forcer le diff.")

# 5) Injection juste après FEED:start
new_html = re.sub(r"(<!-- FEED:start -->)", r"\\1\n" + card_html, html, count=1, flags=re.S)

if new_html == html:
    die("Aucun changement détecté dans index.html (substitution non effectuée).")

INDEX.write_text(new_html, encoding="utf-8")
print("✅ Vignette insérée en haut du feed & index.html mis à jour.")
