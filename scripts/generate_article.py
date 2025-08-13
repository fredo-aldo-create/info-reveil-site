#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime as dt
from pathlib import Path
import re
import sys
import hashlib

# --- Chemins ---
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLE = ROOT / "article_exemple.html"
IMAGES = ROOT / "images"

def die(msg):
    print(f"❌ {msg}")
    sys.exit(1)

if not INDEX.exists():
    die("index.html introuvable à la racine du dépôt.")

# --- Image de test (placeholder) ---
if not (IMAGES / "eolienne.jpg").exists():
    print("ℹ️ images/eolienne.jpg manquante — la carte s'affichera sans image.")

# --- Créer/mettre à jour un article de test pour que le lien de la carte soit valide ---
stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
ARTICLE.write_text(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Article de test</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="styles.css"></head>
<body><main class="wrap"><h1>Article de test</h1>
<p>Ceci est un article généré automatiquement pour valider le workflow.</p>
<p>Horodatage: {stamp}</p>
<p>Vous pouvez supprimer ce fichier après le test.</p>
</main></body></html>""", encoding="utf-8")
print("✅ article_exemple.html écrit/actualisé.")

# --- Lecture d'index.html ---
html = INDEX.read_text(encoding="utf-8")

# --- S'assurer que les marqueurs FEED existent ---
if "<!-- FEED:start -->" not in html or "<!-- FEED:end -->" not in html:
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

# --- Construire et injecter la carte au sommet du flux ---
uid = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:8]
today_fr = dt.datetime.now().astimezone().strftime("%d/%m/%Y")

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
            <span>Publié le {today_fr}</span>
          </div>
          <a class="link" href="article_exemple.html">Lire l’article</a>
        </div>
      </article>
""".rstrip()

new_html = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, html, count=1, flags=re.S)
if new_html == html:
    die("Aucun changement détecté dans index.html (substitution non effectuée).")

# --- Écriture de index.html + commentaire horodaté pour garantir un diff ---
INDEX.write_text(new_html, encoding="utf-8")
with INDEX.open("a", encoding="utf-8") as f:
    f.write(f"\n<!-- automated-build {stamp} -->\n")

print("✅ Vignette insérée en haut du feed & index.html mis à jour.")
