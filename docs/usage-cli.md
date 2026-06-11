# Mode ligne de commande

Tout le moteur est utilisable depuis le terminal, sans rien déployer. C'est
aussi le meilleur moyen de comprendre ce que fait le bot avant de l'automatiser.

## Prérequis

- Python 3.11+ (aucune dépendance externe pour ce mode) ;
- un fichier `.env` à la racine (voir `.env.example`) ;
- pour interroger MPP : un jeton d'accès dans `MPP_TOKEN`, ou mieux, un fichier
  de jetons avec refresh automatique (voir plus bas).

### Obtenir un jeton MPP

Se connecter à [mpp.football](https://mpp.football) dans Chrome, ouvrir les
DevTools → onglet **Réseau** → cliquer sur une requête vers `api.mpp.football`
→ copier la valeur de l'en-tête `Authorization` (sans le préfixe `Bearer `).
Le `refresh_token` s'obtient dans la réponse de
`connect.ligue1.fr/oauth/token`. Pour un usage répété, créer le fichier :

```json
{
  "access_token": "...",
  "refresh_token": "..."
}
```

dans `.secrets/mpp-bot-tokens.json` (dossier ignoré par Git, `chmod 600`).
Le client rafraîchit alors le jeton automatiquement avant expiration.

## Calculer l'espérance d'un match isolé

Le moteur de base prend un fichier JSON décrivant un match (cotes 1N2
décimales et quotations MPP) :

```bash
PYTHONPATH=src python3.11 -m mpp_optimizer.cli examples/match.json
```

Il affiche les scores classés par espérance décroissante, avec le détail
base + bonus. Voir `examples/match.json` pour le format d'entrée.

## Les commandes du bot (lecture seule par défaut)

```bash
export MPP_BOT_TOKEN_FILE="$PWD/.secrets/mpp-bot-tokens.json"

# Lister les matchs à venir, leur association Polymarket et l'heure T-15
PYTHONPATH=src python3.11 -m mpp_optimizer.bot_cli plan

# Recalculer TOUS les matchs et afficher ce qui serait joué (dry-run)
PYTHONPATH=src python3.11 -m mpp_optimizer.bot_cli sync

# Pareil, mais écrit réellement les pronostics qui changent, puis vérifie
PYTHONPATH=src python3.11 -m mpp_optimizer.bot_cli sync --write

# Détailler la recommandation d'un seul match
PYTHONPATH=src python3.11 -m mpp_optimizer.bot_cli forecast --match-id ID_MATCH
```

Le mode `sync` est idempotent : un pronostic déjà optimal n'est jamais
réécrit, et chaque écriture est vérifiée par une relecture de l'API. Sans
`--write`, **aucune** écriture n'est possible (le client MPP lève une
exception par construction).

Exemple de sortie `sync` (résumé) :

```json
{
  "mode": "dry-run",
  "checked": 72,
  "would_write": 57,
  "already_current": 15,
  "skipped": 0,
  "errors": 0
}
```

## Le tableau de bord web (bonus)

Une petite interface de laboratoire compare les fournisseurs de cotes et
affiche les données brutes d'un match :

```bash
PYTHONPATH=src python3.11 -m mpp_optimizer.webapp
# puis ouvrir http://127.0.0.1:8765
```

Elle sert aussi de serveur de fixture pour tester l'extension Chrome
(`http://127.0.0.1:8765/mpp-fixture.html`).

## Lancer les tests

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests -v
node tests/test_extension.mjs   # test réel de l'extension (réseau requis)
```
