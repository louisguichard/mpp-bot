# Rapport de recherche : modèle de rareté MPP

Date de l'étude : 11 juin 2026

## Résumé exécutif

Le bonus de rareté MPP est prédit à partir du score candidat, de la quotation
MPP de son issue et de la proportion de joueurs ayant choisi cette issue.
La cible n'est pas une part de joueurs reconstruite approximativement : c'est
le niveau de rareté réellement attribué par MPP sur les matchs historiques.

Le corpus final contient **741 matchs labellisés**. La Ligue 1 2024-2025 a bien
pu être reconstruite : 306 matchs ont été trouvés, dont 255 avec un niveau de
rareté exploitable. L'Euro 2024 et la CAN 2025 apportent 101 labels
internationaux particulièrement importants pour le Mondial.

La formule de distance initiale a été challengée sur **2 688 configurations**.
Le modèle déployé reste un kNN simple, mais sa géométrie change :

- représentation du score par `(buts totaux, écart de buts)` ;
- distance euclidienne ;
- poids dominant donné à la part MPP ayant choisi l'issue ;
- 7 voisins ;
- votes uniformes parmi les voisins, avec poids `1,5` pour les matchs
  internationaux.

Sur l'Euro 2024, gardé totalement hors sélection et hors entraînement, l'erreur
absolue moyenne du bonus attendu passe de **5,01 à 4,62 points** et l'exactitude
du palier de rareté passe de **77,6 % à 79,6 %**. L'amélioration est cohérente
sur la CAN tenue hors entraînement, mais les intervalles bootstrap restent
larges : le nouveau modèle est meilleur en tendance, pas démontré supérieur
avec une certitude statistique forte.

## Règle et variable cible

Pour un joueur ayant trouvé la bonne issue, MPP attribue un bonus selon la part
des joueurs de cette bonne issue ayant saisi le même score exact :

| Part du score dans la bonne issue | Niveau | Bonus |
|---|---:|---:|
| plus de 30 % | 1 | +20 |
| 20 à 30 % | 2 | +30 |
| 5 à 20 % | 3 | +50 |
| 0,5 à 5 % | 4 | +70 |
| moins de 0,5 % | 5 | +100 |

La cible apprise est le niveau officiel `1..5`, extrait des points réellement
attribués. L'espérance utilise ensuite la moyenne pondérée des bonus
`20, 30, 50, 70, 100`, plutôt que de considérer le niveau modal comme certain.

Source de la règle actuelle :
[règles officielles MPP Mondial 2026](https://ligue1.com/fr/articles/l1_article_5224-mpp-mondial-tout-savoir-sur-les-regles-26).

## Données

### Corpus d'entraînement

| Compétition | Saison API | Matchs trouvés | Labels utilisables |
|---|---:|---:|---:|
| Ligue 1 | 2024 | 306 | 255 |
| Ligue 1 | 2025 | 307 | 241 |
| Ligue des champions | 2025 | 189 | 144 |
| Euro 2024 | 2023 | 51 | 49 |
| CAN 2025 | 2025 | 52 | 52 |
| **Total labellisé** | | | **741** |

Les 72 matchs MPP actuels du Mondial 2026 sont disponibles, mais n'ont
évidemment encore aucun résultat ni bonus réel. Ils ne participent pas à
l'entraînement.

Le Mondial 2022 n'a pas pu être récupéré : l'archive MPP annonce zéro joueur et
les historiques renvoient des erreurs serveur. L'Euro 2024 et la CAN 2025
emploient la même échelle de bonus observée que le Mondial 2026.

### Distribution de la cible

| Dataset | +20 | +30 | +50 | +70 | +100 |
|---|---:|---:|---:|---:|---:|
| Ligue 1 2024-2025 | 89 | 47 | 76 | 39 | 4 |
| Ligue 1 2025-2026 | 83 | 36 | 95 | 23 | 4 |
| Ligue des champions 2025-2026 | 38 | 20 | 53 | 30 | 3 |
| Euro 2024 | 24 | 1 | 16 | 8 | 0 |
| CAN 2025 | 15 | 6 | 23 | 8 | 0 |

La classe `+100` est extrêmement rare et absente des deux datasets
internationaux. Toute estimation `+100` doit donc être considérée très
incertaine.

### Construction d'une observation

Une ligne d'apprentissage correspond au score qui s'est réellement produit :

- `kind` : nul ou victoire ;
- score miroir-fusionné : les victoires équipe 1 et équipe 2 sont traitées de
  manière symétrique ;
- quotation MPP de la bonne issue ;
- part MPP des joueurs ayant choisi la bonne issue ;
- indicateur de compétition internationale ;
- niveau de rareté réellement attribué.

À l'inférence, chaque score possible est transformé de la même manière et son
bonus attendu est prédit. Le score exact sportif reste probabilisé par le
Poisson calibré sur Polymarket.

### Collecte et limites

Les historiques publics exposent environ 100 pronostics par match. Aucun
identifiant joueur n'est conservé : les données sont agrégées immédiatement.
Cet échantillon n'est pas la communauté MPP complète, mais le bonus officiel
constitue une étiquette fiable.

Risques de données :

- la population MPP du Mondial peut différer de celle de la Ligue 1 ;
- seulement 101 labels internationaux sont disponibles ;
- `stats.bets` historique représente la répartition finale, très proche mais
  pas nécessairement identique à celle observée exactement à T-15 ;
- certains matchs n'exposent pas de niveau de rareté et sont exclus ;
- dans les archives publiques, un label n'est observable que si au moins un
  joueur de l'échantillon a trouvé le score exact ;
- les bonus extrêmes sont très peu représentés.

## Formule initiale et pourquoi elle devait être challengée

Le premier modèle utilisait :

```text
d = |Δ buts vainqueur|
  + |Δ buts perdant|
  + |Δ quotation| / 50
  + 3 × |Δ part MPP|
  + 1 si le score exact diffère
```

Cette formule était une initialisation d'ingénierie, pas un résultat
statistique. Son échelle implicite disait approximativement :

- un but d'écart de score ;
- 50 points de quotation ;
- 33 points de pourcentage de part MPP ;

ont une importance comparable. Le `+1` favorisait fortement le même score.
Sept voisins étaient ensuite pondérés par l'inverse de cette distance.

Cette construction avait l'avantage d'être lisible et raisonnable, mais les
coefficients et la métrique Manhattan étaient arbitraires. Elle devait donc
être traitée comme une baseline.

## Protocole expérimental

### Séparation honnête de l'Euro

L'Euro 2024 est le dataset le plus proche du Mondial. Aucun de ses 49 labels
n'a été utilisé pour sélectionner la distance, `k`, les poids ou la puissance
de vote. Il est évalué une seule fois comme test final principal.

La sélection hors Euro combine :

1. une validation croisée à 5 plis, équilibrée entre les quatre autres
   datasets ;
2. une validation CAN entièrement hors entraînement, avec l'Euro également
   exclu.

Ce protocole pénalise les modèles qui fonctionnent seulement sur la Ligue 1 et
teste un transfert international avant d'ouvrir l'Euro.

### Espace recherché

La recherche couvre 768 géométries de base, puis 1 920 variantes finalistes :

- Manhattan ou euclidienne ;
- score `(vainqueur, perdant)` ou `(total, marge)` ;
- pénalité d'identité `0, 0,5, 1, 2` ;
- poids buts `0,5, 1, 2` ;
- poids quotation `0, 0,5, 1, 2` ;
- poids part MPP `0, 1, 3, 5` ;
- `k = 3, 5, 7, 9, 11, 15, 21, 31` ;
- poids international `1, 1,25, 1,5, 2, 3` ;
- puissance de pondération par distance `0, 0,5, 1, 2`.

Les vingt meilleures configurations hors Euro sont toutes euclidiennes,
utilisent un poids de part MPP égal à `5`, `k=7` et des votes uniformes
(`distance_power=0`). Ce sont les conclusions les plus robustes de la grille.

## Modèle déployé

Pour un score candidat et une observation historique :

```text
s = (buts totaux, écart de buts)

d = sqrt(
      (0,5 × Δ buts totaux)²
    + (0,5 × Δ écart de buts)²
    + (0,5 × Δ quotation / 50)²
    + (5,0 × Δ part MPP)²
    )
    + 0,5 si le score relatif diffère
```

Seuls les matchs du même type, nul ou victoire, sont comparés. Les 7 plus
proches sont retenus. Chaque voisin vote uniformément ; un précédent Euro/CAN
reçoit un poids `1,5`, contre `1` pour les autres compétitions.

Le meilleur score de grille donnait un poids international `3`. Il n'est pas
déployé : le gain par rapport à `1,5` est négligeable, tandis que `1,5` réduit
le risque de surapprendre les 52 matchs de CAN. C'est une règle de
shrinkage conservatrice sur un plateau de performance.

Le niveau affiché est le mode pondéré. Le bonus utilisé dans l'espérance est :

```text
E[bonus | voisins] = somme(poids voisin × bonus observé) / somme(poids voisin)
```

## Résultats

### Comparaison principale

| Évaluation | Modèle initial | Modèle déployé |
|---|---:|---:|
| Euro hors entraînement : exactitude palier | 77,55 % | **79,59 %** |
| Euro hors entraînement : erreur bonus | 5,01 | **4,62** |
| CAN hors entraînement et Euro exclu : exactitude | 73,08 % | **75,00 %** |
| CAN hors entraînement et Euro exclu : erreur bonus | 7,11 | **6,62** |
| Validation croisée globale : exactitude | 68,42 % | **69,23 %** |
| Validation croisée globale : erreur bonus | 6,80 | **6,77** |

Le gain global est faible, mais le gain de transfert international est
cohérent et obtenu sans utiliser les labels Euro pour la sélection.

### Incertitude bootstrap appariée

Sur l'Euro, l'amélioration moyenne du bonus est proche de `0,4` point par
match. L'intervalle bootstrap à 95 % traverse zéro ; la probabilité bootstrap
que le nouveau modèle soit meilleur est d'environ 87 %. La CAN donne une
conclusion similaire.

Interprétation : le choix est raisonnable et validé dans la bonne direction,
mais il ne faut pas présenter le petit gain comme une preuve définitive. Le
vrai test sera le Mondial 2026.

### Baselines alternatives

Une régression ridge sur 741 labels, avec score, type d'issue, total, marge,
quotation, part MPP et interactions, obtient seulement :

- 47,8 % d'exactitude de palier ;
- 11,12 points d'erreur moyenne sur le bonus attendu.

Le phénomène est discontinu, ordinal et très lié à des conventions humaines
locales comme `1-0`, `1-1` ou `2-1`. Le kNN reproduit mieux ces voisinages
qu'une régression linéaire.

## Risque de surapprentissage

Le risque existe pour trois raisons :

1. 2 688 configurations ont été comparées ;
2. seulement 101 labels internationaux existent ;
3. la CAN influence directement la sélection hors Euro.

Les garde-fous sont :

- Euro totalement scellé pendant la sélection ;
- comparaison à une baseline simple ;
- choix conservateur du poids international `1,5` au lieu du maximum `3` ;
- maintien d'un modèle kNN court et interprétable ;
- suivi de l'erreur sur chaque compétition séparément ;
- utilisation du bonus attendu, moins instable que le seul palier modal.

## Améliorations recommandées

### Priorité 1 : collecter le Mondial en rolling origin

Après chaque match terminé :

1. importer le bonus réel et la scoresheet ;
2. évaluer le modèle pré-tournoi sans réentraîner sur ce match ;
3. seulement ensuite ajouter le match au corpus ;
4. comparer un modèle avec et sans surpondération Mondial ;
5. ne déployer un challenger que s'il améliore plusieurs fenêtres successives.

Après 15 matchs, les données seront utiles pour détecter un biais de population,
mais trop faibles pour remplacer le corpus historique.

### Priorité 2 : enregistrer les covariables exactement à T-15

Le bot doit archiver pour chaque décision :

- quotations MPP ;
- `stats.bets` ;
- probabilités Polymarket ;
- score recommandé et bonus attendu ;
- heure exacte de calcul.

On pourra alors mesurer le décalage entre covariables historiques finales et
covariables réellement disponibles au moment du pari.

### Priorité 3 : calibrer l'incertitude

Le vote kNN donne une pseudo-distribution des niveaux. Une calibration
out-of-fold, par exemple isotonic/Dirichlet, pourrait améliorer le bonus
attendu même sans améliorer le niveau modal. Elle doit être évaluée par
log-loss, Brier score et erreur du bonus attendu.

### Priorité 4 : modèle ordinal hiérarchique en challenger

Un modèle bayésien ordinal avec pooling partiel par :

- archetype de score ;
- compétition ;
- type nul/victoire ;
- tranche de quotation et part MPP ;

serait statistiquement plus propre pour les classes rares. Il ne doit remplacer
le kNN que s'il gagne sur l'Euro, la CAN et le rolling Mondial.

### Priorité 5 : politique de décision selon le classement

Le modèle actuel maximise l'espérance de points. Pour maximiser la probabilité
de gagner un classement, il faudra simuler la distribution totale des points
restants et proposer des modes prudent, espérance et remontée.

## Conclusion

Le modèle de rareté est désormais suffisamment performant pour contribuer
utilement à l'espérance MPP, à condition de conserver son incertitude. Il n'est
pas suffisamment précis pour traiter un bonus affiché comme certain.

Le gros gain futur ne viendra probablement plus d'une nouvelle distance
arbitraire, mais de trois éléments : vrais labels Mondial, snapshots T-15 et
calibration probabiliste du bonus attendu.

## Artefacts reproductibles

- `data/mpp_history.sqlite3` : corpus agrégé ;
- `docs/RARITY_KNN_SEARCH.json` : recherche complète ;
- `docs/RARITY_MODEL_SELECTION_ANALYSIS.json` : bootstrap final ;
- `docs/RARITY_REGRESSION_ANALYSIS.json` : baseline ridge ;
- `scripts/search_rarity_knn.py` : grille de modèles ;
- `scripts/analyze_rarity_selection.py` : validation finale ;
- `scripts/build_supervised_rarity_model.py` : construction du modèle déployé.
