#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from math import sqrt

from build_supervised_rarity_model import ROOT, load_rows, metrics


REPORT = ROOT / "docs" / "RARITY_REGRESSION_ANALYSIS.json"
BONUSES = {1: 20, 2: 30, 3: 50, 4: 70, 5: 100}
LAMBDAS = (0.0, 0.1, 1.0, 10.0, 100.0)


def fold(match_id: str) -> int:
    return int(hashlib.sha256(match_id.encode()).hexdigest()[:8], 16) % 5


def raw_features(row: dict) -> list[float]:
    winner = row["winner_goals"]
    loser = row["loser_goals"]
    quotation = row["quotation"] / 100
    share = row["bet_share"]
    return [
        float(row["kind"] == "draw"),
        winner,
        loser,
        winner + loser,
        winner - loser,
        winner * winner,
        loser * loser,
        quotation,
        share,
        quotation * share,
    ]


def prepare(training: list[dict]) -> tuple[list[list[float]], list[float], list[float]]:
    raw = [raw_features(row) for row in training]
    means = [sum(column) / len(column) for column in zip(*raw)]
    scales = [
        sqrt(sum((value - mean) ** 2 for value in column) / len(column)) or 1.0
        for column, mean in zip(zip(*raw), means)
    ]
    return [[1.0, *[(value - mean) / scale for value, mean, scale in zip(row, means, scales)]] for row in raw], means, scales


def solve(matrix: list[list[float]], values: list[float]) -> list[float]:
    augmented = [row[:] + [value] for row, value in zip(matrix, values)]
    for column in range(len(augmented)):
        pivot = max(range(column, len(augmented)), key=lambda index: abs(augmented[index][column]))
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        if abs(divisor) < 1e-12:
            continue
        augmented[column] = [value / divisor for value in augmented[column]]
        for row_index, row in enumerate(augmented):
            if row_index == column:
                continue
            factor = row[column]
            augmented[row_index] = [
                value - factor * pivot_value
                for value, pivot_value in zip(row, augmented[column])
            ]
    return [row[-1] for row in augmented]


def fit(training: list[dict], ridge: float) -> tuple[list[float], list[float], list[float]]:
    design, means, scales = prepare(training)
    targets = [BONUSES[row["rarity_level"]] for row in training]
    size = len(design[0])
    gram = [[sum(row[left] * row[right] for row in design) for right in range(size)] for left in range(size)]
    for index in range(1, size):
        gram[index][index] += ridge
    rhs = [sum(row[index] * target for row, target in zip(design, targets)) for index in range(size)]
    return solve(gram, rhs), means, scales


def predict(model: tuple[list[float], list[float], list[float]], row: dict) -> tuple[int, float]:
    coefficients, means, scales = model
    features = [1.0, *[(value - mean) / scale for value, mean, scale in zip(raw_features(row), means, scales)]]
    expected = min(100.0, max(20.0, sum(coefficient * value for coefficient, value in zip(coefficients, features))))
    level = min(BONUSES, key=lambda candidate: abs(BONUSES[candidate] - expected))
    return level, expected


def cross_validate(rows: list[dict], ridge: float) -> dict:
    predictions = []
    for validation_fold in range(5):
        training = [row for row in rows if fold(row["match_id"]) != validation_fold]
        model = fit(training, ridge)
        predictions.extend(
            (*predict(model, row), row["rarity_level"])
            for row in rows
            if fold(row["match_id"]) == validation_fold
        )
    return metrics(predictions)


def main() -> None:
    rows = load_rows()
    results = {str(ridge): cross_validate(rows, ridge) for ridge in LAMBDAS}
    best_ridge = min(
        LAMBDAS,
        key=lambda ridge: results[str(ridge)]["mean_absolute_expected_bonus_error"],
    )
    report = {
        "description": (
            "Régression ridge linéaire du bonus réel à partir du score miroir-fusionné, "
            "du type nul/victoire, de la cote MPP et de la part de paris sur l'issue."
        ),
        "features": [
            "draw",
            "winner_goals",
            "loser_goals",
            "total_goals",
            "goal_margin",
            "winner_goals_squared",
            "loser_goals_squared",
            "quotation",
            "bet_share",
            "quotation_x_bet_share",
        ],
        "five_fold_results": results,
        "best_ridge": best_ridge,
        "best_result": results[str(best_ridge)],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
