#!/usr/bin/env python3
"""Compare calibration grid caps (4.0 vs 6.0) under Bet365 correct-score truth.

Same protocol as validate_dixon_coles.py: Polymarket 1X2 calibrated with each
grid, score distribution compared with de-vigged Bet365 correct-score markets,
plus the real EV of the recommendation each grid would pick.
"""
from __future__ import annotations

import json
from datetime import datetime

from backtest_score_recommendations import (
    ROOT,
    bonus_map,
    evaluate,
    fetch_odds,
    fetch_polymarket,
    load_env,
    load_mpp_matches,
    match_rows,
    polymarket_probabilities,
    recommendation,
)
from analyze_score_models import correct_score_markets
from mpp_optimizer.model import (
    _float_range,
    outcome_probabilities,
    score_matrix,
)
from rarity_tools import load_model
from validate_dixon_coles import kl_divergence

CAPS = (4.0, 6.0)
OUTPUT = ROOT / "docs" / "XG_GRID_VALIDATION.json"


def calibrate_with_cap(target: dict[str, float], cap: float, max_goals: int = 8) -> tuple[float, float]:
    best = (1.4, 1.1)
    best_loss = float("inf")
    for step, radius in ((0.10, None), (0.02, 0.30), (0.005, 0.08)):
        if radius is None:
            home_values = _float_range(0.2, cap, step)
            away_values = _float_range(0.2, cap, step)
        else:
            home_values = _float_range(max(0.05, best[0] - radius), best[0] + radius, step)
            away_values = _float_range(max(0.05, best[1] - radius), best[1] + radius, step)
        for home_xg in home_values:
            for away_xg in away_values:
                probabilities = outcome_probabilities(score_matrix(home_xg, away_xg, max_goals, 0.0))
                loss = sum((probabilities[key] - target[key]) ** 2 for key in ("home", "draw", "away"))
                if loss < best_loss:
                    best_loss = loss
                    best = (home_xg, away_xg)
    return best


def main() -> None:
    load_env()
    mpp_matches = load_mpp_matches()
    odds_events, odds_details = fetch_odds()
    poly_events = fetch_polymarket()
    linked = match_rows(mpp_matches, odds_events, poly_events)
    rarity_model = load_model()

    per_cap = {cap: {"kl": [], "real_ev": 0.0, "saturated": 0, "changed": []} for cap in CAPS}
    matches_used = 0
    for mpp, event, poly_event in linked:
        markets = correct_score_markets(odds_details.get(str(event["id"]), {}))
        if not markets:
            continue
        _, truth = markets
        matches_used += 1
        poly_1x2 = polymarket_probabilities(poly_event)
        quotations = {
            "home": mpp["home_quotation"],
            "draw": mpp["draw_quotation"],
            "away": mpp["away_quotation"],
        }
        scores_by_cap = {}
        bonuses = None
        for cap in CAPS:
            home_xg, away_xg = calibrate_with_cap(poly_1x2, cap)
            matrix = score_matrix(home_xg, away_xg, 8, 0.0)
            if bonuses is None:
                bonuses = bonus_map(rarity_model, matrix, quotations, set(truth))
            per_cap[cap]["kl"].append(kl_divergence(truth, matrix))
            if max(home_xg, away_xg) > cap - 0.15:
                per_cap[cap]["saturated"] += 1
            score, _ = recommendation(matrix, quotations, bonuses)
            per_cap[cap]["real_ev"] += evaluate(score, truth, quotations, bonuses)
            scores_by_cap[cap] = score
        if len(set(scores_by_cap.values())) > 1:
            for cap in CAPS:
                per_cap[cap]["changed"].append(
                    f"{event['home']} - {event['away']}: {scores_by_cap[cap]}"
                )

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "matches": matches_used,
        "results": {
            str(cap): {
                "mean_kl": round(sum(values["kl"]) / len(values["kl"]), 5),
                "total_real_ev": round(values["real_ev"], 2),
                "saturated_fits": values["saturated"],
                "diverging_recommendations": values["changed"],
            }
            for cap, values in per_cap.items()
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
