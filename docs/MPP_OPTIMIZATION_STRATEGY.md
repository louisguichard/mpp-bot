# Stratégie pour maximiser les points MPP

> Mise à jour du 11 juin 2026 : le modèle final et la stratégie de validation
> sont détaillés dans `RARITY_MODEL_RESEARCH_REPORT.md`. L'automatisation T-15
> est détaillée dans `usage-bot.md`.

## Ce qui est déjà amélioré

- La rareté est désormais prédite directement depuis 434 bonus réellement attribués
  par MPP, et non seulement depuis l'échantillon visible des scoresheets.
- Le modèle supervisé atteint 65,5 % de niveaux exacts contre 61,0 % pour le meilleur
  modèle précédent.
- L'erreur moyenne tombe de 0,473 à 0,416 niveau.
- L'espérance utilise le bonus attendu issu de plusieurs voisins similaires, plutôt
  qu'un bonus prédit considéré à tort comme certain.
- Le modèle fusionne les victoires équipe 1 et équipe 2 pour représenter un terrain
  neutre.

## Priorités classées par impact

### 1. Ajouter les matchs du Mondial après chaque journée

Les données les plus précieuses ne sont pas davantage de pronostics visibles, mais
les vrais niveaux de bonus attribués après chaque match. Après chaque journée :

1. visiter ou scraper les scoresheets terminées ;
2. importer les bonus réels ;
3. reconstruire le modèle supervisé ;
4. mesurer son erreur sur les matchs précédents.

Commande reproductible :

```bash
PYTHONPATH=src:scripts python3.11 scripts/refresh_rarity_models.py --import-cache
```

Quinze matchs du Mondial ne suffiront pas à remplacer le corpus historique, mais
permettront d'apprendre un éventuel biais propre au tournoi.

### 2. Exploiter prudemment les scores exacts Polymarket

Polymarket expose déjà un événement `Exact Score` pour chacun des 72 matchs de
poule, sans nouvelle API payante. Ils sont cependant encore peu liquides :

- seulement 17 marchés possèdent actuellement les 17 scores cotés ;
- spread médian actuel : environ 10,4 points de probabilité ;
- les meilleurs marchés proches du coup d'envoi ont des spreads de 1 à 5 points.

Le bon usage serait de mélanger ces probabilités avec Poisson uniquement lorsque
le marché devient suffisamment liquide et serré. Il ne faut pas remplacer Poisson
aveuglément par un marché encore vide.

### 3. Rafraîchir juste avant la clôture

Polymarket, les quotations MPP et `stats.bets` évoluent. La recommandation optimale
doit être recalculée peu avant chaque coup d'envoi, avec un indicateur signalant un
marché trop ancien ou trop peu liquide.

### 4. Optimiser l'objectif réel, pas seulement l'espérance

Maximiser les points moyens et maximiser la probabilité de gagner un classement ne
sont pas toujours identiques :

- en tête : privilégier les options probables et limiter la variance ;
- en retard : accepter davantage de variance et rechercher des gains élevés ;
- près de la fin : choisir en fonction de l'écart au leader et des matchs restants.

Il faudrait ajouter un mode `Espérance`, un mode `Prudent` et un mode `Remontée`.

### 5. Optimiser l'ensemble des matchs

Le choix idéal n'est pas forcément le meilleur pari match par match. Un optimiseur
de portefeuille pourrait répartir le risque entre favoris, nuls et surprises afin
d'éviter qu'un seul scénario footballistique fasse perdre toute une journée.

## Scraping à rechercher

Ordre de valeur :

1. scoresheets du Mondial terminées, car elles correspondent exactement au contexte ;
2. anciens matchs de compétitions internationales sur terrain neutre ;
3. ancien championnat MPP `19` identifié comme la CAN ;
4. davantage de saisons Ligue 1 / Ligue des champions.

Le corpus actuel contient déjà tout ce qui a été trouvé pour les calendriers courants
1 et 6. Les paramètres MPP révèlent également trois archives internationales :

- Mondial 2022 : championnat `8`, saison `2022` ;
- Euro 2024 : championnat `9`, saison `2023` ;
- CAN 2025 : championnat `19`, saison `2025`.

Elles sont désormais prises en charge par le scraper, avec deux voies : la route
globale des pronostics et la reconstruction anonymisée depuis les historiques publics
du classement. Elles demandent un jeton MPP valide placé dans `.env` sous
`MPP_TOKEN` :

```bash
PYTHONPATH=src:scripts python3.11 scripts/refresh_rarity_models.py \
  --international-archives

PYTHONPATH=src:scripts python3.11 scripts/scrape_mpp_history.py \
  --public-archive 9:2023 --delay 0.05
```

Au 11 juin 2026, l'Euro 2024 apporte 5 131 pronostics publics agrégés sur 51 matchs
et 49 niveaux de rareté officiels. L'échelle observée est identique à l'échelle
actuelle : niveaux 1 à 5 associés à +20, +30, +50, +70 et +100. Le classement et
l'historique du Mondial 2022 ont en revanche été purgés par MPP : l'API annonce zéro
joueur et renvoie une erreur serveur pour les historiques 2022.

## Risque de surapprentissage

Le modèle supervisé reste volontairement simple : sept voisins, cinq variables et
aucun réseau neuronal. Plusieurs validations le comparent aux modèles par tranches :

| Modèle | Niveau exact | Erreur moyenne | Erreur bonus attendu |
|---|---:|---:|---:|
| Score seul | 61,6 % | 0,512 | 10,27 pts |
| Score + tranches quotation/parts MPP | 61,0 % | 0,488 | 9,56 pts |
| Voisins déployés | 69,1 % | 0,378 | 7,43 pts |
| Voisins, validation imbriquée | 65,9 % | 0,408 | 7,48 pts |
| Régression ridge | 50,7 % | 0,576 | 10,93 pts |

La validation imbriquée choisit les paramètres sans voir le pli évalué. Elle ne
montre pas de surapprentissage mesurable, mais le corpus de 434 labels reste petit.

## Lecture du bonus attendu dans l'extension

Le niveau MPP le plus probable reste utilisé pour afficher le gain possible, tandis
que l'espérance utilise la moyenne pondérée des bonus voisins. Le front affiche :

| Bonus attendu | Libellé |
|---:|---|
| jusqu'à `+25` | exact |
| `+26` à `+35` | rare |
| `+36` à `+44` | rare / très rare |
| `+45` à `+55` | très rare |
| `+56` à `+64` | très rare / méga rare |
| `+65` à `+80` | méga rare |
| `+81` à `+94` | méga rare / ultra rare |
| `+95` et plus | ultra rare |

## Garde-fous

- Toujours mesurer hors échantillon avant d'intégrer une nouvelle règle.
- Afficher l'incertitude du bonus plutôt qu'un faux niveau certain.
- Ne pas sacrifier beaucoup de probabilité sportive pour poursuivre un bonus rare :
  le bonus exact ne compte que si le score exact se réalise.
