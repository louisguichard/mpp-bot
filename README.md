# MPP Bot

Un bot qui joue (bien) au [Mon Petit Prono](https://mpp.football) de la Coupe
du monde 2026, en maximisant l'espérance de points à partir des probabilités
de marché et d'un modèle de rareté entraîné sur données historiques.

> **Genèse.** Ce projet a été entièrement *vibe-codé* en une journée, avec
> Codex (GPT 5.5) principalement, puis Claude Code (Fable 5) une fois les
> quotas épuisés. Le code, les analyses statistiques, les backtests et cette
> documentation sont le produit de cette collaboration humain-IA.

## L'idée en bref

À MPP, un pronostic rapporte la **quotation** de l'issue (1, N ou 2) si elle
est correcte, plus un **bonus de rareté** si le score exact est trouvé — bonus
d'autant plus gros que peu de joueurs ont choisi ce score. Le bot choisit donc
le score qui maximise :

```text
E[points] = P(issue) × quotation MPP + P(score exact) × E[bonus de rareté]
```

Les trois ingrédients :

1. **P(issue)** vient de [Polymarket](https://polymarket.com) : un marché de
   prédiction liquide, gratuit, sans clé API, dont les prix sont une excellente
   estimation des probabilités 1N2 ;
2. **P(score exact)** vient d'un modèle de Poisson calibré sur ce 1N2 par
   recherche en grille ;
3. **E[bonus de rareté]** vient d'un kNN supervisé entraîné sur **741 bonus
   réellement attribués** par MPP (Ligue 1, Ligue des champions, Euro 2024,
   CAN 2025), collectés depuis les feuilles de scores publiques et agrégés
   anonymement.

Chaque hypothèse a été backtestée — y compris contre les cotes « score
exact » de bookmakers traitées comme vérité — et plusieurs raffinements
classiques (correction de Dixon-Coles, régression, calibration) ont été
**testés puis rejetés** parce qu'ils n'amélioraient pas les décisions. Tout
est documenté.

## Trois modes d'utilisation

| Mode | Pour qui | Documentation |
|---|---|---|
| 🖥️ **Ligne de commande** | calculer les meilleurs scores, jouer en une commande | [docs/usage-cli.md](docs/usage-cli.md) |
| 🧩 **Extension Chrome** | voir les espérances directement sur le site MPP | [docs/usage-extension.md](docs/usage-extension.md) |
| 🤖 **Bot automatisé** | pronostics rejoués automatiquement à T-15 de chaque match | [docs/usage-bot.md](docs/usage-bot.md) |

## La méthode en détail

[docs/methode.md](docs/methode.md) explique tout : le moteur d'espérance, le
choix de Polymarket, la collecte des données historiques, le modèle de rareté
et son protocole de validation, **toutes les hypothèses testées** (celles qui
ont marché comme celles qui ont échoué), les limites connues et les pistes
restantes. Les rapports bruts et les artefacts reproductibles sont dans
[docs/](docs/).

## Installation rapide

```bash
git clone https://github.com/louisguichard/mpp-bot.git
cd mpp-bot
cp .env.example .env   # puis remplir les variables nécessaires au mode choisi
PYTHONPATH=src python3.11 -m unittest discover -s tests -v
```

Python 3.11+, aucune dépendance externe pour le cœur du moteur. Seul le mode
bot automatisé installe Flask et les clients Google Cloud (`pip install ".[bot]"`).

## Avertissements

- L'API MPP utilisée est celle du site officiel, mais elle n'est **pas
  documentée publiquement** : ce projet peut cesser de fonctionner à tout
  moment et son usage relève de votre responsabilité vis-à-vis des
  [CGU de la LFP](https://ligue1.com/fr/legal/cgu).
- Le cadre le plus sain : un compte dédié et déclaré comme bot, dans une ligue
  privée entre amis, sans enjeu financier.
- Les écritures sont **désactivées par défaut** partout dans le code ; elles
  exigent un opt-in explicite et sont relues puis vérifiées après chaque envoi.
- Aucun jeton, identifiant ou donnée nominative de joueur n'est stocké dans ce
  dépôt : la base historique ne contient que des agrégats.

## Licence

[MIT](LICENSE).
