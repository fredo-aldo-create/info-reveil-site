#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import requests
import json
from datetime import datetime

# =========================
# 1. Fonction de génération
# =========================
def generate_article_body():
    """
    Appelle l'API OpenAI pour générer un article HTML.
    """
    import openai

    openai.api_key = os.getenv("OPENAI_API_KEY")

    prompt = f"""
Rédige un article HTML de 600 à 1000 mots en français sur un sujet d'actualité
contenant un sujet au choix à propos de : géopolitique mondiale (pro Trump),
IA (avancées mais aussi dangers liés à l'IA), disparition de nos libertés,
l'arnaque écologique, dette de la France, dilapidation de l'argent des Français,
décisions politiques anormales ou contre productives pour la France, dénonciation
des hausses d'impôts et de la vie chère, dénonciation du comportement de nos
hommes et femmes politiques en France ou autres sujets dans cet esprit.

Contraintes strictes :
- Commence par un <h1> clair (titre).
- Structure ensuite en <h2> + <p>.
- N'ajoute AUCUNE référence, AUCUN chiffre entre crochets du type [1] [2] [3], et n'emploie pas <sup> pour des renvois.
- N'inclus PAS de section "Références" ni "Sources" dans le corps de l'article.
- Ne mets PAS de <!doctype>, <html>, <head> ni <body>.
Réponds UNIQUEMENT avec le HTML du corps de l’article.
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )

    return response.choices[0].message["content"]


# =========================
# 2. Fonction de nettoyage
# =========================
def strip_citation_markers(html: str) -> str:
    '''
    Supprime les marqueurs de type [1], <sup>[1]</sup>, liens "[1]" et autres renvois chiffrés.
    '''
    # Supprimer <sup>[1]</sup>, <sup>1</sup>, <sup><a>1</a></sup>, etc.
    html = re.sub(r'<sup[^>]*>\s*(\[\s*\d+\s*\]|<a[^>]*>\s*\[\s*\d+\s*\]\s*</a>|\d+)\s*</sup>', '', html, flags=re.I)

    # Supprimer des ancres ou liens qui ne contiennent qu'un numéro entre crochets
    html = re.sub(r'<a[^>]*>\s*\[\s*\d+\s*\]\s*</a>', '', html, flags=re.I)

    # Supprimer les numéros nus entre crochets (en évitant d'autres usages évidents)
    html = re.sub(r'(?<![\w/])\[\s*\d+\s*\](?![\w/])', '', html)

    # Supprimer des " [i]" romains éventuels (rare)
    html = re.sub(r'(?<![\w/])\[\s*[ivxlcdmIVXLCDM]+\s*\](?![\w/])', '', html)

    # Nettoyage espaces multiples
    html = re.sub(r'\s{2,}', ' ', html).strip()
    return html


# =========================
# 3. Génération + Nettoyage
# =========================
print("⏳ Génération de l'article...")
body_html = generate_article_body()
# Nettoyage des marqueurs de références
body_html = strip_citation_markers(body_html)
print("✅ Article généré (texte).")

# =========================
# 4. Extraction titre + chapeau
# =========================
m_h1 = re.search(r"<h1[^>]*>.*?</h1>", body_html, re.S | re.I)
if not m_h1:
    raise ValueError("❌ Aucun <h1> trouvé dans le texte généré.")

TITLE_HTML = m_h1.group(0)
after_h1 = body_html[m_h1.end():].strip()

m_first_p = re.search(r"<p[^>]*>.*?</p>", after_h1, re.S | re.I)
if not m_first_p:
    raise ValueError("❌ Aucun <p> trouvé après le <h1>.")

LEAD_HTML = strip_citation_markers(
    m_first_p.group(0).replace("<p", "<p class=\"lead\"", 1)
)
BODY_HTML = strip_citation_markers(
    after_h1[m_first_p.end():].strip()
)

# =========================
# 5. Injection dans le template
# =========================
with open("article_template_ir.html", "r", encoding="utf-8") as f:
    template_html = f.read()

final_html = template_html.replace("{{TITLE_HTML}}", TITLE_HTML)
final_html = final_html.replace("{{LEAD_HTML}}", LEAD_HTML)
final_html = final_html.replace("{{BODY_HTML}}", BODY_HTML)

# =========================
# 6. Sauvegarde
# =========================
date_str = datetime.now().strftime("%Y-%m-%d")
filename = f"article_{date_str}.html"
with open(filename, "w", encoding="utf-8") as f:
    f.write(final_html)

print(f"💾 Article sauvegardé sous {filename}")
input("Appuyez sur Entrée pour fermer ce terminal...")
