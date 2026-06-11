# MPP Espérance — extension Chrome

## Installation

1. Ouvrir `chrome://extensions`.
2. Activer le mode développeur.
3. Cliquer sur `Charger l'extension non empaquetée`.
4. Sélectionner le dossier `extension/` de ce dépôt.
5. Ouvrir ou recharger `https://mpp.football/`, puis se connecter normalement.

Le popup de l'extension indique les matchs MPP détectés, les associations
Polymarket réussies et les erreurs éventuelles.

## Fonctionnement et sécurité

- Aucun token MPP n'est demandé, lu ou stocké.
- `page-hook.js` observe uniquement les réponses MPP déjà reçues par la page.
- `background.js` lit l'API publique Polymarket sans clé.
- L'extension ne remplit et n'envoie aucun pronostic.
- Une issue est conseillée si son espérance est à moins de 1 point du maximum.
- Les espérances sont ajoutées directement sous les trois quotations MPP.
- Chaque case affiche le nom, la probabilité Polymarket, le meilleur score
  estimé pour cette issue et l'espérance totale.
- Un clic sur le bloc d'espérance ouvre le détail des trois meilleurs scores de
  chaque issue dans trois colonnes avec une animation progressive. Ouvrir un
  autre match ferme le précédent.
- Le bloc et le détail distinguent la probabilité de l'issue, la probabilité du
  score exact, le gain si réalisé et l'espérance.
- Une espérance de 50 points ou plus utilise un traitement visuel doré.
- Le popup distingue les matchs reçus, trouvés, affichés et non trouvés.
- Le cache Polymarket ne conserve que les marchés 1N2 utiles et reste sous le
  quota de stockage Chrome.

Calcul :

`espérance totale = P(issue) × quotation MPP + P(score) × bonus MPP estimé`

Le score est modélisé par deux lois de Poisson calibrées sur le 1N2 Polymarket.
La rareté utilise en priorité le kNN supervisé embarqué dans
`rarity-label-model.js` (le même modèle que le bot, entraîné sur les bonus
réellement attribués par MPP). Quand les parts de paris ne sont pas
disponibles, elle se replie sur le modèle historique terrain neutre de
`neutral-score-model.js` (fusion miroir des victoires, interpolation entre
tranches de quotation), puis sur une heuristique comportementale.

Les modèles embarqués se régénèrent avec :

```bash
PYTHONPATH=src:scripts python3.11 scripts/build_supervised_rarity_model.py
PYTHONPATH=src:scripts python3.11 scripts/build_mpp_neutral_score_model.py
PYTHONPATH=src:scripts python3.11 scripts/export_neutral_model_to_extension.py
```

## Tests

```bash
node tests/test_extension.mjs
PYTHONPATH=src python3.11 -m unittest discover -s tests -v
PYTHONPATH=src python3.11 -m mpp_optimizer.webapp
```

La fixture visuelle est alors disponible sur
`http://127.0.0.1:8765/mpp-fixture.html`.
