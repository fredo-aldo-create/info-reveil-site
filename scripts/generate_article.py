#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime as dt
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"

if not INDEX.exists():
    print("❌ index.html introuvable à la racine du dépôt.")
    sys.exit(1)

html = INDEX.read_text(encoding="utf-8")

# 1) S'assurer que des marqueurs FEED existent, sinon les créer autour de la grille
if "<!-- FEED:start -->" not in html or "<!-- FEED:end -->" not in html:
    # chercher la grille principale
    grid_open = re.search(r"<(main|div)([^>]*\\bclass=[\"'][^\"']*\\bgrid\\b[^\"']*[\"'][^>]*)>", html, flags=re.I)
    if not grid_open:
        print("❌ Impossible de trouver le conteneur .grid pour y insérer le flux.")
        sys.exit(1)
    start_tag = grid_open.group(0)
    insert_pos = grid_open.end()
    html = html[:insert_pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + html[insert_pos:]
    print("ℹ️ Marqueurs FEED ajoutés automatiquement autour de la grille.")

# 2) Construire la carte à insérer
today = dt.datetime.now().astimezone().strftime("%d/%m/%Y")
card_html = f"""
      <article class="card">
        <a class="thumb" href="article_exemple.html" aria-label="Lire : Article de test">
          <img src="images/eolienne.jpg" alt="Illustration de test">
        </a>
        <div class="card-body">
          <h2 class="title">[TEST] Carte insérée automatiquement</h2>
          <p class="excerpt">Vérification du workflow GitHub Actions et de l’insertion en tête de flux.</p>
          <div class="meta">
            <span class="badge">Automatisation</span>
            <span>Publié le {today}</span>
          </div>
          <a class="link" href="article_exemple.html">Lire l’article</a>
        </div>
      </article>
""".rstrip()

# 3) Insérer juste après FEED:start
new_html = re.sub(
    r"(<!-- FEED:start -->)",
    r"\\1\n" + card_html,
    html,
    count=1,
    flags=re.S
)

if new_html == html:
    print("⚠️ Aucun changement détecté (les marqueurs existent mais la substitution n'a pas eu lieu).")
    sys.exit(0)

INDEX.write_text(new_html, encoding="utf-8")
print("✅ Vignette insérée en haut du feed.")
