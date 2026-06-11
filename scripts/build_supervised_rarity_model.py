#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from math import sqrt
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "mpp_history.sqlite3"
MODEL = ROOT / "data" / "mpp_supervised_rarity_model.json"
EXTENSION = ROOT / "extension" / "rarity-label-model.js"
REPORT = ROOT / "docs" / "SUPERVISED_RARITY_MODEL.json"
PARAMETERS = {
    "metric": "euclidean",
    "score_representation": "total_margin",
    "identity_penalty": 0.5,
    "goal_weight": 0.5,
    "quotation_weight": 0.5,
    "bet_weight": 5.0,
    "neighbors": 7,
    "international_weight": 1.5,
    "distance_power": 0.0,
    "distance_floor": 0.15,
}
INTERNATIONAL_IDS = {"9", "19"}


def load_rows() -> list[dict]:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT m.match_id, md.championship_id, md.season, m.actual_home_score,
               m.actual_away_score, m.actual_outcome, m.rarity_level,
               CASE m.actual_outcome
                   WHEN 'home' THEN md.home_quotation
                   WHEN 'draw' THEN md.draw_quotation
                   ELSE md.away_quotation
               END AS quotation,
               CASE m.actual_outcome
                   WHEN 'home' THEN md.home_bet_share
                   WHEN 'draw' THEN md.draw_bet_share
                   ELSE md.away_bet_share
               END AS bet_share
        FROM matches m
        JOIN match_metadata md USING (match_id)
        WHERE m.rarity_level IS NOT NULL
          AND md.home_bet_share IS NOT NULL
          AND md.draw_bet_share IS NOT NULL
          AND md.away_bet_share IS NOT NULL
        """
    ).fetchall()
    connection.close()
    return [
        {
            "match_id": row["match_id"],
            "championship_id": row["championship_id"],
            "season": row["season"],
            "kind": "draw" if row["actual_outcome"] == "draw" else "win",
            "winner_goals": max(row["actual_home_score"], row["actual_away_score"]),
            "loser_goals": min(row["actual_home_score"], row["actual_away_score"]),
            "quotation": row["quotation"],
            "bet_share": row["bet_share"],
            "rarity_level": row["rarity_level"],
        }
        for row in rows
    ]


def distance(left: dict, right: dict) -> float:
    if PARAMETERS["score_representation"] == "total_margin":
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
    differences = [abs(a - b) for a, b in zip(score_left, score_right)]
    weighted = [
        *(PARAMETERS["goal_weight"] * value for value in differences),
        PARAMETERS["quotation_weight"] * abs(left["quotation"] - right["quotation"]) / 50,
        PARAMETERS["bet_weight"] * abs(left["bet_share"] - right["bet_share"]),
    ]
    result = (
        sqrt(sum(value * value for value in weighted))
        if PARAMETERS["metric"] == "euclidean"
        else sum(weighted)
    )
    return result + (PARAMETERS["identity_penalty"] if any(differences) else 0)


def predict(training: list[dict], row: dict) -> tuple[int, float]:
    neighbors = sorted(
        (
            (distance(candidate, row), candidate)
            for candidate in training
            if candidate["kind"] == row["kind"]
        ),
        key=lambda item: item[0],
    )[: PARAMETERS["neighbors"]]
    votes: dict[int, float] = defaultdict(float)
    for item_distance, candidate in neighbors:
        competition_weight = (
            PARAMETERS["international_weight"]
            if str(candidate["championship_id"]) in INTERNATIONAL_IDS
            else 1.0
        )
        distance_weight = (
            1.0
            if PARAMETERS["distance_power"] == 0
            else 1 / (PARAMETERS["distance_floor"] + item_distance) ** PARAMETERS["distance_power"]
        )
        votes[candidate["rarity_level"]] += competition_weight * distance_weight
    total = sum(votes.values())
    bonuses = {1: 20, 2: 30, 3: 50, 4: 70, 5: 100}
    return max(votes, key=votes.get), sum(bonuses[level] * weight for level, weight in votes.items()) / total


def fold(match_id: str) -> int:
    return int(hashlib.sha256(match_id.encode()).hexdigest()[:8], 16) % 5


def metrics(predictions: list[tuple[int, float, int]]) -> dict:
    return {
        "rows": len(predictions),
        "accuracy": round(mean(predicted == actual for predicted, _, actual in predictions), 4),
        "mean_absolute_level_error": round(
            mean(abs(predicted - actual) for predicted, _, actual in predictions), 4
        ),
        "within_one_level": round(
            mean(abs(predicted - actual) <= 1 for predicted, _, actual in predictions), 4
        ),
        "mean_absolute_expected_bonus_error": round(
            mean(
                abs(expected_bonus - {1: 20, 2: 30, 3: 50, 4: 70, 5: 100}[actual])
                for _, expected_bonus, actual in predictions
            ),
            2,
        ),
    }


def main() -> None:
    rows = load_rows()
    cross_validation = []
    for row in rows:
        validation_fold = fold(row["match_id"])
        predicted_level, expected_bonus = predict(
                    [candidate for candidate in rows if fold(candidate["match_id"]) != validation_fold],
                    row,
                )
        cross_validation.append(
            (predicted_level, expected_bonus, row["rarity_level"])
        )
    championship_validation = {}
    for championship_id in sorted({row["championship_id"] for row in rows}):
        training = [row for row in rows if row["championship_id"] != championship_id]
        validation = [row for row in rows if row["championship_id"] == championship_id]
        championship_validation[f"other_to_{championship_id}"] = metrics(
            [
                (*predict(training, row), row["rarity_level"])
                for row in validation
            ]
        )
    compact_rows = [
        {
            "k": row["kind"],
            "w": row["winner_goals"],
            "l": row["loser_goals"],
            "q": row["quotation"],
            "b": row["bet_share"],
            "y": row["rarity_level"],
            "i": str(row["championship_id"]) in INTERNATIONAL_IDS,
        }
        for row in rows
    ]
    model = {"parameters": PARAMETERS, "rows": compact_rows}
    report = {
        "description": (
            "k plus proches voisins supervisé par les niveaux de rareté réellement "
            "attribués par MPP. Les scores gagnants domicile/extérieur sont miroir-fusionnés."
        ),
        "training_rows": len(rows),
        "parameters": PARAMETERS,
        "five_fold_match_validation": metrics(cross_validation),
        "leave_one_championship_out": championship_validation,
    }
    MODEL.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    EXTENSION.write_text(
        "// Generated by scripts/build_supervised_rarity_model.py\n"
        f"globalThis.MPP_RARITY_LABEL_MODEL={json.dumps(model, ensure_ascii=False, separators=(',', ':'))};\n"
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
