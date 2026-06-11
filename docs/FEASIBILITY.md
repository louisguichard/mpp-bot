# Etude de faisabilite

## MPP

Le site web utilise `https://api.mpp.football`. Le bundle expose notamment :

- `GET /championships-current-matches`
- `GET /championship-match/{matchId}`
- `GET /user-match-forecasts/{entityId}`
- `PATCH /user-match-forecasts/entity/{entityId}/match/{matchId}`

Un match contient les quotations MPP `home`, `draw`, `away` et les proportions
communautaires `stats.bets`. Un bon resultat rapporte la quotation choisie. Un
score exact ajoute un bonus dependant de sa rarete communautaire.

## Sources implementees

### API-Football

- offre gratuite limitee a 100 appels par jour ;
- nombreux bookmakers et marches, dont score exact selon disponibilite ;
- cotes pre-match annoncees comme mises a jour toutes les quelques heures.
- le plan gratuit teste ne donne pas acces a la saison Coupe du monde 2026.

### odds-api.io

- nombreux bookmakers et marches ;
- horodatage par marche et endpoints de mises a jour incrementales ;
- la cle testee expose Bet365 et Winamax FR ainsi que le marche Correct Score ;
- candidat naturel si la fraicheur observee est bonne.

### Polymarket

- donnees publiques sans cle API ;
- authentification necessaire uniquement pour trader ;
- Coupe du monde 2026 deja couverte match par match ;
- trois marches moneyline permettent de reconstruire le 1N2 ;
- carnet d'ordres, spread, liquidite et volume disponibles ;
- pas de marche score exact observe.

Polymarket est donc un excellent signal temps reel pour `P(issue)`, mais ne
remplace pas une source de score exact pour `P(score exact)`.

## Strategie

1. Recuperer les matchs, quotations et choix communautaires depuis MPP.
2. Utiliser le marche score exact d'API-Football ou odds-api.io s'il existe.
3. Agreger le 1N2 bookmaker et Polymarket apres retrait de la marge.
4. Utiliser Poisson uniquement lorsque le score exact manque.
5. Calculer :

   `EV = P(issue) * quotation MPP + P(score exact) * bonus de rarete estime`

6. Afficher le meilleur score directement sur MPP via l'extension Chrome.

## Rarete

Paliers officiels Coupe du monde 2026 :

- exact ordinaire, plus de 30 % : `+20` ;
- rare, 20 a 30 % : `+30` ;
- tres rare, 5 a 20 % : `+50` ;
- mega rare, 0,5 a 5 % : `+70` ;
- ultra rare, moins de 0,5 % : `+100`.

La part est calculee parmi les joueurs ayant choisi la bonne issue, et non
parmi tous les joueurs. Le serveur MPP calcule `points.extra` et
`points.rarityLevel`.

## Extension

L'extension Chrome est faisable et constitue l'interface quotidienne :

- elle detecte les cartes de match MPP ;
- elle appelle le service local ;
- elle injecte meilleur score, esperance et explication ;
- la saisie automatique restera optionnelle et explicitement declenchee.

Le tableau de comparaison sert a choisir et surveiller le fournisseur. Il ne
remplace pas l'extension.

## Association des matchs

Les fournisseurs n'utilisent pas d'identifiant partage. Le rapprochement
utilise donc l'horaire et les deux equipes apres normalisation multilingue.
Les correspondances ambigues sont rejetees et devront etre confirmees
manuellement. Une fois valides, les liens pourront etre mis en cache pour toute
la Coupe du monde.

Un test reel a associe les 20 premiers matchs odds-api.io aux 20 matchs
Polymarket correspondants avec 100 % de confiance et aucun decalage horaire.
