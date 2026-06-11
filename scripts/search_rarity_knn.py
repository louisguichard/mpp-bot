#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from math import sqrt

from build_supervised_rarity_model import ROOT, load_rows, metrics


REPORT = ROOT / "docs" / "RARITY_KNN_SEARCH.json"
BONUSES = {1: 20, 2: 30, 3: 50, 4: 70, 5: 100}
INTERNATIONAL_IDS = {"9", "19"}
DATASET_NAMES = {
    ("1", 2024): "ligue_1_2024_2025",
    ("1", 2025): "ligue_1_2025_2026",
    ("6", 2025): "champions_league_2025_2026",
    ("9", 2023): "euro_2024",
    ("19", 2025): "can_2025",
}


def dataset(row: dict) -> str:
    return DATASET_NAMES.get(
        (str(row["championship_id"]), row["season"]),
        f"{row['championship_id']}_{row['season']}",
    )


def fold(row: dict) -> int:
    return int(hashlib.sha256(f"metric:{row['match_id']}".encode()).hexdigest()[:8], 16) % 5


def is_international(row: dict) -> bool:
    return str(row["championship_id"]) in INTERNATIONAL_IDS


def distance(left: dict, right: dict, parameters: dict) -> float:
    if parameters["score_representation"] == "total_margin":
        score_left = (
            left["winner_goals"] + left["loser_goals"],
            left["winner_goals"] - left["loser_goals"],
        )
        score_right = (
            right["winner_goals"] + right["loser_goals"],
            right["winner_goals"] - right["loser_goals"],
        )
    else:
        score_left = (left["winner_goals"], left["loser_goals"])
        score_right = (right["winner_goals"], right["loser_goals"])
    score_differences = [abs(a - b) for a, b in zip(score_left, score_right)]
    context_differences = [
        abs(left["quotation"] - right["quotation"]) / 50,
        abs(left["bet_share"] - right["bet_share"]),
    ]
    weighted = [
        *(parameters["goal_weight"] * value for value in score_differences),
        parameters["quotation_weight"] * context_differences[0],
        parameters["bet_weight"] * context_differences[1],
    ]
    result = sqrt(sum(value * value for value in weighted)) if parameters["metric"] == "euclidean" else sum(weighted)
    if score_differences[0] or score_differences[1]:
        result += parameters["identity_penalty"]
    return result


def sorted_neighbors(rows: list[dict], parameters: dict) -> list[list[tuple[float, int]]]:
    return [
        sorted(
            (
                (distance(candidate, row, parameters), candidate_index)
                for candidate_index, candidate in enumerate(rows)
                if candidate["kind"] == row["kind"] and candidate_index != row_index
            ),
            key=lambda item: item[0],
        )
        for row_index, row in enumerate(rows)
    ]


def predict(
    rows: list[dict],
    neighbors_by_row: list[list[tuple[float, int]]],
    row_index: int,
    parameters: dict,
    allowed,
) -> tuple[int, float]:
    votes: dict[int, float] = defaultdict(float)
    accepted = 0
    for item_distance, candidate_index in neighbors_by_row[row_index]:
        candidate = rows[candidate_index]
        if not allowed(candidate):
            continue
        competition_weight = parameters["international_weight"] if is_international(candidate) else 1.0
        distance_weight = 1.0 if parameters["distance_power"] == 0 else 1 / (0.15 + item_distance) ** parameters["distance_power"]
        votes[candidate["rarity_level"]] += competition_weight * distance_weight
        accepted += 1
        if accepted >= parameters["neighbors"]:
            break
    total = sum(votes.values())
    return (
        max(votes, key=votes.get),
        sum(BONUSES[level] * weight for level, weight in votes.items()) / total,
    )


def evaluate_indices(
    rows: list[dict],
    neighbors_by_row: list[list[tuple[float, int]]],
    parameters: dict,
    validation_indices: list[int],
    allowed_for_index,
) -> dict:
    return metrics(
        [
            (
                *predict(
                    rows,
                    neighbors_by_row,
                    row_index,
                    parameters,
                    lambda candidate, row_index=row_index: allowed_for_index(row_index, candidate),
                ),
                rows[row_index]["rarity_level"],
            )
            for row_index in validation_indices
        ]
    )


def holdout(
    rows: list[dict],
    neighbors_by_row: list[list[tuple[float, int]]],
    parameters: dict,
    held_out: str,
    *,
    exclude_training: set[str] | None = None,
) -> dict:
    excluded = {held_out, *(exclude_training or set())}
    validation = [index for index, row in enumerate(rows) if dataset(row) == held_out]
    return evaluate_indices(
        rows,
        neighbors_by_row,
        parameters,
        validation,
        lambda _, candidate: dataset(candidate) not in excluded,
    )


def cross_validation(
    rows: list[dict],
    neighbors_by_row: list[list[tuple[float, int]]],
    parameters: dict,
    *,
    excluded_datasets: set[str] | None = None,
) -> dict:
    excluded = excluded_datasets or set()
    validation = [index for index, row in enumerate(rows) if dataset(row) not in excluded]
    return evaluate_indices(
        rows,
        neighbors_by_row,
        parameters,
        validation,
        lambda row_index, candidate: dataset(candidate) not in excluded and fold(candidate) != fold(rows[row_index]),
    )


def dataset_fold_metrics(
    rows: list[dict],
    neighbors_by_row: list[list[tuple[float, int]]],
    parameters: dict,
    *,
    excluded_datasets: set[str] | None = None,
) -> dict[str, dict]:
    excluded = excluded_datasets or set()
    return {
        name: evaluate_indices(
            rows,
            neighbors_by_row,
            parameters,
            [index for index, row in enumerate(rows) if dataset(row) == name],
            lambda row_index, candidate: dataset(candidate) not in excluded and fold(candidate) != fold(rows[row_index]),
        )
        for name in sorted({dataset(row) for row in rows} - excluded)
    }


def mean_bonus_error(results: dict[str, dict]) -> float:
    return sum(result["mean_absolute_expected_bonus_error"] for result in results.values()) / len(results)


def base_parameters() -> list[dict]:
    return [
        {
            "metric": metric,
            "score_representation": score_representation,
            "identity_penalty": identity,
            "goal_weight": goals,
            "quotation_weight": quotation,
            "bet_weight": bets,
            "neighbors": 7,
            "international_weight": 1.0,
            "distance_power": 1.0,
        }
        for metric, score_representation, identity, goals, quotation, bets in itertools.product(
            ("manhattan", "euclidean"),
            ("winner_loser", "total_margin"),
            (0.0, 0.5, 1.0, 2.0),
            (0.5, 1.0, 2.0),
            (0.0, 0.5, 1.0, 2.0),
            (0.0, 1.0, 3.0, 5.0),
        )
    ]


def full_evaluation(
    rows: list[dict],
    parameters: dict,
    neighbors_by_row: list[list[tuple[float, int]]] | None = None,
) -> dict:
    neighbors_by_row = neighbors_by_row or sorted_neighbors(rows, parameters)
    euro = "euro_2024"
    can = "can_2025"
    no_euro_by_dataset = dataset_fold_metrics(rows, neighbors_by_row, parameters, excluded_datasets={euro})
    return {
        "parameters": parameters,
        "selection_without_euro": {
            "balanced_dataset_bonus_error": round(mean_bonus_error(no_euro_by_dataset), 3),
            "by_dataset": no_euro_by_dataset,
            "can_holdout_without_euro": holdout(rows, neighbors_by_row, parameters, can, exclude_training={euro}),
        },
        "euro_final_holdout": holdout(rows, neighbors_by_row, parameters, euro),
        "can_holdout": holdout(rows, neighbors_by_row, parameters, can),
        "overall_five_fold": cross_validation(rows, neighbors_by_row, parameters),
        "by_dataset_five_fold": dataset_fold_metrics(rows, neighbors_by_row, parameters),
    }


def selection_score(result: dict) -> tuple:
    selection = result["selection_without_euro"]
    can = selection["can_holdout_without_euro"]
    return (
        round((selection["balanced_dataset_bonus_error"] + can["mean_absolute_expected_bonus_error"]) / 2, 4),
        can["mean_absolute_expected_bonus_error"],
        -can["accuracy"],
    )


def main() -> None:
    rows = load_rows()
    euro = "euro_2024"
    base_results = []
    for parameters in base_parameters():
        neighbors_by_row = sorted_neighbors(rows, parameters)
        by_dataset = dataset_fold_metrics(rows, neighbors_by_row, parameters, excluded_datasets={euro})
        can = holdout(rows, neighbors_by_row, parameters, "can_2025", exclude_training={euro})
        base_results.append(
            {
                "parameters": parameters,
                "selection_without_euro": {
                    "balanced_dataset_bonus_error": round(mean_bonus_error(by_dataset), 3),
                    "can_holdout_without_euro": can,
                },
            }
        )
    base_results.sort(key=selection_score)

    finalists = []
    signatures = set()
    for base in base_results[:12]:
        distance_parameters = {
            key: value
            for key, value in base["parameters"].items()
            if key not in {"neighbors", "international_weight", "distance_power"}
        }
        neighbors_by_row = sorted_neighbors(rows, distance_parameters)
        for neighbors, international_weight, distance_power in itertools.product(
            (3, 5, 7, 9, 11, 15, 21, 31),
            (1.0, 1.25, 1.5, 2.0, 3.0),
            (0.0, 0.5, 1.0, 2.0),
        ):
            parameters = {
                **distance_parameters,
                "neighbors": neighbors,
                "international_weight": international_weight,
                "distance_power": distance_power,
            }
            signature = tuple(parameters.items())
            if signature in signatures:
                continue
            signatures.add(signature)
            finalists.append(full_evaluation(rows, parameters, neighbors_by_row))
    finalists.sort(key=selection_score)

    current = full_evaluation(
        rows,
        {
            "metric": "manhattan",
            "score_representation": "winner_loser",
            "identity_penalty": 1.0,
            "goal_weight": 1.0,
            "quotation_weight": 1.0,
            "bet_weight": 3.0,
            "neighbors": 7,
            "international_weight": 1.0,
            "distance_power": 1.0,
        },
    )
    report = {
        "description": (
            "Recherche d'hyperparamètres sélectionnée sans utiliser aucun label Euro. "
            "L'Euro est évalué une seule fois comme test final principal."
        ),
        "selection_objective": (
            "Moyenne de l'erreur bonus équilibrée entre datasets hors Euro et de "
            "l'erreur CAN tenue entièrement hors entraînement, Euro exclu."
        ),
        "rows": len(rows),
        "datasets": {
            name: sum(dataset(row) == name for row in rows)
            for name in sorted({dataset(row) for row in rows})
        },
        "searched_base_distances": len(base_results),
        "searched_finalists": len(finalists),
        "current_model": current,
        "selected_without_euro": finalists[0],
        "best_euro_post_hoc": min(
            finalists,
            key=lambda result: (
                result["euro_final_holdout"]["mean_absolute_expected_bonus_error"],
                -result["euro_final_holdout"]["accuracy"],
            ),
        ),
        "best_overall_post_hoc": min(
            finalists,
            key=lambda result: (
                result["overall_five_fold"]["mean_absolute_expected_bonus_error"],
                -result["overall_five_fold"]["accuracy"],
            ),
        ),
        "top_selected_without_euro": finalists[:20],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
