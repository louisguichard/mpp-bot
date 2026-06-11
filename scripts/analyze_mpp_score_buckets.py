#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from build_mpp_score_distribution_model import QUOTE_BUCKETS, bucket_label


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "mpp_history.sqlite3"
CSV_OUTPUT = ROOT / "docs" / "MPP_SCORE_BUCKETS_COMPLETE.csv"
MARKDOWN_OUTPUT = ROOT / "docs" / "MPP_SCORE_BUCKETS_COMPLETE.md"


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        rows = load_rows(connection)
    finally:
        connection.close()
    analysis = analyze(rows)
    write_csv(analysis)
    write_markdown(analysis)
    print(f"{len(analysis)} lignes écrites dans {CSV_OUTPUT}")


def load_rows(connection: sqlite3.Connection) -> list[dict]:
    today = date.today().isoformat()
    rows = connection.execute(
        """
        SELECT sc.match_id, md.championship_id, sc.predicted_outcome AS issue,
               sc.home_score, sc.away_score, sc.forecast_count,
               CASE sc.predicted_outcome
                   WHEN 'home' THEN md.home_quotation
                   WHEN 'draw' THEN md.draw_quotation
                   ELSE md.away_quotation
               END AS quotation
        FROM score_counts sc
        JOIN match_metadata md USING (match_id)
        WHERE sc.contest_id = 'general'
          AND md.match_date <= ?
          AND sc.home_score <= 10 AND sc.away_score <= 10
        """,
        (today + "T23:59:59",),
    ).fetchall()
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        totals[(row["match_id"], row["issue"])] += row["forecast_count"]
    return [
        {
            "match_id": row["match_id"],
            "championship_id": row["championship_id"],
            "issue": row["issue"],
            "bucket": bucket_label(row["quotation"], QUOTE_BUCKETS),
            "score": f"{row['home_score']}-{row['away_score']}",
            "count": row["forecast_count"],
            "match_share": row["forecast_count"] / totals[(row["match_id"], row["issue"])],
        }
        for row in rows
    ]


def analyze(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["issue"], row["bucket"], "all", row["score"])].append(row)
        groups[(row["issue"], row["bucket"], str(row["championship_id"]), row["score"])].append(row)
    result = []
    for (issue, bucket, championship, score), score_rows in groups.items():
        relevant_matches = {
            row["match_id"]
            for row in rows
            if row["issue"] == issue
            and row["bucket"] == bucket
            and (championship == "all" or str(row["championship_id"]) == championship)
        }
        shares_by_match = {match_id: 0.0 for match_id in relevant_matches}
        for row in score_rows:
            shares_by_match[row["match_id"]] = row["match_share"]
        shares = list(shares_by_match.values())
        mean = sum(shares) / len(shares)
        variance = sum((value - mean) ** 2 for value in shares) / max(1, len(shares) - 1)
        margin = 1.96 * math.sqrt(variance / len(shares))
        all_rows = [
            row
            for row in rows
            if row["issue"] == issue
            and row["bucket"] == bucket
            and (championship == "all" or str(row["championship_id"]) == championship)
        ]
        pooled_total = sum(row["count"] for row in all_rows)
        pooled_score = sum(row["count"] for row in score_rows)
        result.append(
            {
                "issue": issue,
                "quotation_bucket": bucket,
                "championship_id": championship,
                "score": score,
                "matches": len(relevant_matches),
                "forecasts": pooled_total,
                "score_forecasts": pooled_score,
                "player_weighted_share": pooled_score / pooled_total,
                "match_weighted_share": mean,
                "ci95_low": max(0.0, mean - margin),
                "ci95_high": min(1.0, mean + margin),
            }
        )
    return sorted(
        result,
        key=lambda row: (
            row["championship_id"] != "all",
            row["issue"],
            bucket_sort(row["quotation_bucket"]),
            -row["match_weighted_share"],
            row["score"],
        ),
    )


def write_csv(rows: list[dict]) -> None:
    with CSV_OUTPUT.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict]) -> None:
    lines = [
        "# Distributions complètes des scores MPP par tranche",
        "",
        "Données : matchs terminés uniquement. `Part joueurs` pondère chaque pronostic ; "
        "`part moyenne/match` donne le même poids à chaque match. L'intervalle à 95 % "
        "mesure la variabilité entre matchs, pas l'incertitude sur la communauté MPP complète.",
        "",
    ]
    all_rows = [row for row in rows if row["championship_id"] == "all"]
    keys = list(dict.fromkeys((row["issue"], row["quotation_bucket"]) for row in all_rows))
    for issue, bucket in keys:
        bucket_rows = [
            row for row in all_rows if row["issue"] == issue and row["quotation_bucket"] == bucket
        ]
        lines.extend(
            [
                f"## {issue} · quotation {bucket}",
                "",
                f"{bucket_rows[0]['matches']} matchs, {bucket_rows[0]['forecasts']} pronostics visibles.",
                "",
                "| Score | Pronostics | Part joueurs | Part moyenne/match | IC 95 % entre matchs |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in bucket_rows:
            lines.append(
                f"| `{row['score']}` | {row['score_forecasts']} | "
                f"{row['player_weighted_share']:.1%} | {row['match_weighted_share']:.1%} | "
                f"{row['ci95_low']:.1%}–{row['ci95_high']:.1%} |"
            )
        lines.append("")
    MARKDOWN_OUTPUT.write_text("\n".join(lines) + "\n")


def bucket_sort(label: str) -> float:
    return float(label.split("-")[0])


if __name__ == "__main__":
    main()
