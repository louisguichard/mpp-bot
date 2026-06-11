#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mpp_optimizer.model import calibrate_poisson, outcome, score_matrix
from mpp_optimizer.odds_client import PolymarketClient
from rarity_tools import (
    ROOT,
    RARITY_BONUSES,
    historical_share,
    heuristic_shares,
    load_model,
    rarity_level,
)


DATABASE = ROOT / "data" / "mpp_history.sqlite3"
JSON_REPORT = ROOT / "docs" / "FRANCE_RARITY_COMPARISON.json"
MARKDOWN_REPORT = ROOT / "docs" / "FRANCE_RARITY_COMPARISON.md"
FRANCE_CLUB_ID = "mpp_championship_club_368"


def polymarket_events() -> list[dict]:
    payload, _, _ = PolymarketClient()._get(
        "/events/keyset",
        {"active": "true", "closed": "false", "limit": 100, "series_id": "11433"},
    )
    return payload["events"]


def probabilities(event: dict) -> dict[str, float]:
    home, away = event["title"].split(" vs. ", 1)
    result = {}
    for market in event["markets"]:
        if market.get("sportsMarketType") != "moneyline":
            continue
        label = market.get("groupItemTitle", "")
        key = "home" if label == home else "away" if label == away else "draw"
        bid, ask = float(market.get("bestBid") or 0), float(market.get("bestAsk") or 0)
        result[key] = (bid + ask) / 2 if bid and ask else float(json.loads(market["outcomePrices"])[0])
    total = sum(result.values())
    return {key: value / total for key, value in result.items()}


def best_by_outcome(matrix: dict, quotations: dict, model: dict, historical: bool) -> dict:
    heuristic = heuristic_shares(matrix)
    rows = []
    for score, probability in matrix.items():
        issue = outcome(*score)
        crowd_share = (
            historical_share(model, score, quotations[issue])
            if historical
            else heuristic[score]
        )
        if crowd_share is None:
            crowd_share = heuristic[score]
        level = rarity_level(crowd_share)
        bonus = RARITY_BONUSES[level]
        rows.append(
            {
                "score": f"{score[0]}-{score[1]}",
                "issue": issue,
                "score_probability": probability,
                "estimated_crowd_share": crowd_share,
                "rarity_level": level,
                "bonus": bonus,
                "exact_score_ev": probability * bonus,
            }
        )
    return {
        issue: max((row for row in rows if row["issue"] == issue), key=lambda row: row["exact_score_ev"])
        for issue in ("home", "draw", "away")
    }


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    matches = connection.execute(
        """
        SELECT * FROM match_metadata
        WHERE championship_id = '8' AND game_week_number <= 3
          AND (home_club_id = ? OR away_club_id = ?)
        ORDER BY match_date
        """,
        (FRANCE_CLUB_ID, FRANCE_CLUB_ID),
    ).fetchall()
    connection.close()
    events = {event["endDate"]: event for event in polymarket_events() if "France" in event["title"]}
    model = load_model()
    rows = []
    for match in matches:
        date = match["match_date"].replace(".000Z", "Z")
        event = events[date]
        market = probabilities(event)
        matrix = score_matrix(*calibrate_poisson(market), 8)
        quotations = {
            "home": match["home_quotation"],
            "draw": match["draw_quotation"],
            "away": match["away_quotation"],
        }
        rows.append(
            {
                "match": event["title"].replace(" vs. ", " - "),
                "date": date,
                "polymarket": market,
                "mpp_quotations": quotations,
                "old_heuristic": best_by_outcome(matrix, quotations, model, False),
                "new_historical": best_by_outcome(matrix, quotations, model, True),
            }
        )
    JSON_REPORT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# France : ancien vs nouveau modèle de rareté",
        "",
        "Le score affiché est celui qui maximise l'espérance du bonus exact au sein de chaque issue.",
        "",
    ]
    for row in rows:
        lines.extend([f"## {row['match']}", "", "| Issue | Ancien | Nouveau |", "|---|---:|---:|"])
        for issue in ("home", "draw", "away"):
            old, new = row["old_heuristic"][issue], row["new_historical"][issue]
            lines.append(
                f"| {issue} | {old['score']} · rareté {old['estimated_crowd_share']:.1%} · "
                f"+{old['bonus']} · EV exact {old['exact_score_ev']:.2f} | "
                f"{new['score']} · rareté {new['estimated_crowd_share']:.1%} · "
                f"+{new['bonus']} · EV exact {new['exact_score_ev']:.2f} |"
            )
        lines.append("")
    MARKDOWN_REPORT.write_text("\n".join(lines) + "\n")
    print(MARKDOWN_REPORT.read_text())


if __name__ == "__main__":
    main()
