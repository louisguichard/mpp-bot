#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from build_supervised_rarity_model import ROOT, load_rows, metrics


REPORT = ROOT / "docs" / "SUPERVISED_RARITY_ROBUSTNESS.json"
BONUSES = {1: 20, 2: 30, 3: 50, 4: 70, 5: 100}
CANDIDATES = (
    (0.5, 2, 1, 1, 7),
    (1, 2, 2, 1, 7),
    (1, 1, 1, 3, 7),
    (0.5, 1, 2, 1, 5),
    (1, 2, 1, 1, 7),
    (1, 2, 2, 1, 11),
)


def split(match_id: str, salt: str) -> int:
    return int(hashlib.sha256(f"{salt}:{match_id}".encode()).hexdigest()[:8], 16) % 5


def neighbor_prediction(training: list[dict], row: dict, parameters: tuple) -> tuple[int, float]:
    identity, goal_weight, quotation_weight, bet_weight, neighbors = parameters
    distances = []
    for candidate in training:
        if candidate["kind"] != row["kind"]:
            continue
        same_score = (
            candidate["winner_goals"] == row["winner_goals"]
            and candidate["loser_goals"] == row["loser_goals"]
        )
        distance = (
            goal_weight
            * (
                abs(candidate["winner_goals"] - row["winner_goals"])
                + abs(candidate["loser_goals"] - row["loser_goals"])
            )
            + quotation_weight * abs(candidate["quotation"] - row["quotation"]) / 50
            + bet_weight * abs(candidate["bet_share"] - row["bet_share"])
            + (0 if same_score else identity)
        )
        distances.append((distance, candidate["rarity_level"]))
    votes: dict[int, float] = defaultdict(float)
    for distance, level in sorted(distances)[:neighbors]:
        votes[level] += 1 / (0.15 + distance)
    total = sum(votes.values())
    return max(votes, key=votes.get), sum(BONUSES[level] * weight for level, weight in votes.items()) / total


def simple_prediction(training: list[dict], row: dict, with_context: bool) -> tuple[int, float]:
    keys = [
        lambda item: (
            item["kind"],
            item["winner_goals"],
            item["loser_goals"],
            int(item["quotation"] // 20),
            int(item["bet_share"] // 0.1),
        ),
        lambda item: (
            item["kind"],
            item["winner_goals"],
            item["loser_goals"],
            int(item["quotation"] // 20),
        ),
        lambda item: (item["kind"], item["winner_goals"], item["loser_goals"]),
        lambda item: (item["kind"],),
    ] if with_context else [
        lambda item: (item["kind"], item["winner_goals"], item["loser_goals"]),
        lambda item: (item["kind"],),
    ]
    for key in keys:
        levels = [candidate["rarity_level"] for candidate in training if key(candidate) == key(row)]
        if len(levels) >= 3:
            return Counter(levels).most_common(1)[0][0], sum(BONUSES[level] for level in levels) / len(levels)
    raise RuntimeError("Aucun groupe de repli.")


def cross_validate(rows: list[dict], predictor) -> dict:
    predictions = []
    for row in rows:
        training = [candidate for candidate in rows if split(candidate["match_id"], "outer") != split(row["match_id"], "outer")]
        predictions.append((*predictor(training, row), row["rarity_level"]))
    return metrics(predictions)


def nested_validation(rows: list[dict]) -> tuple[dict, list[tuple]]:
    predictions = []
    chosen = []
    for outer_fold in range(5):
        training = [row for row in rows if split(row["match_id"], "outer") != outer_fold]
        validation = [row for row in rows if split(row["match_id"], "outer") == outer_fold]
        best = None
        for parameters in CANDIDATES:
            inner_predictions = []
            for row in training:
                inner_training = [
                    candidate
                    for candidate in training
                    if split(candidate["match_id"], "inner") != split(row["match_id"], "inner")
                ]
                inner_predictions.append((*neighbor_prediction(inner_training, row, parameters), row["rarity_level"]))
            result = metrics(inner_predictions)
            candidate = (result["mean_absolute_level_error"], -result["accuracy"], parameters)
            if best is None or candidate < best:
                best = candidate
        chosen.append(best[-1])
        predictions.extend(
            (*neighbor_prediction(training, row, best[-1]), row["rarity_level"])
            for row in validation
        )
    return metrics(predictions), chosen


def main() -> None:
    rows = load_rows()
    nested, chosen = nested_validation(rows)
    report = {
        "interpretation": (
            "La validation imbriquée choisit les paramètres sans voir le pli évalué. "
            "Elle constitue le contrôle principal contre le surapprentissage."
        ),
        "simple_score_only": cross_validate(rows, lambda training, row: simple_prediction(training, row, False)),
        "simple_score_quotation_bets_buckets": cross_validate(
            rows, lambda training, row: simple_prediction(training, row, True)
        ),
        "fixed_neighbor_model": cross_validate(
            rows, lambda training, row: neighbor_prediction(training, row, (1, 1, 1, 3, 7))
        ),
        "nested_neighbor_model": nested,
        "nested_chosen_parameters": chosen,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
