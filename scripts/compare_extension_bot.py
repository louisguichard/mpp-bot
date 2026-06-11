"""Compare bot vs extension recommendations on live data for every open match.

The two implementations share the Polymarket extraction and the supervised
rarity model; the only computational difference is the Poisson calibration
grid (bot: 0.10/0.02/0.005 capped at 4.0 — extension: 0.15/0.03/0.01 capped
at 4.5). This script recomputes both on the same live snapshot to isolate
exactly which matches flip and why.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mpp_optimizer.matching import link_matches, mpp_match_references
from mpp_optimizer.model import score_matrix, outcome_probabilities
from mpp_optimizer.mpp_client import MppClient
from mpp_optimizer.odds_client import PolymarketClient, normalize_polymarket, polymarket_1x2
from mpp_optimizer.rarity import SupervisedRarityModel, recommend_scores
from mpp_optimizer.auth import MppTokenManager, token_store_from_environment


def calibrate_extension(target: dict[str, float], max_goals: int = 8) -> tuple[float, float]:
    """Replicate extension/background.js calibratePoisson exactly."""
    best = {"home": 1.4, "away": 1.1, "loss": float("inf")}
    for step, radius in ((0.15, None), (0.03, 0.24), (0.01, 0.05)):
        home_start = 0.15 if radius is None else max(0.05, best["home"] - radius)
        home_end = 4.5 if radius is None else best["home"] + radius
        away_start = 0.15 if radius is None else max(0.05, best["away"] - radius)
        away_end = 4.5 if radius is None else best["away"] + radius
        home = home_start
        while home <= home_end + 1e-9:
            away = away_start
            while away <= away_end + 1e-9:
                probabilities = outcome_probabilities(score_matrix(home, away, max_goals, rho=0.0))
                loss = sum((probabilities[key] - target[key]) ** 2 for key in ("home", "draw", "away"))
                if loss < best["loss"]:
                    best = {"home": home, "away": away, "loss": loss}
                away += step
            home += step
    return best["home"], best["away"]


def best_extension_score(
    probabilities: dict[str, float],
    quotations: dict[str, float],
    bets: dict[str, float],
    model: SupervisedRarityModel,
    max_goals: int = 8,
) -> tuple[str, float, tuple[float, float]]:
    """Replicate the extension ranking: ev = P(issue)*quotation + P(score)*E[bonus]."""
    home_xg, away_xg = calibrate_extension(probabilities, max_goals)
    matrix = score_matrix(home_xg, away_xg, max_goals, rho=0.0)
    best_label, best_ev = None, -1.0
    for (home_score, away_score), score_probability in matrix.items():
        issue = "home" if home_score > away_score else "away" if home_score < away_score else "draw"
        _, expected_bonus = model.predict(
            kind="draw" if issue == "draw" else "win",
            winner_goals=max(home_score, away_score),
            loser_goals=min(home_score, away_score),
            quotation=float(quotations[issue]),
            bet_share=float(bets[issue]),
        )
        ev = float(probabilities[issue]) * float(quotations[issue]) + score_probability * expected_bonus
        if ev > best_ev:
            best_label, best_ev = f"{home_score}-{away_score}", ev
    return best_label, best_ev, (home_xg, away_xg)


def main() -> None:
    token = MppTokenManager(token_store_from_environment()).access_token()
    mpp = MppClient(token=token, allow_write=False)
    matches_payload = mpp.get_current_matches()
    matches = list(matches_payload.values()) if isinstance(matches_payload, dict) else list(matches_payload)
    clubs_payload = mpp.get_clubs()
    clubs = clubs_payload.get("championshipClubs", clubs_payload)
    raw_events = PolymarketClient().events()
    normalized = [
        normalized_event
        for event in raw_events
        if (normalized_event := normalize_polymarket(event)).has_1x2
    ]
    raw_by_id = {str(event.get("id", "")): event for event in raw_events}
    references = mpp_match_references(matches, clubs)
    links = {link.mpp_match_id: link for link in link_matches(references, normalized)}
    matches_by_id = {str(match.get("matchId", "")): match for match in matches}
    model = SupervisedRarityModel.load()
    now = datetime.now(UTC)

    differences = 0
    for reference in references:
        starts_at = datetime.fromisoformat(reference.starts_at.replace("Z", "+00:00"))
        if starts_at <= now:
            continue
        link = links.get(reference.match_id)
        if not link or link.confidence < 0.90:
            continue
        match = matches_by_id[reference.match_id]
        probabilities = polymarket_1x2(raw_by_id[link.provider_event_id])
        if link.reversed_teams:
            probabilities["home"], probabilities["away"] = probabilities["away"], probabilities["home"]
        quotations = match["quotations"]
        bets = match["stats"]["bets"]

        bot_best = recommend_scores(probabilities, quotations, bets, model)[0]
        bot_label = f"{bot_best.home_score}-{bot_best.away_score}"
        ext_label, ext_ev, ext_xg = best_extension_score(probabilities, quotations, bets, model)

        saved = match.get("forecast") or {}
        saved_label = (
            f"{saved.get('homeScore')}-{saved.get('awayScore')}"
            if saved.get("homeScore") is not None
            else "—"
        )
        marker = "  DIFF" if bot_label != ext_label else ""
        stale = "  STALE-SAVED" if saved_label not in ("—", bot_label) else ""
        if marker or stale:
            differences += 1
            print(
                f"{reference.home_team} – {reference.away_team}: "
                f"bot={bot_label} (EV {bot_best.expected_points:.2f}) "
                f"ext={ext_label} (EV {ext_ev:.2f}) saved={saved_label}{marker}{stale}"
            )
            print(
                f"    probs h/d/a = {probabilities['home']:.3f}/{probabilities['draw']:.3f}/{probabilities['away']:.3f}"
                f"  ext xg = {ext_xg[0]:.2f}/{ext_xg[1]:.2f}"
            )
    if not differences:
        print("Aucune différence bot/extension/sauvegardé sur les matchs ouverts.")


if __name__ == "__main__":
    main()
