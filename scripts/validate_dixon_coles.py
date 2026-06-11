#!/usr/bin/env python3
"""Validate the Dixon-Coles rho against de-vigged Bet365 correct-score markets.

For each linked World Cup match, the Polymarket 1X2 is calibrated with each
candidate rho and the resulting score distribution is compared with the Bet365
correct-score probabilities (power de-vig), treated as truth like in
backtest_score_recommendations.py. Two metrics per rho:

- mean KL divergence between truth and model, on the scores Bet365 quotes;
- total real EV of the recommendation picked under the model, evaluated under
  truth with a bonus map kept identical across rhos.
"""
from __future__ import annotations

import json
from datetime import datetime
from math import log

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
from mpp_optimizer.model import calibrate_poisson, score_matrix
from rarity_tools import load_model

RHOS = (0.0, -0.05, -0.10, -0.15)
OUTPUT = ROOT / "docs" / "DIXON_COLES_VALIDATION.json"


def kl_divergence(truth: dict, model: dict) -> float:
    """KL(truth || model) restricted to quoted scores, model renormalized."""
    restricted = {score: model.get(score, 0.0) for score in truth}
    total = sum(restricted.values())
    result = 0.0
    for score, probability in truth.items():
        if probability <= 0:
            continue
        modeled = restricted[score] / total
        result += probability * log(probability / max(modeled, 1e-12))
    return result


def main() -> None:
    load_env()
    mpp_matches = load_mpp_matches()
    odds_events, odds_details = fetch_odds()
    poly_events = fetch_polymarket()
    linked = match_rows(mpp_matches, odds_events, poly_events)
    rarity_model = load_model()

    per_rho = {rho: {"kl": [], "real_ev": 0.0, "low_score_mass": []} for rho in RHOS}
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
        # The bonus map is computed once from the rho=0 matrix so the EV
        # comparison isolates the score model, not the rarity estimate.
        base_matrix = score_matrix(*calibrate_poisson(poly_1x2, 8, 0.0), 8, 0.0)
        bonuses = bonus_map(rarity_model, base_matrix, quotations, set(truth))
        for rho in RHOS:
            matrix = score_matrix(*calibrate_poisson(poly_1x2, 8, rho), 8, rho)
            per_rho[rho]["kl"].append(kl_divergence(truth, matrix))
            score, _ = recommendation(matrix, quotations, bonuses)
            per_rho[rho]["real_ev"] += evaluate(score, truth, quotations, bonuses)
            per_rho[rho]["low_score_mass"].append(
                matrix.get((0, 0), 0.0) + matrix.get((1, 1), 0.0)
            )

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "matches": matches_used,
        "method": (
            "Vérité = Bet365 Correct Score dévigé (méthode puissance). KL(truth||model) "
            "sur les scores cotés, et EV réelle totale de la recommandation, bonus de "
            "rareté identiques pour tous les rho."
        ),
        "results": {
            str(rho): {
                "mean_kl": round(sum(values["kl"]) / len(values["kl"]), 5),
                "total_real_ev": round(values["real_ev"], 2),
                "mean_low_score_draw_mass": round(
                    sum(values["low_score_mass"]) / len(values["low_score_mass"]), 4
                ),
            }
            for rho, values in per_rho.items()
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
