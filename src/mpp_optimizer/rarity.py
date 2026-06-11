from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

from .model import calibrate_poisson, outcome, score_matrix


DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "data" / "mpp_supervised_rarity_model.json"
BONUSES = {1: 20.0, 2: 30.0, 3: 50.0, 4: 70.0, 5: 100.0}


@dataclass(frozen=True)
class ForecastRecommendation:
    home_score: int
    away_score: int
    outcome: str
    outcome_probability: float
    score_probability: float
    quotation: float
    expected_base_points: float
    expected_exact_points: float
    expected_points: float
    expected_bonus: float
    rarity_level: int


class SupervisedRarityModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.parameters = payload["parameters"]
        self.rows = payload["rows"]

    @classmethod
    def load(cls, path: Path = DEFAULT_MODEL) -> "SupervisedRarityModel":
        return cls(json.loads(path.read_text()))

    def predict(
        self,
        *,
        kind: str,
        winner_goals: int,
        loser_goals: int,
        quotation: float,
        bet_share: float,
        international: bool = True,
    ) -> tuple[int, float]:
        parameters = self.parameters
        neighbors = sorted(
            (
                (
                    _distance(
                        row,
                        winner_goals=winner_goals,
                        loser_goals=loser_goals,
                        quotation=quotation,
                        bet_share=bet_share,
                        parameters=parameters,
                    ),
                    row,
                )
                for row in self.rows
                if row["k"] == kind
            ),
            key=lambda item: item[0],
        )[: int(parameters["neighbors"])]
        votes: dict[int, float] = defaultdict(float)
        for distance, row in neighbors:
            international_weight = float(parameters.get("international_weight", 1))
            competition_weight = international_weight if international and row.get("i") else 1.0
            power = float(parameters.get("distance_power", 1))
            distance_floor = float(parameters.get("distance_floor", 0.15))
            distance_weight = 1.0 if power == 0 else 1 / (distance_floor + distance) ** power
            votes[int(row["y"])] += competition_weight * distance_weight
        total = sum(votes.values())
        if not total:
            raise ValueError(f"No rarity neighbors for score kind {kind}.")
        level = max(votes, key=votes.get)
        expected_bonus = sum(BONUSES[key] * weight for key, weight in votes.items()) / total
        return level, min(100.0, max(20.0, expected_bonus))


def recommend_scores(
    probabilities: dict[str, float],
    quotations: dict[str, float],
    bets: dict[str, float],
    rarity_model: SupervisedRarityModel,
    *,
    max_goals: int = 8,
) -> list[ForecastRecommendation]:
    home_xg, away_xg = calibrate_poisson(probabilities, max_goals)
    scores = score_matrix(home_xg, away_xg, max_goals)
    recommendations = []
    for (home_score, away_score), score_probability in scores.items():
        issue = outcome(home_score, away_score)
        level, expected_bonus = rarity_model.predict(
            kind="draw" if issue == "draw" else "win",
            winner_goals=max(home_score, away_score),
            loser_goals=min(home_score, away_score),
            quotation=float(quotations[issue]),
            bet_share=float(bets[issue]),
        )
        expected_base = float(probabilities[issue]) * float(quotations[issue])
        expected_exact = score_probability * expected_bonus
        recommendations.append(
            ForecastRecommendation(
                home_score=home_score,
                away_score=away_score,
                outcome=issue,
                outcome_probability=float(probabilities[issue]),
                score_probability=score_probability,
                quotation=float(quotations[issue]),
                expected_base_points=expected_base,
                expected_exact_points=expected_exact,
                expected_points=expected_base + expected_exact,
                expected_bonus=expected_bonus,
                rarity_level=level,
            )
        )
    return sorted(recommendations, key=lambda item: item.expected_points, reverse=True)


def _distance(
    row: dict[str, Any],
    *,
    winner_goals: int,
    loser_goals: int,
    quotation: float,
    bet_share: float,
    parameters: dict[str, Any],
) -> float:
    score_representation = parameters.get("score_representation", "winner_loser")
    if score_representation == "total_margin":
        left = (int(row["w"]) + int(row["l"]), int(row["w"]) - int(row["l"]))
        right = (winner_goals + loser_goals, winner_goals - loser_goals)
    else:
        left = (int(row["w"]), int(row["l"]))
        right = (winner_goals, loser_goals)
    score_differences = [abs(a - b) for a, b in zip(left, right)]
    goal_weight = float(parameters.get("goal_weight", parameters.get("goal_distance_weight", 1)))
    quotation_weight = float(
        parameters.get("quotation_weight", parameters.get("quotation_distance_weight", 1))
    )
    bet_weight = float(parameters.get("bet_weight", parameters.get("bet_share_distance_weight", 3)))
    weighted = [
        *(goal_weight * value for value in score_differences),
        quotation_weight * abs(float(row["q"]) - quotation) / 50,
        bet_weight * abs(float(row["b"]) - bet_share),
    ]
    result = (
        sqrt(sum(value * value for value in weighted))
        if parameters.get("metric", "manhattan") == "euclidean"
        else sum(weighted)
    )
    identity_penalty = float(
        parameters.get("identity_penalty", parameters.get("score_identity_penalty", 1))
    )
    if any(score_differences):
        result += identity_penalty
    return result
