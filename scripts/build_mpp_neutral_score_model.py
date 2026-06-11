#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from build_mpp_score_distribution_model import QUOTE_BUCKETS, bucket_label


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "mpp_history.sqlite3"
OUTPUT = ROOT / "data" / "mpp_neutral_score_distribution_model.json"


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        rows = load_rows(connection)
    finally:
        connection.close()
    model = build_model(rows)
    OUTPUT.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(model, ensure_ascii=False, indent=2))


def load_rows(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT sc.match_id, sc.predicted_outcome AS issue,
               sc.home_score, sc.away_score, sc.forecast_count, md.match_date,
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
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        totals[(row["match_id"], row["issue"])] += row["forecast_count"]
    today = date.today().isoformat()
    return [
        {
            "match_id": row["match_id"],
            "type": "draw" if row["issue"] == "draw" else "win",
            "side": row["issue"],
            "bucket": bucket_label(row["quotation"], QUOTE_BUCKETS),
            "relative_score": relative_score(row),
            "share": row["forecast_count"] / totals[(row["match_id"], row["issue"])],
            "is_historical": row["match_date"][:10] <= today,
        }
        for row in rows
    ]


def relative_score(row: sqlite3.Row) -> str:
    if row["issue"] == "away":
        return f"{row['away_score']}-{row['home_score']}"
    return f"{row['home_score']}-{row['away_score']}"


def build_model(rows: list[dict]) -> dict:
    historical = [row for row in rows if row["is_historical"]]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in historical:
        groups[(row["type"], row["bucket"])].append(row)
    distributions = {}
    for (prediction_type, bucket), group in sorted(groups.items()):
        match_sides = {(row["match_id"], row["side"]) for row in group}
        scores = {row["relative_score"] for row in group}
        score_shares = {}
        for score in scores:
            total = sum(
                row["share"] for row in group if row["relative_score"] == score
            )
            score_shares[score] = total / len(match_sides)
        distributions[f"{prediction_type}:{bucket}"] = {
            "match_issue_samples": len(match_sides),
            "home_samples": len({row["match_id"] for row in group if row["side"] == "home"}),
            "away_samples": len({row["match_id"] for row in group if row["side"] == "away"}),
            "scores": [
                {"relative_score": score, "probability": round(probability, 6)}
                for score, probability in sorted(
                    score_shares.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        }
    return {
        "description": (
            "Modèle pour terrain neutre. Les victoires équipe 1 et équipe 2 sont "
            "fusionnées après miroir du score, puis chaque match-issue reçoit le même poids."
        ),
        "usage": (
            "Pour une victoire de l'équipe 2, remiroiter le score relatif : "
            "2-1 devient 1-2 dans l'affichage MPP."
        ),
        "historical_matches": len({row["match_id"] for row in historical}),
        "quotation_buckets": list(QUOTE_BUCKETS),
        "distributions": distributions,
    }


if __name__ == "__main__":
    main()
