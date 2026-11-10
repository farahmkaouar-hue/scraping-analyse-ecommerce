# Scraping et analyse de produits e-commerce

Collecte automatique de produits cosmétiques sur un site de vente en ligne, puis analyse des prix et des catégories.

## Démarche

1. **Scraping** (`01_scraping.ipynb`) : collecte des produits par catégorie (visage, yeux, lèvres, cheveux) avec Selenium : nom, prix, catégorie, note, nombre d'avis, ingrédients et labels. Environ 330 produits au total.
2. **Analyse** (`02_analyse.ipynb`) :
   - nettoyage et exploration des prix ;
   - segmentation des produits par K-Means, après une analyse en composantes principales ;
   - prédiction du prix à partir du texte des fiches produits (TF-IDF et Random Forest).

Les résultats ont aussi été présentés dans des tableaux de bord Power BI.

## Données

Les fichiers de données collectés ne sont pas publiés dans ce dépôt.

Technologies : Python, Selenium, pandas, scikit-learn.
