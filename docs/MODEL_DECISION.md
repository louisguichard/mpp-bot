# Décision modèle : rareté et probabilités de score

> Mise à jour du 11 juin 2026 : le corpus atteint désormais 741 labels et le
> modèle final a été re-sélectionné avec l'Euro entièrement hors entraînement.
> Le rapport de référence est `RARITY_MODEL_RESEARCH_REPORT.md`; les chiffres
> ci-dessous documentent les étapes antérieures de l'étude.

## Rareté MPP

Validation croisée sur 434 matchs pour lesquels le niveau de rareté officiel est connu.
Le match évalué est toujours exclu de la construction de sa distribution historique.

| Méthode | Niveau exact | Erreur moyenne | À ±1 niveau |
|---|---:|---:|---:|
| Ancienne heuristique Poisson | 27,3 % | 1,239 | 60,3 % |
| Mélange historique 85 % / heuristique 15 % | 56,6 % | 0,543 | 89,4 % |
| Historique MPP seul | **61,0 %** | **0,473** | 92,0 % |
| Historique calibré | 60,5 % | **0,473** | **92,2 %** |

Décision : utiliser l'historique MPP seul lorsqu'un score est présent dans la base.
Conserver l'heuristique comme repli pour les scores absents. La calibration testée
n'améliore pas suffisamment le modèle pour justifier sa complexité.

Une seconde passe utilise maintenant les 434 niveaux de bonus réellement attribués
comme étiquettes d'un modèle supervisé de voisins similaires :

| Modèle supervisé | Niveau exact | Erreur moyenne | À ±1 niveau |
|---|---:|---:|---:|
| 5 plis par match | **65,5 %** | **0,416** | **93,0 %** |
| Ligue des champions vers Ligue 1 | 65,6 % | 0,440 | 90,5 % |
| Ligue 1 vers Ligue des champions | 59,0 % | 0,486 | 92,4 % |

Après ajout de l'Euro 2024, le réglage déployé atteint entre 64,5 % et 69,1 % de
niveau exact selon le découpage de validation, avec 7,43 à 7,74 points d'erreur sur
le bonus attendu. La validation imbriquée atteint 65,9 % et 7,48 points. Le modèle
simple par tranches reste à 62,9 %, tandis qu'une régression ridge testée sur les
mêmes variables plafonne à 50,7 % et 10,93 points d'erreur. Sur l'Euro laissé
entièrement hors entraînement, le réglage déployé atteint 71,4 % et 5,90 points.
Aucun surapprentissage mesurable n'apparaît pour l'instant, mais les baselines simples
restent suivies comme garde-fou.

Décision mise à jour : utiliser le modèle supervisé lorsque `stats.bets` est
disponible, puis le modèle historique et enfin l'heuristique comme replis.
L'espérance utilise le bonus attendu pondéré par les voisins, pas seulement le
niveau modal.

Limite principale : les scoresheets exposent environ 100 joueurs par match, pas toute
la communauté. Une précision exacte de 61 % est utile mais ne permet pas de considérer
le niveau de bonus comme certain.

## Polymarket + Poisson contre cotes de score exact

Backtest sur les 72 matchs de poule du Mondial :

- MPP, Polymarket et Bet365 reliés : **72/72**
- Vérité supposée : probabilités `Correct Score` Bet365, dévigées par méthode puissance
- Même recommandation : **83,3 %** des matchs
- EV totale de la recommandation Polymarket + Poisson : **2 769,66 points**
- EV totale de la recommandation avec cotes de score exact : **2 781,71 points**
- Avantage des cotes de score exact : **12,05 points**, soit **0,167 point par match**
  et **+0,44 %**

Décision : rester sur Polymarket seul pour le produit principal. Les cotes de score
exact sont légèrement meilleures sous leur propre hypothèse de vérité, mais le gain
est trop faible pour justifier la dépendance API et sa complexité dans le MVP.

Cette conclusion doit être réévaluée après le tournoi avec les scores réellement
observés. Le marché Bet365 est ici renormalisé sur les scores explicitement cotés.

## Améliorations testées et rejetées (11 juin 2026)

Deux raffinements classiques du modèle de Poisson ont été évalués sous la même
vérité Bet365 Correct Score que le backtest principal, sur les 72 matchs de
poule :

| Variante | KL moyen | EV réelle totale | Décision |
|---|---:|---:|---|
| Poisson indépendant, grille 4,0 (déployé) | 0,0559 | **2 762,9** | conservé |
| Dixon-Coles `rho = -0,05` | **0,0503** | 2 745,6 | rejeté |
| Dixon-Coles `rho = -0,10` | 0,0575 | 2 735,8 | rejeté |
| Grille de calibration élargie à 6,0 | 0,0578 | 2 759,0 | rejeté |

La correction Dixon-Coles rapproche légèrement la forme globale de la
distribution (KL à `rho = -0,05`) mais dégrade systématiquement l'EV réelle des
recommandations une fois le 1N2 recalibré : le marché calibré capture déjà
l'essentiel de la corrélation des scores faibles. Le paramètre `rho` reste
disponible dans `score_matrix` mais vaut `0` par défaut.

L'élargissement de la grille xG corrige une saturation théorique (3 matchs
saturent à 4,0) mais le seul match dont la recommandation change
(Allemagne - Curaçao, 6-1 au lieu de 5-0) est mieux noté par le marché score
exact avec la grille d'origine : la borne agit comme une régularisation des
totaux de buts. Scripts : `scripts/validate_dixon_coles.py` et
`scripts/validate_xg_grid.py`.

Rapports détaillés :

- `FRANCE_RARITY_COMPARISON.md`
- `RARITY_MODEL_ACCURACY.json`
- `SCORE_RECOMMENDATION_BACKTEST.json`
- `SCORE_MODEL_ANALYSIS.json`
- `DIXON_COLES_VALIDATION.json`
- `XG_GRID_VALIDATION.json`
