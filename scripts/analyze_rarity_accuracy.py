#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import mean

from mpp_optimizer.model import calibrate_poisson, score_matrix
from rarity_tools import (
    ROOT,
    build_neutral_model,
    estimated_share,
    heuristic_shares,
    historical_share,
    rarity_level,
)


DATABASE = ROOT / "data" / "mpp_history.sqlite3"
REPORT = ROOT / "docs" / "RARITY_MODEL_ACCURACY.json"


def fold(match_id: str) -> int:
    return int(hashlib.sha256(match_id.encode()).hexdigest()[:8], 16) % 5


def load_targets(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT m.match_id, m.actual_home_score, m.actual_away_score, m.actual_outcome,
               m.rarity_level, md.home_quotation, md.draw_quotation, md.away_quotation,
               md.home_bet_share, md.draw_bet_share, md.away_bet_share
        FROM matches m
        JOIN match_metadata md USING (match_id)
        WHERE m.rarity_level IS NOT NULL
          AND m.actual_home_score <= 8 AND m.actual_away_score <= 8
          AND md.home_bet_share IS NOT NULL
          AND md.draw_bet_share IS NOT NULL
          AND md.away_bet_share IS NOT NULL
        """
    ).fetchall()
    return [dict(row) for row in rows]


def enrich(row: dict, model: dict) -> dict:
    matrix = row["matrix"]
    score = row["score"]
    quotation = row["quotation"]
    empirical_share = historical_share(model, score, quotation)
    return {
        **row,
        "empirical_share": empirical_share,
    }


def prepare(row: dict) -> dict:
    target = {
        "home": row["home_bet_share"],
        "draw": row["draw_bet_share"],
        "away": row["away_bet_share"],
    }
    total = sum(target.values())
    target = {key: value / total for key, value in target.items()}
    matrix = score_matrix(*calibrate_poisson(target), 8)
    score = (row["actual_home_score"], row["actual_away_score"])
    return {
        **row,
        "matrix": matrix,
        "score": score,
        "quotation": row[f"{row['actual_outcome']}_quotation"],
        "old_share": heuristic_shares(matrix)[score],
    }


def metric(rows: list[dict], predictor) -> dict:
    predictions = [rarity_level(predictor(row)) for row in rows]
    actual = [row["rarity_level"] for row in rows]
    return {
        "rows": len(rows),
        "accuracy": round(mean(left == right for left, right in zip(predictions, actual)), 4),
        "mean_absolute_level_error": round(mean(abs(left - right) for left, right in zip(predictions, actual)), 4),
        "within_one_level": round(mean(abs(left - right) <= 1 for left, right in zip(predictions, actual)), 4),
        "predicted_levels": dict(sorted(Counter(predictions).items())),
    }


def transformed_share(row: dict, weight: float, scale: float, exponent: float) -> float:
    raw = (
        row["old_share"]
        if row["empirical_share"] is None
        else weight * row["empirical_share"] + (1 - weight) * row["old_share"]
    )
    return min(1.0, scale * raw**exponent)


def fit(rows: list[dict]) -> tuple[float, float, float]:
    best = None
    for weight_step in range(0, 21):
        weight = weight_step / 20
        for exponent_step in range(6, 15):
            exponent = exponent_step / 10
            for scale_step in range(8, 33):
                scale = scale_step / 20
                errors = []
                correct = 0
                for row in rows:
                    predicted = rarity_level(transformed_share(row, weight, scale, exponent))
                    errors.append(abs(predicted - row["rarity_level"]))
                    correct += predicted == row["rarity_level"]
                candidate = (
                    mean(errors),
                    -correct / len(rows),
                    abs(weight - 0.85),
                    weight,
                    scale,
                    exponent,
                )
                if best is None or candidate < best:
                    best = candidate
    assert best is not None
    return best[3], best[4], best[5]


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    targets = [prepare(row) for row in load_targets(connection)]
    predictions = []
    fitted_parameters = []
    for validation_fold in range(5):
        validation_ids = {row["match_id"] for row in targets if fold(row["match_id"]) == validation_fold}
        model = build_neutral_model(connection, validation_ids)
        training = [enrich(row, model) for row in targets if row["match_id"] not in validation_ids]
        validation = [enrich(row, model) for row in targets if row["match_id"] in validation_ids]
        parameters = fit(training)
        fitted_parameters.append(parameters)
        for row in validation:
            predictions.append({**row, "fitted_share": transformed_share(row, *parameters)})
    connection.close()

    report = {
        "method": "Validation croisée par match en 5 plis. Le modèle de distribution exclut toujours les matchs évalués.",
        "rows": len(predictions),
        "actual_levels": dict(sorted(Counter(row["rarity_level"] for row in predictions).items())),
        "old_heuristic": metric(predictions, lambda row: row["old_share"]),
        "historical_only": metric(
            predictions,
            lambda row: row["empirical_share"] if row["empirical_share"] is not None else row["old_share"],
        ),
        "current_extension_85_15": metric(
            predictions,
            lambda row: transformed_share(row, 0.85, 1.0, 1.0),
        ),
        "cross_validated_calibrated": metric(predictions, lambda row: row["fitted_share"]),
        "fold_parameters": [
            {"historical_weight": weight, "scale": scale, "exponent": exponent}
            for weight, scale, exponent in fitted_parameters
        ],
        "suggested_parameters": {
            "historical_weight": round(mean(row[0] for row in fitted_parameters), 3),
            "scale": round(mean(row[1] for row in fitted_parameters), 3),
            "exponent": round(mean(row[2] for row in fitted_parameters), 3),
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
