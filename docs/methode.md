# La méthode en détail

Ce document explique comment le bot calcule ses pronostics, comment chaque
brique a été choisie, **tout ce qui a été essayé** — y compris ce qui n'a pas
marché — et les limites connues. Les rapports bruts et artefacts
reproductibles sont listés en fin de page.

## 1. Le problème

À MPP, pour chaque match, on pronostique un score exact. Les points gagnés :

- la **quotation** de l'issue (victoire 1, nul, victoire 2) si elle est
  correcte — fixée par MPP avant le match, entre ~40 et ~200 points ;
- un **bonus de rareté** si le score exact est trouvé, selon la part des
  joueurs ayant choisi ce score **parmi ceux qui ont la bonne issue** :

| Part du score dans la bonne issue | Niveau | Bonus |
|---|---:|---:|
| plus de 30 % | 1 | +20 |
| 20 à 30 % | 2 | +30 |
| 5 à 20 % | 3 | +50 |
| 0,5 à 5 % | 4 | +70 |
| moins de 0,5 % | 5 | +100 |

(Source : [règles officielles MPP Mondial 2026](https://ligue1.com/fr/articles/l1_article_5224-mpp-mondial-tout-savoir-sur-les-regles-26).)

Le score qui maximise l'espérance n'est donc presque jamais le plus probable :
il faut arbitrer entre probabilité du score, quotation de l'issue et rareté
du choix dans la communauté. D'où la formule optimisée pour chaque score
candidat `(h, a)` :

```text
E[points] = P(issue de h-a) × quotation(issue) + P(score h-a) × E[bonus | h-a]
```

## 2. P(issue) : pourquoi Polymarket

Trois sources de probabilités 1N2 ont été implémentées et comparées :
API-Football, odds-api.io (cotes bookmakers dont Bet365) et Polymarket.

**Polymarket a gagné** pour le produit principal :

- gratuit, sans clé API, sans quota ;
- très liquide sur la Coupe du monde (les 72 matchs de poule disponibles) ;
- les prix d'un marché de prédiction sont déjà des probabilités — on prend le
  point médian bid/ask de chaque issue et on normalise le total à 1 ;
- l'association MPP ↔ Polymarket a réussi **72/72** avec une confiance de
  100 % (alias multilingues, tolérance horaire, rejet des ambiguïtés).

Les cotes bookmakers restent utilisées pour la **validation** (voir § 6) : le
marché « score exact » de Bet365, dévigé, sert de vérité de référence dans
les backtests.

Le dévig des cotes 1N2 utilise la normalisation proportionnelle classique.
Pour les cotes de score exact, dont les marges se concentrent sur les
cotes longues, c'est la **méthode puissance** qui est utilisée (recherche
dichotomique de l'exposant qui ramène la somme des probabilités implicites
à 1).

## 3. P(score exact) : un Poisson calibré sur le marché

Les buts de chaque équipe sont modélisés par deux lois de Poisson
indépendantes. Les taux `(λ domicile, μ extérieur)` ne viennent pas de
statistiques d'équipes : ils sont **calibrés pour reproduire le 1N2 de
Polymarket**, par une recherche en grille à trois passes (pas 0,10 sur
[0,2 ; 4,0], puis raffinements à 0,02 et 0,005). La matrice des scores est
tronquée à 8 buts et renormalisée.

Ce choix concentre toute l'information dans le marché, qui agrège déjà
forme, compositions et contexte — et il est validé par backtest (§ 6).

## 4. E[bonus] : le modèle de rareté supervisé

C'est la partie la plus originale du projet. Le bonus dépend du comportement
de la communauté MPP, inconnu à l'avance. Deux approches naïves échouent :

- supposer que la foule joue proportionnellement aux probabilités → faux, la
  foule sur-joue les scores simples (1-0, 2-1) et sous-joue les scores hauts ;
- reconstruire la part exacte des joueurs → impossible à l'avance.

### Les données

Les feuilles de scores publiques de MPP exposent environ 100 pronostics par
match, ainsi que le bonus réellement attribué. Un collecteur a reconstruit un
corpus en agrégeant immédiatement ces données (aucun identifiant joueur
conservé) :

| Compétition | Labels utilisables |
|---|---:|
| Ligue 1 2024-2025 | 255 |
| Ligue 1 2025-2026 | 241 |
| Ligue des champions 2025-2026 | 144 |
| Euro 2024 | 49 |
| CAN 2025 | 52 |
| **Total** | **741** |

La cible apprise est le **niveau de rareté officiel** (1 à 5) réellement
attribué par MPP — pas une part reconstruite approximativement. Le Mondial
2022 n'a pas pu être récupéré (archives vides côté MPP).

### Le modèle

Un kNN supervisé : pour un score candidat, on cherche les 7 précédents
historiques les plus proches **du même type** (nul ou victoire), selon la
distance :

```text
s = (buts totaux, écart de buts)

d = sqrt(
      (0,5 × Δ buts totaux)²
    + (0,5 × Δ écart de buts)²
    + (0,5 × Δ quotation / 50)²
    + (5,0 × Δ part des joueurs sur l'issue)²
    )
    + 0,5 si le score relatif diffère
```

Chaque voisin vote pour son niveau de rareté (poids 1,5 pour les précédents
internationaux Euro/CAN). L'espérance utilise le **bonus attendu pondéré**
(moyenne des bonus votés), pas seulement le niveau majoritaire : c'est plus
stable et c'est ce qui compte pour une espérance.

La variable dominante est, de loin, la **part des joueurs ayant choisi
l'issue** (`stats.bets` de MPP) : un 1-0 quand 88 % de la communauté joue la
victoire est commun ; le même 1-0 quand 12 % la joue est rare.

### Le protocole de validation (l'important)

La distance ci-dessus est le résultat d'une recherche sur **2 688
configurations** (métrique, représentation du score, poids, k, pondérations).
Pour éviter de surapprendre :

- l'**Euro 2024 a été entièrement scellé** pendant toute la sélection : aucun
  de ses 49 labels n'a servi à choisir quoi que ce soit. Il n'a été ouvert
  qu'une fois, comme test final — c'est le dataset le plus proche du Mondial ;
- la sélection a combiné validation croisée à 5 plis et une validation CAN
  entièrement hors entraînement ;
- le poids international retenu (1,5) est volontairement plus conservateur
  que l'optimum de grille (3), pour ne pas surapprendre les 52 matchs de CAN.

Résultats sur l'Euro tenu hors de tout :

| Évaluation | Distance initiale | Modèle déployé |
|---|---:|---:|
| Exactitude du palier | 77,6 % | **79,6 %** |
| Erreur moyenne sur le bonus attendu | 5,01 pts | **4,62 pts** |

L'intervalle bootstrap à 95 % de l'amélioration traverse zéro (probabilité
~87 % que le nouveau modèle soit meilleur) : le gain est cohérent mais pas
statistiquement démontré. Il est présenté comme tel.

## 5. Ce qui a été essayé et rejeté

Chaque idée a été testée contre une référence mesurable avant d'être adoptée
ou écartée. La liste complète :

| Idée | Verdict | Pourquoi |
|---|---|---|
| Heuristique de foule (Poisson^α + biais buts) | ❌ remplacée | 27,3 % d'exactitude de palier — gardée en dernier repli de l'extension |
| Mélange historique 85 % / heuristique 15 % | ❌ | l'historique seul fait mieux (61,0 % contre 56,6 %) |
| Calibration de l'historique | ❌ | gain insuffisant pour la complexité ajoutée |
| Régression ridge (mêmes variables + interactions) | ❌ | 47,8 % d'exactitude contre 65,5 % au kNN : le phénomène est discontinu et local, une régression linéaire le lisse à tort |
| Distance Manhattan initiale (poids manuels) | ❌ remplacée | la recherche systématique a trouvé mieux : euclidienne sur (total, marge), poids 5 sur la part des joueurs |
| Cotes « score exact » Bet365 au lieu de Polymarket + Poisson | ❌ | +0,44 % d'espérance seulement (+0,167 pt/match sur 72 matchs) : pas de quoi justifier une dépendance API avec quotas |
| Correction de Dixon-Coles (corrélation des scores faibles) | ❌ | améliore légèrement la forme de la distribution (KL 0,050 contre 0,056 à ρ=−0,05) mais **dégrade l'EV réelle des décisions** pour tout ρ négatif : une fois le 1N2 recalibré sur le marché, la correction est déjà capturée. Le paramètre reste dans le code, désactivé |
| Grille de calibration xG élargie de 4,0 à 6,0 | ❌ | corrige une saturation théorique mais le seul pronostic modifié (un 6-1 au lieu d'un 5-0) est moins bien noté par le marché score exact : la borne agit comme une régularisation des totaux de buts |

Les deux dernières lignes illustrent la philosophie du projet : même les
raffinements « de manuel » sont backtestés avant adoption, et un modèle
simple bien calibré sur le marché s'avère difficile à battre.

## 6. Backtests de bout en bout

Le backtest principal traite les probabilités « Correct Score » de Bet365,
dévigées par méthode puissance, comme vérité, et compare les recommandations
complètes (base + rareté) sur les 72 matchs de poule :

- même recommandation que la méthode de référence : 83,3 % des matchs ;
- espérance totale Polymarket + Poisson : 2 769,7 points ;
- espérance totale avec les cotes score exact : 2 781,7 points ;
- écart : 0,167 point par match — négligeable.

Ces chiffres doivent être réévalués après le tournoi avec les scores réels.

## 7. Limites et biais connus

1. **Biais d'observabilité des labels** : dans les archives publiques
   (~100 joueurs), un bonus n'est observable que si au moins un joueur de
   l'échantillon a trouvé le score. Les vrais +100 (< 0,5 % des joueurs)
   disparaissent donc du corpus → le bonus attendu des scores exotiques est
   sous-estimé. Le biais est conservateur (le bot privilégie des scores plus
   standards), mais réel.
2. **Population** : la communauté MPP du Mondial peut se comporter autrement
   que celle de la Ligue 1 ; seulement 101 labels internationaux existent.
3. **Covariables** : le modèle est entraîné sur les parts de paris finales,
   mais utilisé avec les parts disponibles à T-15. L'écart est probablement
   faible (la majorité des pronostics sont posés des jours à l'avance) et les
   journaux du bot archivent les covariables exactes de chaque décision pour
   le mesurer après coup.
4. **Espérance ≠ classement** : maximiser l'espérance par match ne maximise
   pas la probabilité de gagner une ligue (la corrélation avec les choix de
   la foule compte). Un mode « remontée » reste à construire.

## 8. Pistes restantes

- **Rolling Mondial** : après chaque match terminé, évaluer le modèle
  pré-tournoi sur ce match avant de l'ajouter au corpus ;
- **calibration probabiliste** des votes kNN (isotonique/Dirichlet), évaluée
  par log-loss et erreur de bonus attendu ;
- **modèle ordinal bayésien hiérarchique** en challenger, à ne déployer que
  s'il gagne sur Euro, CAN et rolling Mondial à la fois ;
- **politique de décision selon le classement** (prudent / espérance /
  remontée) par simulation des points restants.

## 9. Rapports et artefacts

Tous les rapports bruts sont dans ce dossier :

- [RARITY_MODEL_RESEARCH_REPORT.md](RARITY_MODEL_RESEARCH_REPORT.md) — le
  rapport complet du modèle de rareté (corpus, recherche, validation) ;
- [MODEL_DECISION.md](MODEL_DECISION.md) — toutes les décisions de
  modélisation chiffrées, dont les améliorations testées et rejetées ;
- [HISTORICAL_RARITY.md](HISTORICAL_RARITY.md) et
  [SCORE_MODEL.md](SCORE_MODEL.md) — analyses intermédiaires ;
- `*.json` — résultats bruts de chaque expérience (recherche kNN, bootstrap,
  régression, backtest, Dixon-Coles, grille xG…).

Scripts reproductibles dans [scripts/](../scripts) : collecte
(`scrape_mpp_history.py`), construction du modèle
(`build_supervised_rarity_model.py`), recherche (`search_rarity_knn.py`),
validations (`validate_dixon_coles.py`, `validate_xg_grid.py`,
`backtest_score_recommendations.py`), etc. La base agrégée est
`data/mpp_history.sqlite3`.
