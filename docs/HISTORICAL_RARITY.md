# Historique du bonus de rareté MPP

> Mise à jour du 11 juin 2026 : le corpus atteint 741 labels après ajout de la
> Ligue 1 2024-2025, de l'Euro 2024 et de la CAN 2025. Voir
> `RARITY_MODEL_RESEARCH_REPORT.md` pour le bilan final.

## Découverte principale

L'endpoint utilisé par une scoresheet MPP est :

`GET /user-match-forecasts/contest/general/match/{matchId}`

Il retourne le score saisi et les points de chaque joueur du concours général.
Le collecteur ne conserve aucun identifiant de joueur : il agrège
immédiatement les données dans `data/mpp_history.sqlite3`.

Les premières observations sont cohérentes avec la règle officielle : MPP
calcule la rareté du score exact parmi les joueurs ayant choisi la bonne issue,
et non parmi tous les joueurs.

## Corpus massif du 10 juin 2026

Une collecte authentifiée et cadencée a parcouru tous les calendriers
disponibles localement :

- 599 matchs MPP ;
- 49 820 pronostics joueurs agrégés ;
- 6 413 couples match-score observés ;
- 385 matchs avec un bonus de rareté réel identifiable ;
- aucune erreur API pendant la collecte.

| Niveau | Bonus | Matchs |
|---:|---:|---:|
| 1 | `+20` | 121 |
| 2 | `+30` | 56 |
| 3 | `+50` | 148 |
| 4 | `+70` | 53 |
| 5 | `+100` | 7 |

La part du score exact dans l'échantillon visible ne reproduit le bon palier
que dans 60,3 % des matchs. Cela confirme qu'il faut utiliser le bonus réel
comme étiquette d'apprentissage et non considérer l'échantillon comme la
population complète.

### Match `mpp_championship_match_2568730`

- résultat : `0-0` ;
- 101 pronostics au total ;
- 37 joueurs avaient choisi le nul ;
- 4 avaient choisi exactement `0-0` ;
- part parmi tous les joueurs : `4 / 101 = 3,96 %` ;
- part parmi les joueurs ayant choisi le nul : `4 / 37 = 10,81 %` ;
- bonus réellement attribué : niveau 3, `+50`.

Une part de `3,96 %` aurait donné `+70`. La part conditionnelle de `10,81 %`
donne bien le `+50` observé.

La distribution des nuls était très concentrée :

| Score | Joueurs | Part parmi les nuls |
|---|---:|---:|
| `1-1` | 27 | 72,97 % |
| `2-2` | 6 | 16,22 % |
| `0-0` | 4 | 10,81 % |

### Match `mpp_championship_match_2629032`

- résultat : `1-1` ;
- 83 pronostics au total ;
- 4 joueurs avaient choisi le nul ;
- 3 avaient choisi exactement `1-1` ;
- part parmi tous les joueurs : `3 / 83 = 3,61 %` ;
- part parmi les joueurs ayant choisi le nul : `3 / 4 = 75 %` ;
- bonus réellement attribué : niveau 1, `+20`.

Le second match est encore cohérent avec le dénominateur conditionnel :
`3,61 %` aurait donné `+70`, alors que `75 %` donne le `+20` observé.

## Limite importante : la scoresheet est un échantillon

La scoresheet générale expose environ 100 pronostics, alors que l'endpoint MPP
`general-standings/users-quantity` indiquait plus de 200 000 utilisateurs.
La liste visible n'est donc pas la population complète, et ressemble à
l'échantillon de joueurs affiché par le classement.

Conséquences :

- `points.extra` et `points.rarityLevel` donnent le vrai bonus attribué ;
- la règle et son dénominateur sont connus officiellement ;
- la part précise calculée dans l'échantillon n'est pas nécessairement la part
  utilisée par MPP ;
- la distribution complète des scores visible dans la scoresheet est utile
  comme signal comportemental, mais peut être biaisée.

Le futur modèle devra donc traiter le bonus réel comme une étiquette par
intervalle : par exemple `+50` signifie que la vraie part communautaire du
score se situe entre 5 % et 20 %. Il ne faudra pas apprendre naïvement à
reproduire la part exacte de l'échantillon.

## Données collectées

Pour chaque match et concours :

- résultat et issue réels ;
- nombre total de pronostics ;
- nombre de pronostics ayant la bonne issue ;
- nombre de scores exacts ;
- part du score exact parmi tous les joueurs et parmi la bonne issue ;
- niveau de rareté et bonus réellement attribués ;
- distribution complète des scores, séparée par issue.

Lorsque la fiche du match est disponible, la base ajoute :

- date, championnat et journée ;
- identifiants des clubs ;
- quotations MPP ;
- parts communautaires MPP pour domicile, nul et extérieur.

## Utilisation

```bash
# Import sans jeton des pages déjà consultées dans Chrome
PYTHONPATH=src python3.11 scripts/scrape_mpp_history.py --import-chrome-cache

# Import direct d'un match avec un jeton temporaire
MPP_TOKEN='...' PYTHONPATH=src python3.11 scripts/scrape_mpp_history.py \
  --match-id mpp_championship_match_2568730

# Parcours de tout un calendrier MPP
MPP_TOKEN='...' PYTHONPATH=src python3.11 scripts/scrape_mpp_history.py --calendar 1

# Rapport reproductible
PYTHONPATH=src python3.11 scripts/analyze_mpp_history.py

# Quotation MPP vers distribution empirique des scores joueurs
PYTHONPATH=src python3.11 scripts/build_mpp_score_distribution_model.py
```

Le rapport généré est `docs/HISTORICAL_RARITY_ANALYSIS.json`.

## Ce que le corpus permettra de modéliser

La variable à prédire n'est pas seulement la probabilité sportive d'un score.
Il faut prédire :

`P(un joueur MPP saisit ce score | il a choisi cette issue, profil du match)`

Les variables explicatives naturelles seront notamment :

- issue domicile, nul ou extérieur ;
- force relative suggérée par les quotations MPP ;
- part communautaire de chaque issue ;
- score simple ou symétrique (`1-0`, `1-1`, `2-1`) ;
- nombre total de buts ;
- écart de buts ;
- favori ou outsider.

Le corpus permet désormais d'entraîner un modèle ordinal supervisé par le
niveau de rareté réel, éventuellement complété par un modèle multinomial sur
les scores de l'échantillon.

## Quotation MPP vers distribution des scores

Le script `scripts/build_mpp_score_distribution_model.py` construit :

`issue + tranche de quotation MPP -> distribution des scores saisis`

Évaluation hors échantillon sur 90 matchs historiques :

| Modèle | Cross-entropy | Bon score joueur numéro 1 |
|---|---:|---:|
| issue seule | 1,709 | 59,1 % |
| issue + quotation MPP | 1,615 | 62,9 % |
| issue + part communautaire MPP | 1,609 | 61,7 % |

La quotation apporte donc une amélioration réelle. La part communautaire est
légèrement meilleure pour prédire toute la distribution, tandis que la
quotation est meilleure pour identifier le score le plus choisi.

Exemples observés :

- domicile coté `40-60` : `2-0` 29,0 %, `1-0` 20,3 %, `2-1` 17,4 % ;
- domicile coté `120-150` : `1-0` 44,1 %, `2-1` 40,3 % ;
- extérieur coté `40-60` : `0-2` 24,9 %, `0-3` 17,8 %, `1-3` 16,4 % ;
- extérieur coté `120-150` : `1-2` 41,3 %, `0-1` 32,8 % ;
- nul coté `100-120` : `1-1` 62,0 %, `0-0` 18,8 %, `2-2` 18,6 %.

Le modèle généré est `data/mpp_score_distribution_model.json`. L'analyse
reproductible est `docs/MPP_SCORE_DISTRIBUTION_ANALYSIS.json`.

Le détail exhaustif de chaque score, avec pondération par joueur, pondération
par match, détail par compétition et intervalle de variabilité à 95 %, est
disponible dans :

- `docs/MPP_SCORE_BUCKETS_COMPLETE.md` ;
- `docs/MPP_SCORE_BUCKETS_COMPLETE.csv`.

## Modèle terrain neutre pour la Coupe du monde

Les positions équipe 1 et équipe 2 ne représentent pas un avantage de terrain
au Mondial. Le modèle neutre fusionne donc les scores miroirs :

- victoire équipe 1 `2-1` ;
- victoire équipe 2 `1-2` ;
- score relatif commun : `2-1`.

Chaque couple match-issue reçoit le même poids, puis les observations domicile
et extérieur historiques sont moyennées. Pour la tranche `40-60`, le modèle
neutre repose sur 107 observations match-issue et donne :

| Score relatif du vainqueur | Part moyenne |
|---|---:|
| `2-0` | 27,5 % |
| `1-0` | 19,1 % |
| `2-1` | 17,6 % |
| `3-1` | 13,9 % |
| `3-0` | 13,2 % |

Le fichier généré est `data/mpp_neutral_score_distribution_model.json`.

Après 15 matchs du Mondial, on disposera vraisemblablement d'environ 1 500
pronostics visibles, mais seulement de 15 étiquettes de bonus réel. Une
simulation par sous-échantillonnage historique montre que 15 matchs donnent
typiquement seulement 3 à 8 observations match-issue par tranche centrale et
0 à 3 dans les tranches extrêmes. Cela suffit pour détecter un biais global
propre au Mondial, mais pas pour remplacer séparément chaque distribution.

La mise à jour devra donc être hiérarchique :

1. conserver le modèle neutre historique comme a priori ;
2. mesurer les écarts globaux observés au Mondial ;
3. mélanger chaque tranche avec les données Mondial selon son effectif ;
4. augmenter progressivement le poids du Mondial après chaque journée.

### Données avant match

Un test authentifié sur plusieurs matchs Mondial à venir confirme que
`/user-match-forecasts/contest/general/match/{matchId}` renvoie avant le coup
d'envoi un seul enregistrement : le pronostic du joueur connecté, avec des
points à zéro. Aucun endpoint agrégé de scores exacts n'a été trouvé.

MPP expose néanmoins `stats.bets`, qui donne les parts globales des trois issues
équipe 1, nul et équipe 2. Cette donnée peut être utilisée en complément, mais
elle ne permet pas de connaître la répartition entre `1-0`, `2-0`, `2-1`, etc.

## Limites d'accès

Les endpoints historiques nécessitent l'authentification MPP. Le mode cache
Chrome fonctionne sans stocker de jeton, mais ne récupère que les scoresheets
déjà consultées. Le mode calendrier permet une collecte exhaustive avec un
jeton temporaire fourni via `MPP_TOKEN`; le collecteur applique un délai entre
les requêtes et ne réalise aucune écriture sur MPP.
