# Modélisation des prolongations Coupe du monde

Source : Fjelstul World Cup Database v1.2.0 (`matches.csv` et `goals.csv`), licence CC-BY-SA 4.0. Les données sont filtrées sur la Coupe du monde masculine, phase à élimination directe, hors replays.

## Résumé

- `all_mens_world_cup_knockout_extra_time_1934_2022` : 66 matchs, 1.000 but(s) en prolongation en moyenne, 47.0% décidés avant les tirs au but, 53.0% encore nuls après 120 minutes.
- `modern_mens_world_cup_knockout_extra_time_1986_2022` : 54 matchs, 0.704 but(s) en prolongation en moyenne, 37.0% décidés avant les tirs au but, 63.0% encore nuls après 120 minutes.
- `recent_mens_world_cup_knockout_extra_time_1998_2022` : 37 matchs, 0.649 but(s) en prolongation en moyenne, 35.1% décidés avant les tirs au but, 64.9% encore nuls après 120 minutes.

## Paramètres recommandés

- Slice recommandé : 1986-2022, parce que c'est l'ère moderne avec tirs au but et tableau KO comparable.
- Lambda total prolongation 30 min, après shrinkage : `0.710` but/match.
- À force égale : `0.355` but par équipe sur 30 min.
- Répartition conditionnelle si le match est nul à 90, après shrinkage : home `20.0%`, away `20.0%`, draw `60.0%`.

## Distribution empirique moderne 1986-2022

- Buts en prolongation : 0 but(s): 55.6%, 1 but(s): 25.9%, 2 but(s): 11.1%, 3 but(s): 7.4%.
- Score de la prolongation : 0-0: 55.6%, 0-1: 13.0%, 0-2: 3.7%, 1-0: 13.0%, 1-1: 7.4%, 1-2: 1.9%, 2-1: 5.6%.

## Remarque modèle MPP

Pour MPP, les tirs au but doivent rester ignorés. Le modèle doit donc laisser une masse `draw` après 120 minutes : cette masse correspond aux scores exacts encore nuls après prolongation, pas au vainqueur qualifié.
