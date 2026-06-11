#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "mpp_history.sqlite3"
DEFAULT_MODEL = ROOT / "data" / "mpp_score_distribution_model.json"
DEFAULT_ANALYSIS = ROOT / "docs" / "MPP_SCORE_DISTRIBUTION_ANALYSIS.json"
QUOTE_BUCKETS = (0, 40, 60, 80, 100, 120, 150, 1000)
SHARE_BUCKETS = (0, 0.05, 0.15, 0.30, 0.50, 0.70, 0.90, 1.01)
ISSUES = ("home", "draw", "away")


def main() -> None:
    parser = argparse.ArgumentParser(description="Modèle des scores saisis selon les données MPP.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        rows = load_rows(connection)
    finally:
        connection.close()

    historical = [row for row in rows if row["is_past"]]
    train = [row for row in historical if split(row["match_id"]) == "train"]
    test = [row for row in historical if split(row["match_id"]) == "test"]
    evaluation = {
        "issue_only": evaluate(train, test, lambda row: row["issue"]),
        "quotation_bucket": evaluate(train, test, quote_key),
        "community_share_bucket": evaluate(train, test, share_key),
    }
    model = {
        "description": (
            "Distribution empirique des scores saisis par les joueurs visibles dans "
            "les scoresheets MPP, conditionnée par l'issue et la quotation MPP."
        ),
        "warning": (
            "Les scoresheets exposent un échantillon biaisé d'environ 100 joueurs, "
            "pas toute la communauté MPP."
        ),
        "matches": len({row["match_id"] for row in rows}),
        "forecasts": sum(row["count"] for row in rows),
        "quotation_buckets": list(QUOTE_BUCKETS),
        "distributions": build_distributions(rows, quote_key),
    }
    analysis = {
        "historical_matches": len({row["match_id"] for row in historical}),
        "train_matches": len({row["match_id"] for row in train}),
        "test_matches": len({row["match_id"] for row in test}),
        "evaluation": evaluation,
        "interpretation": (
            "Une cross_entropy plus faible est meilleure. top_score_accuracy mesure "
            "la capacité à prédire le score le plus saisi pour chaque issue."
        ),
        "model_preview": model["distributions"],
    }
    args.model.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    args.analysis.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


def load_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    rows = connection.execute(
        """
        SELECT sc.match_id, sc.predicted_outcome AS issue,
               sc.home_score, sc.away_score, sc.forecast_count,
               md.match_date,
               CASE sc.predicted_outcome
                   WHEN 'home' THEN md.home_quotation
                   WHEN 'draw' THEN md.draw_quotation
                   ELSE md.away_quotation
               END AS quotation,
               CASE sc.predicted_outcome
                   WHEN 'home' THEN md.home_bet_share
                   WHEN 'draw' THEN md.draw_bet_share
                   ELSE md.away_bet_share
               END AS community_share
        FROM score_counts sc
        JOIN match_metadata md USING (match_id)
        WHERE sc.contest_id = 'general'
          AND sc.home_score <= 10 AND sc.away_score <= 10
        """
    ).fetchall()
    return [
        {
            "match_id": row["match_id"],
            "issue": row["issue"],
            "score": f"{row['home_score']}-{row['away_score']}",
            "count": row["forecast_count"],
            "quotation": row["quotation"],
            "community_share": row["community_share"],
            "is_past": row["match_date"][:10] <= today,
        }
        for row in rows
        if row["quotation"] is not None and row["community_share"] is not None
    ]


def build_distributions(
    rows: list[dict[str, Any]],
    key_function: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    matches: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        key = key_function(row)
        grouped[key][row["score"]] += row["count"]
        matches[key].add(row["match_id"])
    result = {}
    for key, scores in sorted(grouped.items()):
        total = sum(scores.values())
        result[key] = {
            "matches": len(matches[key]),
            "forecasts": total,
            "scores": [
                {"score": score, "probability": round(count / total, 6), "forecasts": count}
                for score, count in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:12]
            ],
        }
    return result


def evaluate(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    key_function: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    issue_counts = _counts(train, lambda row: row["issue"])
    bucket_counts = _counts(train, key_function)
    test_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in test:
        test_groups[(row["match_id"], row["issue"])].append(row)
    cross_entropy = 0.0
    forecasts = 0
    top_correct = 0
    for (_, issue), rows in test_groups.items():
        key = key_function(rows[0])
        distribution = smoothed_distribution(bucket_counts.get(key, {}), issue_counts[issue])
        actual_top = max(rows, key=lambda row: row["count"])["score"]
        predicted_top = max(distribution, key=distribution.get)
        top_correct += int(actual_top == predicted_top)
        for row in rows:
            cross_entropy -= row["count"] * math.log(distribution.get(row["score"], 1e-8))
            forecasts += row["count"]
    return {
        "groups": len(test_groups),
        "forecasts": forecasts,
        "cross_entropy": round(cross_entropy / forecasts, 6),
        "top_score_accuracy": round(top_correct / len(test_groups), 6),
    }


def smoothed_distribution(bucket: dict[str, int], fallback: dict[str, int]) -> dict[str, float]:
    scores = set(bucket) | set(fallback)
    bucket_total = sum(bucket.values())
    fallback_total = sum(fallback.values())
    prior_weight = 100
    return {
        score: (bucket.get(score, 0) + prior_weight * fallback.get(score, 0) / fallback_total)
        / (bucket_total + prior_weight)
        for score in scores
    }


def _counts(
    rows: list[dict[str, Any]],
    key_function: Callable[[dict[str, Any]], str],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        result[key_function(row)][row["score"]] += row["count"]
    return result


def quote_key(row: dict[str, Any]) -> str:
    return f"{row['issue']}:{bucket_label(row['quotation'], QUOTE_BUCKETS)}"


def share_key(row: dict[str, Any]) -> str:
    return f"{row['issue']}:{bucket_label(row['community_share'], SHARE_BUCKETS)}"


def bucket_label(value: float, boundaries: tuple[float, ...]) -> str:
    for lower, upper in zip(boundaries, boundaries[1:]):
        if lower <= value < upper:
            return f"{lower:g}-{upper:g}"
    raise ValueError(value)


def split(match_id: str) -> str:
    return "test" if int(hashlib.sha256(match_id.encode()).hexdigest()[:8], 16) % 5 == 0 else "train"


if __name__ == "__main__":
    main()
