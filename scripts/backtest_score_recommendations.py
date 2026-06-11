#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from analyze_score_models import correct_score_markets
from mpp_optimizer.model import calibrate_poisson, outcome, outcome_probabilities, score_matrix
from mpp_optimizer.odds_client import OddsApiIoClient, PolymarketClient
from rarity_tools import ROOT, RARITY_BONUSES, historical_share, heuristic_shares, load_model, rarity_level


DATABASE = ROOT / "data" / "mpp_history.sqlite3"
REPORT = ROOT / "docs" / "SCORE_RECOMMENDATION_BACKTEST.json"
ALIASES = {
    "bosnia and herzegovina": "bosnia",
    "bosnia herzegovina": "bosnia",
    "bosnie herzegovine": "bosnia",
    "cabo verde": "cape verde",
    "congo dr": "dr congo",
    "cote d ivoire": "ivory coast",
    "ir iran": "iran",
    "korea republic": "south korea",
    "united states": "usa",
}


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def canonical(value: str) -> str:
    value = "".join(
        character
        for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    )
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return ALIASES.get(value, value)


def as_date(value: str) -> str:
    return value.replace(".000Z", "Z")


def load_mpp_matches() -> list[dict]:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT * FROM match_metadata
        WHERE championship_id = '8' AND game_week_number <= 3
        ORDER BY match_date, match_id
        """
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def fetch_odds() -> tuple[list[dict], dict[str, dict]]:
    client = OddsApiIoClient()
    events, _, _ = client._get(
        "/events",
        {
            "apiKey": client.api_key,
            "sport": "football",
            "league": "international-fifa-world-cup",
            "status": "pending",
            "limit": 100,
        },
    )
    details = {}
    for offset in range(0, len(events), 10):
        ids = ",".join(str(event["id"]) for event in events[offset : offset + 10])
        batch, _, _ = client._get(
            "/odds/multi",
            {"apiKey": client.api_key, "eventIds": ids, "bookmakers": "Bet365"},
        )
        if isinstance(batch, dict):
            batch = batch.get("response") or batch.get("events") or list(batch.values())
        details.update({str(row["id"]): row for row in batch if isinstance(row, dict)})
    return events, details


def fetch_polymarket() -> list[dict]:
    payload, _, _ = PolymarketClient()._get(
        "/events/keyset",
        {"active": "true", "closed": "false", "limit": 100, "series_id": "11433"},
    )
    return payload["events"]


def polymarket_probabilities(event: dict) -> dict[str, float]:
    home, away = event["title"].split(" vs. ", 1)
    values = {}
    for market in event["markets"]:
        if market.get("sportsMarketType") != "moneyline":
            continue
        label = market.get("groupItemTitle", "")
        key = "home" if label == home else "away" if label == away else "draw"
        bid, ask = float(market.get("bestBid") or 0), float(market.get("bestAsk") or 0)
        values[key] = (bid + ask) / 2 if bid and ask else float(json.loads(market["outcomePrices"])[0])
    total = sum(values.values())
    return {key: value / total for key, value in values.items()}


def build_club_map(mpp_matches: list[dict], odds_events: list[dict]) -> dict[str, str]:
    mpp_by_date, odds_by_date = defaultdict(list), defaultdict(list)
    for match in mpp_matches:
        mpp_by_date[as_date(match["match_date"])].append(match)
    for event in odds_events:
        odds_by_date[event["date"]].append(event)
    club_map = {}
    for date, matches in mpp_by_date.items():
        events = odds_by_date[date]
        if len(matches) == len(events) == 1:
            club_map[matches[0]["home_club_id"]] = events[0]["home"]
            club_map[matches[0]["away_club_id"]] = events[0]["away"]
    changed = True
    while changed:
        changed = False
        for date, matches in mpp_by_date.items():
            events = odds_by_date[date]
            for match in matches:
                scores = []
                for event in events:
                    score = int(club_map.get(match["home_club_id"]) == event["home"])
                    score += int(club_map.get(match["away_club_id"]) == event["away"])
                    scores.append((score, event))
                scores.sort(key=lambda item: item[0], reverse=True)
                if scores and scores[0][0] > 0 and (len(scores) == 1 or scores[0][0] > scores[1][0]):
                    event = scores[0][1]
                    for club_id, team in (
                        (match["home_club_id"], event["home"]),
                        (match["away_club_id"], event["away"]),
                    ):
                        if club_id not in club_map:
                            club_map[club_id] = team
                            changed = True
    return club_map


def match_rows(mpp_matches: list[dict], odds_events: list[dict], poly_events: list[dict]) -> list[tuple]:
    club_map = build_club_map(mpp_matches, odds_events)
    odds_index = {
        (event["date"], canonical(event["home"]), canonical(event["away"])): event
        for event in odds_events
    }
    poly_index = {}
    for event in poly_events:
        home, away = event["title"].split(" vs. ", 1)
        poly_index[(event["endDate"], canonical(home), canonical(away))] = event
    rows = []
    for match in mpp_matches:
        home, away = club_map.get(match["home_club_id"]), club_map.get(match["away_club_id"])
        if not home or not away:
            continue
        key = (as_date(match["match_date"]), canonical(home), canonical(away))
        if key in odds_index and key in poly_index:
            rows.append((match, odds_index[key], poly_index[key]))
    return rows


def bonus_map(model: dict, matrix: dict, quotations: dict, scores: set[tuple[int, int]]) -> dict:
    fallback = heuristic_shares(matrix)
    result = {}
    for score in scores:
        issue = outcome(*score)
        share = historical_share(model, score, quotations[issue])
        if share is None:
            share = fallback.get(score, 0)
        result[score] = RARITY_BONUSES[rarity_level(share)]
    return result


def recommendation(matrix: dict, quotations: dict, bonuses: dict) -> tuple[tuple[int, int], float]:
    outcomes = outcome_probabilities(matrix)
    candidates = {
        score: outcomes[outcome(*score)] * quotations[outcome(*score)] + matrix.get(score, 0) * bonus
        for score, bonus in bonuses.items()
    }
    score = max(candidates, key=candidates.get)
    return score, candidates[score]


def evaluate(score: tuple[int, int], truth: dict, quotations: dict, bonuses: dict) -> float:
    outcomes = outcome_probabilities(truth)
    return outcomes[outcome(*score)] * quotations[outcome(*score)] + truth.get(score, 0) * bonuses[score]


def main() -> None:
    load_env()
    mpp_matches = load_mpp_matches()
    odds_events, odds_details = fetch_odds()
    poly_events = fetch_polymarket()
    linked = match_rows(mpp_matches, odds_events, poly_events)
    model = load_model()
    results = []
    for mpp, event, poly_event in linked:
        markets = correct_score_markets(odds_details.get(str(event["id"]), {}))
        if not markets:
            continue
        _, truth = markets
        poly_1x2 = polymarket_probabilities(poly_event)
        poly_matrix = score_matrix(*calibrate_poisson(poly_1x2), 8)
        quotations = {
            "home": mpp["home_quotation"],
            "draw": mpp["draw_quotation"],
            "away": mpp["away_quotation"],
        }
        bonuses = bonus_map(model, poly_matrix, quotations, set(truth))
        poly_score, poly_estimated = recommendation(poly_matrix, quotations, bonuses)
        odds_score, odds_estimated = recommendation(truth, quotations, bonuses)
        poly_real = evaluate(poly_score, truth, quotations, bonuses)
        odds_real = evaluate(odds_score, truth, quotations, bonuses)
        results.append(
            {
                "match": f"{event['home']} - {event['away']}",
                "date": event["date"],
                "polymarket_poisson_score": f"{poly_score[0]}-{poly_score[1]}",
                "exact_odds_score": f"{odds_score[0]}-{odds_score[1]}",
                "same_recommendation": poly_score == odds_score,
                "polymarket_estimated_ev": round(poly_estimated, 4),
                "polymarket_real_ev_under_odds": round(poly_real, 4),
                "exact_odds_real_ev": round(odds_real, 4),
                "regret": round(odds_real - poly_real, 4),
            }
        )
    total_poly = sum(row["polymarket_real_ev_under_odds"] for row in results)
    total_odds = sum(row["exact_odds_real_ev"] for row in results)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "method": (
            "Les probabilités Bet365 Correct Score, dévigées par méthode puissance, sont traitées "
            "comme vérité. Chaque méthode choisit le score maximisant base MPP + bonus de rareté "
            "historique; les deux choix sont ensuite évalués sous Bet365."
        ),
        "caveat": "Le marché Correct Score est renormalisé sur les scores explicitement cotés.",
        "coverage": {
            "mpp_group_matches": len(mpp_matches),
            "linked_mpp_odds_polymarket": len(linked),
            "with_bet365_correct_score": len(results),
        },
        "summary": {
            "same_recommendation_rate": round(mean(row["same_recommendation"] for row in results), 4),
            "polymarket_poisson_total_real_ev": round(total_poly, 2),
            "exact_odds_total_real_ev": round(total_odds, 2),
            "difference_total": round(total_odds - total_poly, 2),
            "difference_per_match": round((total_odds - total_poly) / len(results), 3),
            "relative_improvement": round((total_odds / total_poly - 1), 4),
        },
        "france": [row for row in results if "France" in row["match"]],
        "matches": results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**report, "matches": f"{len(results)} rows written to {REPORT}"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
