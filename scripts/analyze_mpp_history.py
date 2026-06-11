#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "mpp_history.sqlite3"
DEFAULT_REPORT = ROOT / "docs" / "HISTORICAL_RARITY_ANALYSIS.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse les pronostics historiques MPP agrégés.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--contest", default="general")
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        report = build_report(connection, args.contest)
    finally:
        connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def build_report(connection: sqlite3.Connection, contest_id: str = "general") -> dict[str, Any]:
    matches = connection.execute(
        """
        SELECT m.*, md.championship_id, md.season, md.game_week_number, md.match_date,
               md.home_club_id, md.away_club_id,
               md.home_quotation, md.draw_quotation, md.away_quotation,
               md.home_bet_share, md.draw_bet_share, md.away_bet_share
        FROM matches m
        LEFT JOIN match_metadata md USING (match_id)
        WHERE m.contest_id = ?
        ORDER BY md.match_date, m.match_id
        """,
        (contest_id,),
    ).fetchall()
    resolved = [row for row in matches if row["actual_home_score"] is not None]
    details = [_match_detail(connection, row) for row in resolved]
    checks = [
        detail["observed_bonus"] == bonus_for_share(detail["exact_share_within_outcome"])
        for detail in details
        if detail["observed_bonus"] is not None
    ]
    return {
        "contest_id": contest_id,
        "matches": len(matches),
        "resolved_matches": len(resolved),
        "forecasts": sum(row["forecast_count"] for row in matches),
        "bonus_rule_consistent_with_sample": bool(checks) and all(checks),
        "important_finding": (
            "MPP calcule la rareté du score exact parmi les joueurs ayant choisi "
            "la bonne issue, et non parmi tous les joueurs."
        ),
        "sampling_warning": (
            "La scoresheet générale expose environ 100 pronostics alors que MPP "
            "compte plus de 200 000 joueurs. Le bonus observé est exact, mais la "
            "distribution détaillée des scores est un échantillon probablement biaisé."
        ),
        "matches_detail": details,
    }


def bonus_for_share(share: float) -> int:
    if share < 0.005:
        return 100
    if share < 0.05:
        return 70
    if share < 0.20:
        return 50
    if share <= 0.30:
        return 30
    return 20


def _match_detail(connection: sqlite3.Connection, match: sqlite3.Row) -> dict[str, Any]:
    score_rows = connection.execute(
        """
        SELECT * FROM score_counts
        WHERE match_id = ? AND contest_id = ?
        ORDER BY predicted_outcome, forecast_count DESC, home_score, away_score
        """,
        (match["match_id"], match["contest_id"]),
    ).fetchall()
    by_outcome: dict[str, list[dict[str, Any]]] = {"home": [], "draw": [], "away": []}
    for row in score_rows:
        by_outcome[row["predicted_outcome"]].append(
            {
                "score": f"{row['home_score']}-{row['away_score']}",
                "forecasts": row["forecast_count"],
                "share_within_outcome": round(row["share_within_outcome"], 6),
                "is_actual_score": bool(row["is_actual_score"]),
            }
        )
    concentrations = {}
    for issue, scores in by_outcome.items():
        concentrations[issue] = {
            "distinct_scores": len(scores),
            "top_score": scores[0] if scores else None,
            "top_3_scores": scores[:3],
            "hhi": round(sum(score["share_within_outcome"] ** 2 for score in scores), 6),
        }
    sample_outcome_counts = {
        issue: sum(score["forecasts"] for score in scores)
        for issue, scores in by_outcome.items()
    }
    sample_outcome_shares = {
        issue: round(count / match["forecast_count"], 6)
        for issue, count in sample_outcome_counts.items()
    }
    mpp_bet_shares = {
        "home": match["home_bet_share"],
        "draw": match["draw_bet_share"],
        "away": match["away_bet_share"],
    }
    deltas = [
        abs(sample_outcome_shares[issue] - mpp_bet_shares[issue])
        for issue in ("home", "draw", "away")
        if mpp_bet_shares[issue] is not None
    ]
    return {
        "match_id": match["match_id"],
        "championship_id": match["championship_id"],
        "date": match["match_date"],
        "actual_score": f"{match['actual_home_score']}-{match['actual_away_score']}",
        "actual_outcome": match["actual_outcome"],
        "forecasts": match["forecast_count"],
        "correct_outcome_forecasts": match["correct_outcome_count"],
        "exact_forecasts": match["exact_count"],
        "exact_share_all": round(match["exact_share_all"], 6),
        "exact_share_within_outcome": round(match["exact_share_within_outcome"], 6),
        "observed_rarity_level": match["rarity_level"],
        "observed_bonus": match["extra_bonus"],
        "expected_bonus_from_conditional_share": bonus_for_share(match["exact_share_within_outcome"]),
        "mpp_quotations": {
            "home": match["home_quotation"],
            "draw": match["draw_quotation"],
            "away": match["away_quotation"],
        },
        "mpp_bet_shares": mpp_bet_shares,
        "sample_outcome_shares": sample_outcome_shares,
        "max_abs_sample_vs_mpp_share_delta": round(max(deltas), 6) if deltas else None,
        "score_concentration_by_outcome": concentrations,
    }


if __name__ == "__main__":
    main()
