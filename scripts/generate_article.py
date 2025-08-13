# ... tout le code d'avant inchangé jusqu'à INDEX.write_text(new_html, encoding="utf-8")

INDEX.write_text(new_html, encoding="utf-8")
print("✅ Vignette insérée en haut du feed & index.html mis à jour.")

# 6) Ajout d'un commentaire horodaté pour forcer un diff Git (au cas où le HTML est identique)
with INDEX.open("a", encoding="utf-8") as f:
    f.write(f"\n<!-- automated-build {stamp} -->\n")
print("ℹ️ Commentaire de build ajouté en fin de index.html pour garantir un diff.")

# 7) (Re)créer/mettre à jour l'article de test avec timestamp pour garantir un diff
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
