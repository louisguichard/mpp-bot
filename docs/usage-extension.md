# Mode extension Chrome

L'extension affiche les espérances de points directement sur le site MPP :
pour chaque match, l'issue recommandée, les meilleurs scores exacts et le
bonus de rareté attendu, dans un popover au-dessus de la page officielle.

C'est le mode « copilote » : vous gardez la main, l'extension conseille.
Elle n'écrit jamais rien.

## Installation

1. Ouvrir `chrome://extensions` ;
2. activer le **mode développeur** (en haut à droite) ;
3. cliquer sur **Charger l'extension non empaquetée** ;
4. sélectionner le dossier `extension/` de ce dépôt.

Aucun serveur local n'est nécessaire pour l'usage normal : l'extension est
autonome.

## Comment elle marche

- **Aucun jeton n'est stocké ni demandé.** Un script (`page-hook.js`) observe
  les réponses API que la page MPP authentifiée reçoit déjà, et en extrait les
  matchs, quotations et parts de paris.
- Le service worker lit **publiquement** les marchés 1N2 de Polymarket
  (aucune clé API), associe chaque match MPP au bon marché (alias
  multilingues, tolérance horaire, rejet des correspondances ambiguës), puis
  calcule les espérances avec exactement le même modèle que le bot :
  Poisson calibré + kNN de rareté supervisé.
- Le modèle de rareté est embarqué dans `extension/rarity-label-model.js`,
  généré automatiquement par `scripts/build_supervised_rarity_model.py` —
  c'est le même fichier de modèle que celui du bot, à l'octet près. Quand les
  parts de paris ne sont pas disponibles, l'extension se replie sur le modèle
  historique neutre, puis sur une heuristique comportementale.

## Ce que vous voyez

Pour chaque issue (1, N, 2) :

- l'espérance totale `base + bonus`, en points ;
- le meilleur score exact et sa probabilité ;
- le bonus attendu, avec un libellé mixte quand l'estimation se situe entre
  deux paliers (par exemple `+60 · très rare / méga rare`) ;
- un marqueur « contrarian » quand la recommandation va contre la majorité
  des joueurs.

Le popup de l'extension affiche le nombre de matchs détectés, les conseils
produits et un journal de diagnostic.

## Tester sans compte MPP

Une fixture reproduit la page MPP avec des données réelles enregistrées :

```bash
PYTHONPATH=src python3.11 -m mpp_optimizer.webapp
# puis ouvrir http://127.0.0.1:8765/mpp-fixture.html
```

Le test automatisé de bout en bout (association Polymarket réelle incluse) :

```bash
node tests/test_extension.mjs
```
