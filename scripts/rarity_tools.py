from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from mpp_optimizer.model import CROWD_GOAL_BIAS, outcome, outcome_probabilities


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "data" / "mpp_neutral_score_distribution_model.json"
QUOTE_BUCKETS = (0, 40, 60, 80, 100, 120, 150, 1000)
BUCKET_CENTERS = {
    "0-40": 30,
    "40-60": 50,
    "60-80": 70,
    "80-100": 90,
    "100-120": 110,
    "120-150": 135,
    "150-1000": 175,
}
RARITY_BONUSES = {1: 20, 2: 30, 3: 50, 4: 70, 5: 100}


def load_model(path: Path = DEFAULT_MODEL) -> dict[str, dict[str, float]]:
    payload = json.loads(path.read_text())
    return {
        key: {row["relative_score"]: float(row["probability"]) for row in value["scores"]}
        for key, value in payload["distributions"].items()
    }


def bucket_label(value: float) -> str:
    for lower, upper in zip(QUOTE_BUCKETS, QUOTE_BUCKETS[1:]):
        if lower <= value < upper:
            return f"{lower:g}-{upper:g}"
    raise ValueError(value)


def build_neutral_model(
    connection: sqlite3.Connection, excluded_match_ids: set[str] | None = None
) -> dict[str, dict[str, float]]:
    excluded_match_ids = excluded_match_ids or set()
    rows = connection.execute(
        """
        SELECT sc.match_id, sc.predicted_outcome AS issue, sc.home_score,
               sc.away_score, sc.forecast_count, md.match_date,
               CASE sc.predicted_outcome
                   WHEN 'home' THEN md.home_quotation
                   WHEN 'draw' THEN md.draw_quotation
                   ELSE md.away_quotation
               END AS quotation
        FROM score_counts sc
        JOIN match_metadata md USING (match_id)
        WHERE sc.contest_id = 'general'
          AND sc.home_score <= 10 AND sc.away_score <= 10
        """
    ).fetchall()
    rows = [
        row
        for row in rows
        if row["match_id"] not in excluded_match_ids
        and row["quotation"] is not None
        and row["match_date"][:10] <= date.today().isoformat()
    ]
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        totals[(row["match_id"], row["issue"])] += row["forecast_count"]
    grouped: dict[tuple[str, str], list[tuple[str, str, float]]] = defaultdict(list)
    for row in rows:
        issue = row["issue"]
        relative = (
            f"{row['away_score']}-{row['home_score']}"
            if issue == "away"
            else f"{row['home_score']}-{row['away_score']}"
        )
        kind = "draw" if issue == "draw" else "win"
        grouped[(kind, bucket_label(row["quotation"]))].append(
            (
                row["match_id"],
                relative,
                row["forecast_count"] / totals[(row["match_id"], issue)],
            )
        )
    result = {}
    for (kind, bucket), group in grouped.items():
        match_ids = {match_id for match_id, _, _ in group}
        probabilities: dict[str, float] = defaultdict(float)
        for _, score, share in group:
            probabilities[score] += share / len(match_ids)
        result[f"{kind}:{bucket}"] = dict(probabilities)
    return result


def interpolated_distribution(
    model: dict[str, dict[str, float]], kind: str, quotation: float
) -> dict[str, float]:
    candidates = sorted(
        (
            BUCKET_CENTERS[key.split(":", 1)[1]],
            scores,
        )
        for key, scores in model.items()
        if key.startswith(f"{kind}:") and key.split(":", 1)[1] in BUCKET_CENTERS
    )
    if not candidates:
        return {}
    upper_index = next(
        (index for index, (center, _) in enumerate(candidates) if center >= quotation),
        -1,
    )
    if upper_index <= 0:
        return candidates[0][1]
    if upper_index < 0:
        return candidates[-1][1]
    lower_center, lower = candidates[upper_index - 1]
    upper_center, upper = candidates[upper_index]
    upper_weight = (quotation - lower_center) / (upper_center - lower_center)
    return {
        score: lower.get(score, 0) * (1 - upper_weight) + upper.get(score, 0) * upper_weight
        for score in set(lower) | set(upper)
    }


def relative_score(score: tuple[int, int]) -> str:
    home, away = score
    return f"{away}-{home}" if outcome(home, away) == "away" else f"{home}-{away}"


def historical_share(
    model: dict[str, dict[str, float]],
    score: tuple[int, int],
    quotation: float,
) -> float | None:
    kind = "draw" if outcome(*score) == "draw" else "win"
    distribution = interpolated_distribution(model, kind, quotation)
    return distribution.get(relative_score(score))


def heuristic_shares(
    matrix: dict[tuple[int, int], float], alpha: float = 2.0
) -> dict[tuple[int, int], float]:
    totals = outcome_probabilities(matrix)
    weights = {}
    denominators = defaultdict(float)
    for score, probability in matrix.items():
        conditional = probability / totals[outcome(*score)]
        weight = (
            conditional**alpha
            * math.exp(-CROWD_GOAL_BIAS * sum(score))
            * (1.25 if abs(score[0] - score[1]) == 1 else 1)
        )
        weights[score] = weight
        denominators[outcome(*score)] += weight
    return {
        score: weight / denominators[outcome(*score)]
        for score, weight in weights.items()
    }


def estimated_share(
    model: dict[str, dict[str, float]],
    matrix: dict[tuple[int, int], float],
    score: tuple[int, int],
    quotation: float,
    historical_weight: float = 0.85,
    scale: float = 1.0,
    exponent: float = 1.0,
) -> float:
    heuristic = heuristic_shares(matrix)[score]
    historical = historical_share(model, score, quotation)
    raw = (
        heuristic
        if historical is None
        else historical_weight * historical + (1 - historical_weight) * heuristic
    )
    return min(1.0, max(0.0, scale * raw**exponent))


def rarity_level(share: float) -> int:
    if share < 0.005:
        return 5
    if share < 0.05:
        return 4
    if share < 0.20:
        return 3
    if share <= 0.30:
        return 2
    return 1

