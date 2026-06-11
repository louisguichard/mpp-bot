#!/usr/bin/env python3
from __future__ import annotations

import json
import random
from collections import Counter

from build_supervised_rarity_model import ROOT, load_rows
from search_rarity_knn import BONUSES, dataset, predict, sorted_neighbors


SEARCH = ROOT / "docs" / "RARITY_KNN_SEARCH.json"
REPORT = ROOT / "docs" / "RARITY_MODEL_SELECTION_ANALYSIS.json"


def holdout_predictions(rows: list[dict], parameters: dict, held_out: str, excluded: set[str]) -> list[dict]:
    neighbors = sorted_neighbors(rows, parameters)
    predictions = []
    for index, row in enumerate(rows):
        if dataset(row) != held_out:
            continue
        level, expected_bonus = predict(
            rows,
            neighbors,
            index,
            parameters,
            lambda candidate: dataset(candidate) not in excluded | {held_out},
        )
        predictions.append(
            {
                "match_id": row["match_id"],
                "actual_level": row["rarity_level"],
                "predicted_level": level,
                "actual_bonus": BONUSES[row["rarity_level"]],
                "expected_bonus": expected_bonus,
                "absolute_bonus_error": abs(expected_bonus - BONUSES[row["rarity_level"]]),
            }
        )
    return predictions


def paired_bootstrap(current: list[dict], selected: list[dict], *, samples: int = 20_000) -> dict:
    current_by_id = {row["match_id"]: row for row in current}
    selected_by_id = {row["match_id"]: row for row in selected}
    ids = sorted(current_by_id.keys() & selected_by_id.keys())
    differences = [
        selected_by_id[match_id]["absolute_bonus_error"]
        - current_by_id[match_id]["absolute_bonus_error"]
        for match_id in ids
    ]
    random.seed(20260611)
    means = sorted(
        sum(random.choice(differences) for _ in differences) / len(differences)
        for _ in range(samples)
    )
    observed = sum(differences) / len(differences)
    return {
        "rows": len(differences),
        "delta_selected_minus_current": round(observed, 3),
        "improvement_selected": round(-observed, 3),
        "bootstrap_95_percent_interval_for_delta": [
            round(means[int(samples * 0.025)], 3),
            round(means[int(samples * 0.975)], 3),
        ],
        "bootstrap_probability_selected_is_better": round(
            sum(value < 0 for value in means) / samples,
            4,
        ),
        "matches_better_selected": sum(value < 0 for value in differences),
        "matches_equal": sum(value == 0 for value in differences),
        "matches_worse_selected": sum(value > 0 for value in differences),
    }


def summarize(predictions: list[dict]) -> dict:
    return {
        "rows": len(predictions),
        "mean_absolute_expected_bonus_error": round(
            sum(row["absolute_bonus_error"] for row in predictions) / len(predictions),
            3,
        ),
        "level_accuracy": round(
            sum(row["predicted_level"] == row["actual_level"] for row in predictions)
            / len(predictions),
            4,
        ),
        "predicted_levels": dict(sorted(Counter(row["predicted_level"] for row in predictions).items())),
        "actual_levels": dict(sorted(Counter(row["actual_level"] for row in predictions).items())),
    }


def compare_holdout(rows: list[dict], current_parameters: dict, selected_parameters: dict, held_out: str, excluded: set[str]) -> dict:
    current = holdout_predictions(rows, current_parameters, held_out, excluded)
    selected = holdout_predictions(rows, selected_parameters, held_out, excluded)
    return {
        "training_excludes": sorted(excluded | {held_out}),
        "current": summarize(current),
        "selected": summarize(selected),
        "paired_bootstrap": paired_bootstrap(current, selected),
    }


def main() -> None:
    rows = load_rows()
    search = json.loads(SEARCH.read_text())
    current_parameters = search["current_model"]["parameters"]
    selected_parameters = {
        **search["selected_without_euro"]["parameters"],
        # The search optimum is 3.0, but 1.5 is on the same performance
        # plateau and is retained as a conservative shrinkage choice.
        "international_weight": 1.5,
    }
    report = {
        "description": (
            "Validation finale du modèle déployé sans aucun label Euro. "
            "Le bootstrap est apparié par match et porte sur l'erreur absolue du bonus attendu."
        ),
        "deployment_choice": (
            "Le maximum de grille donne un poids international de 3.0. Le poids 1.5 "
            "est déployé car il se trouve sur le même plateau de performance, améliore "
            "l'Euro presque autant et réduit le risque de surapprentissage sur la CAN."
        ),
        "rows": len(rows),
        "current_parameters": current_parameters,
        "selected_parameters": selected_parameters,
        "euro_final_holdout": compare_holdout(
            rows, current_parameters, selected_parameters, "euro_2024", set()
        ),
        "can_holdout_without_euro": compare_holdout(
            rows, current_parameters, selected_parameters, "can_2025", {"euro_2024"}
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
