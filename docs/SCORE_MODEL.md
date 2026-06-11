# Modele de score exact

## Regle MPP

Un bon resultat rapporte la quotation MPP. Un score exact ajoute un bonus
dependant de sa part parmi les joueurs ayant choisi la bonne issue :

| Part conditionnelle | Bonus |
|---|---:|
| plus de 30 % | +20 |
| 20 a 30 % | +30 |
| 5 a 20 % | +50 |
| 0,5 a 5 % | +70 |
| moins de 0,5 % | +100 |

Source : [regles officielles MPP Mondial 2026](https://ligue1.com/fr/articles/l1_article_5224-mpp-mondial-tout-savoir-sur-les-regles-26).

Pour un score `s` donnant l'issue `i` :

`EV(s) = P(i) x quotation(i) + P(s) x bonus(part communautaire estimee de s | i)`

## Modele autonome de l'extension

L'extension calibre deux lois de Poisson independantes sur les probabilites
1N2 Polymarket. Elle estime ensuite la concentration communautaire par :

`poids(s | i) = P(s | i)^alpha x biais de simplicite(s)`

`part(s | i) = poids(s | i) / somme des poids de l'issue i`

avec `alpha = 2`. Le biais de simplicite favorise les scores bas et les
victoires d'un but. Il represente notamment le fait que les joueurs choisissant
un enorme outsider vont souvent se concentrer sur `0-1`, meme si Poisson
repartit aussi la faible probabilite de surprise sur des scores plus ouverts.
Une sensibilite entre `1,5` et `2,5` permet de verifier si le score conseille
reste stable lorsque la communaute se concentre plus ou moins sur les scores
evidents.

Cette part est une estimation. Le collecteur historique récupère désormais sur
les matchs terminés les distributions de scores ainsi que les champs MPP
`points.extra` et `points.rarityLevel`. Les premières observations confirment
le dénominateur conditionnel et montrent une forte concentration sur les scores
simples. Voir `docs/HISTORICAL_RARITY.md`.

Concretement, le poids communautaire estime est :

`P(score | issue)^2 x exp(-0,55 x nombre total de buts) x 1,25 si victoire d'un but`

Les poids sont ensuite normalises separement pour victoire domicile, nul et
victoire exterieure. La probabilite Poisson mesure ce qui peut arriver ; ce
poids mesure ce que les joueurs risquent d'ecrire. Les coefficients `2`,
`0,55` et `1,25` sont encore des hypotheses comportementales, pas des
parametres observes chez MPP.

## Poisson contre marche score exact

Nouvelle comparaison realisee le 10 juin 2026 sur les 72 matchs Coupe du monde
disposant d'un marche score exact Bet365 via odds-api.io :

- meme meilleur score dans 53 matchs sur 72, soit 73,6 % ;
- recouvrement moyen de 2,76 scores sur les trois premiers ;
- divergence Jensen-Shannon moyenne de 0,00748 apres retrait de marge par la
  methode de puissance.

Une correction Dixon-Coles des petits scores combinee a un leger ajustement du
nombre total de buts reduit la divergence hors echantillon a `0,00655`, soit
environ 12 % de mieux. Elle degrade cependant l'identification du meilleur
score de 73,6 % a 63,9 %, et le recouvrement du top 3 de 2,76 a 2,61. Elle
n'est donc pas appliquee a l'extension pour le moment.

La marge du marche score exact n'est pas uniforme : une normalisation
proportionnelle survalorise fortement les longues cotes. Le moteur utilise
desormais une methode de puissance lorsqu'il recoit des cotes score exact.

Poisson reste donc le meilleur repli gratuit pour classer les scores. Le marche
score exact apporte une information utile sur environ un quart des matchs et
doit rester une amelioration optionnelle lorsque odds-api.io est disponible.

Les mesures reproductibles sont generees par
`scripts/analyze_score_models.py` dans `docs/SCORE_MODEL_ANALYSIS.json`.

## Impact sur la decision

Sur 50 matchs MPP observes, avec `alpha = 2` :

- le bonus score exact changeait la meilleure issue sur 3 matchs ;
- il ajoutait environ 4,2 points d'esperance en moyenne ;
- il servait surtout a departager des esperances 1N2 proches.

A esperance 1N2 identique, l'issue probable a souvent un avantage grace a une
probabilite de score exact plus elevee. Mais le meilleur score n'est pas
toujours le plus probable : une probabilite legerement inferieure peut etre
compensee par un bonus de rarete superieur.
