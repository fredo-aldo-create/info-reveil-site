#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime as dt
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"

# Carte "bouchon" (remplace plus tard par la vraie génération d'article + image)
today = dt.datetime.now().strftime("%-d %b %Y").replace("Aug", "août").replace("Sep", "sept.")
card_html = f"""
      <article class="card">
        <a class="thumb" href="article_exemple.html" aria-label="Lire : Article de test">
          <img src="images/eolienne.jpg" alt="Illustration">
        </a>
        <div class="card-body">
          <h2 class="title">[TEST] Nouvelle carte insérée automatiquement</h2>
          <p class="excerpt">Ceci est une vignette de test ajoutée par le workflow GitHub Actions.</p>
          <div class="meta">
            <span class="badge">Automat.</span>
            <span>Publié le {today}</span>
          </div>
          <a class="link" href="article_exemple.html">Lire l’article</a>
        </div>
      </article>
"""

html = INDEX.read_text(encoding="utf-8")
m = re.search(r"(<!-- FEED:start -->)(.*?)(<!-- FEED:end -->)", html, flags=re.S)
if not m:
    raise SystemExit("Marqueurs FEED introuvables dans index.html")

new_html = html[:m.end(1)] + "\n" + card_html + "\n" + html[m.start(3):]
INDEX.write_text(new_html, encoding="utf-8")
print("✅ Vignette insérée en haut du feed.")

