from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial


OUTCOMES = ("home", "draw", "away")
RARITY_BONUSES = {1: 20.0, 2: 30.0, 3: 50.0, 4: 70.0, 5: 100.0}
CROWD_GOAL_BIAS = 0.55
EXTRA_TIME_SAMPLE_SIZE = 54
EXTRA_TIME_STILL_DRAW = 34 / EXTRA_TIME_SAMPLE_SIZE
EXTRA_TIME_DECIDED = 20 / EXTRA_TIME_SAMPLE_SIZE
EXTRA_TIME_DRAW_DELTAS = {
    (0, 0): 30 / 34,
    (1, 1): 4 / 34,
}
EXTRA_TIME_WIN_DELTAS = {
    (1, 0): 14 / 20,
    (2, 0): 2 / 20,
    (2, 1): 4 / 20,
}
# Dixon-Coles low-score correlation. Tested against de-vigged Bet365
# correct-score markets on the 72 World Cup group matches
# (docs/DIXON_COLES_VALIDATION.json): once the 1X2 is recalibrated, every
# negative rho lowered the real EV of the recommendations, so the correction
# stays available but disabled.
DIXON_COLES_RHO = 0.0


@dataclass(frozen=True)
class MatchInput:
    home_team: str
    away_team: str
    bookmaker_odds: dict[str, float]
    mpp_quotations: dict[str, float]
    mpp_crowd: dict[str, float] | None = None
    exact_score_probabilities: dict[str, float] | None = None
    mpp_score_crowd: dict[str, float] | None = None
    exact_bonus: float = 20.0
    max_goals: int = 8
    knockout_120: bool = False


@dataclass(frozen=True)
class ScoreRecommendation:
    home_score: int
    away_score: int
    outcome: str
    score_probability: float
    outcome_probability: float
    expected_points: float
    expected_base_points: float
    expected_exact_bonus: float
    rarity_level: int | None
    exact_bonus_if_hit: float
    market_edge_vs_crowd: float | None


def remove_vig(odds: dict[str, float]) -> dict[str, float]:
    _require_outcomes(odds, "bookmaker_odds")
    if any(value <= 1 for value in odds.values()):
        raise ValueError("Decimal bookmaker odds must all be greater than 1.")
    raw = {outcome: 1 / odds[outcome] for outcome in OUTCOMES}
    total = sum(raw.values())
    return {outcome: raw[outcome] / total for outcome in OUTCOMES}


def outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def poisson_probability(goals: int, expected_goals: float) -> float:
    return exp(-expected_goals) * expected_goals**goals / factorial(goals)


def score_matrix(
    home_xg: float,
    away_xg: float,
    max_goals: int,
    rho: float = DIXON_COLES_RHO,
) -> dict[tuple[int, int], float]:
    matrix = {
        (home, away): poisson_probability(home, home_xg)
        * poisson_probability(away, away_xg)
        for home in range(max_goals + 1)
        for away in range(max_goals + 1)
    }
    if rho:
        matrix[(0, 0)] *= max(0.0, 1 - home_xg * away_xg * rho)
        matrix[(0, 1)] *= max(0.0, 1 + home_xg * rho)
        matrix[(1, 0)] *= max(0.0, 1 + away_xg * rho)
        matrix[(1, 1)] *= max(0.0, 1 - rho)
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}


def outcome_probabilities(
    matrix: dict[tuple[int, int], float],
) -> dict[str, float]:
    result = {key: 0.0 for key in OUTCOMES}
    for (home, away), probability in matrix.items():
        result[outcome(home, away)] += probability
    return result


def extra_time_delta_distribution(
    probabilities: dict[str, float],
) -> dict[tuple[int, int], float]:
    """Model the 30 extra-time minutes when a knockout match is level at 90'.

    Shape is estimated from men's World Cup knockout matches from 1986-2022.
    The decided share is tilted using the 90-minute home/away probabilities so
    the favorite gets more of the transferred draw mass.
    """
    denominator = float(probabilities["home"]) + float(probabilities["away"])
    home_share = float(probabilities["home"]) / denominator if denominator > 0 else 0.5
    away_share = 1 - home_share
    deltas = {
        delta: EXTRA_TIME_STILL_DRAW * share
        for delta, share in EXTRA_TIME_DRAW_DELTAS.items()
    }
    for (winner_goals, loser_goals), share in EXTRA_TIME_WIN_DELTAS.items():
        deltas[(winner_goals, loser_goals)] = (
            EXTRA_TIME_DECIDED * home_share * share
        )
        deltas[(loser_goals, winner_goals)] = (
            EXTRA_TIME_DECIDED * away_share * share
        )
    return deltas


def apply_knockout_extra_time(
    matrix: dict[tuple[int, int], float],
    probabilities: dict[str, float],
) -> dict[tuple[int, int], float]:
    """Convert a 90-minute score matrix into MPP's 120-minute knockout scoring."""
    deltas = extra_time_delta_distribution(probabilities)
    converted: dict[tuple[int, int], float] = {}
    for (home, away), probability in matrix.items():
        if home != away:
            converted[(home, away)] = converted.get((home, away), 0.0) + probability
            continue
        for (extra_home, extra_away), extra_probability in deltas.items():
            score = (home + extra_home, away + extra_away)
            converted[score] = converted.get(score, 0.0) + probability * extra_probability
    return converted


def estimate_score_crowd(
    matrix: dict[tuple[int, int], float], alpha: float = 2.0
) -> dict[str, float]:
    """Estimate score shares among players who selected the same outcome."""
    if alpha <= 0:
        raise ValueError("Crowd concentration alpha must be greater than zero.")
    totals = outcome_probabilities(matrix)
    conditional = {
        score: probability / totals[outcome(*score)]
        for score, probability in matrix.items()
    }
    weights = {
        score: _crowd_weight(score, probability, alpha)
        for score, probability in conditional.items()
    }
    denominators = {key: 0.0 for key in OUTCOMES}
    for (home, away), weight in weights.items():
        denominators[outcome(home, away)] += weight
    return {
        f"{home}-{away}": weight / denominators[outcome(home, away)]
        for (home, away), weight in weights.items()
    }


def _crowd_weight(
    score: tuple[int, int], conditional_probability: float, alpha: float
) -> float:
    home, away = score
    simple_result_boost = 1.25 if abs(home - away) == 1 else 1.0
    return (
        conditional_probability**alpha
        * exp(-CROWD_GOAL_BIAS * (home + away))
        * simple_result_boost
    )


def calibrate_poisson(
    target: dict[str, float], max_goals: int = 8, rho: float = DIXON_COLES_RHO
) -> tuple[float, float]:
    """Fit Dixon-Coles-adjusted Poisson goal rates to market 1X2 probabilities."""
    best = (1.4, 1.1)
    best_loss = float("inf")

    for step, radius in ((0.10, None), (0.02, 0.30), (0.005, 0.08)):
        if radius is None:
            # The 4.0 cap is a useful regularizer for lopsided fixtures: a
            # wider grid fits the 1X2 marginally better but drifts to goal
            # totals the correct-score market rejects (docs/XG_GRID_VALIDATION.json).
            home_values = _float_range(0.2, 4.0, step)
            away_values = _float_range(0.2, 4.0, step)
        else:
            home_values = _float_range(max(0.05, best[0] - radius), best[0] + radius, step)
            away_values = _float_range(max(0.05, best[1] - radius), best[1] + radius, step)

        for home_xg in home_values:
            for away_xg in away_values:
                probabilities = outcome_probabilities(
                    score_matrix(home_xg, away_xg, max_goals, rho)
                )
                loss = sum(
                    (probabilities[key] - target[key]) ** 2 for key in OUTCOMES
                )
                if loss < best_loss:
                    best_loss = loss
                    best = (home_xg, away_xg)
    return best


def optimize(match: MatchInput) -> list[ScoreRecommendation]:
    _require_outcomes(match.mpp_quotations, "mpp_quotations")
    market = remove_vig(match.bookmaker_odds)
    home_xg, away_xg = calibrate_poisson(market, match.max_goals)
    matrix = score_matrix(home_xg, away_xg, match.max_goals)
    if match.exact_score_probabilities:
        matrix = normalize_score_probabilities(match.exact_score_probabilities, match.max_goals)
    if match.knockout_120:
        matrix = apply_knockout_extra_time(matrix, market)
    modeled_outcomes = outcome_probabilities(matrix)
    score_crowd = match.mpp_score_crowd or estimate_score_crowd(matrix)

    recommendations = []
    for (home_score, away_score), score_probability in matrix.items():
        predicted_outcome = outcome(home_score, away_score)
        outcome_probability = modeled_outcomes[predicted_outcome]
        expected_base = outcome_probability * match.mpp_quotations[predicted_outcome]
        score_key = f"{home_score}-{away_score}"
        rarity_level = None
        exact_bonus = match.exact_bonus
        if score_key in score_crowd:
            rarity_level = rarity_level_from_share(score_crowd[score_key])
            exact_bonus = RARITY_BONUSES[rarity_level]
        expected_exact = score_probability * exact_bonus
        crowd_edge = None
        if match.mpp_crowd:
            crowd_edge = market[predicted_outcome] - match.mpp_crowd[predicted_outcome]
        recommendations.append(
            ScoreRecommendation(
                home_score=home_score,
                away_score=away_score,
                outcome=predicted_outcome,
                score_probability=score_probability,
                outcome_probability=outcome_probability,
                expected_points=expected_base + expected_exact,
                expected_base_points=expected_base,
                expected_exact_bonus=expected_exact,
                rarity_level=rarity_level,
                exact_bonus_if_hit=exact_bonus,
                market_edge_vs_crowd=crowd_edge,
            )
        )
    return sorted(recommendations, key=lambda item: item.expected_points, reverse=True)


def exact_score_probabilities_from_odds(odds: dict[str, float]) -> dict[str, float]:
    """Remove correct-score margin with a power method suited to long odds."""
    if not odds or any(value <= 1 for value in odds.values()):
        raise ValueError("Correct-score decimal odds must all be greater than 1.")
    implied = {score: 1 / value for score, value in odds.items()}
    total = sum(implied.values())
    if total <= 1:
        return {score: probability / total for score, probability in implied.items()}
    low, high = 1.0, 4.0
    for _ in range(60):
        exponent = (low + high) / 2
        if sum(probability**exponent for probability in implied.values()) > 1:
            low = exponent
        else:
            high = exponent
    exponent = (low + high) / 2
    return {score: probability**exponent for score, probability in implied.items()}


def normalize_score_probabilities(
    probabilities: dict[str, float], max_goals: int
) -> dict[tuple[int, int], float]:
    parsed: dict[tuple[int, int], float] = {}
    for score, probability in probabilities.items():
        home, away = (int(value) for value in score.split("-", 1))
        if home <= max_goals and away <= max_goals:
            parsed[(home, away)] = probability
    total = sum(parsed.values())
    if total <= 0:
        raise ValueError("No usable exact-score probabilities.")
    return {score: probability / total for score, probability in parsed.items()}


def rarity_level_from_share(share: float) -> int:
    """MPP rarity bands found in the web bundle. Share is between 0 and 1."""
    if share < 0 or share > 1:
        raise ValueError("MPP score crowd share must be between 0 and 1.")
    if share < 0.005:
        return 5
    if share < 0.05:
        return 4
    if share < 0.20:
        return 3
    if share <= 0.30:
        return 2
    return 1


def _require_outcomes(values: dict[str, float], name: str) -> None:
    missing = set(OUTCOMES) - values.keys()
    if missing:
        raise ValueError(f"{name} is missing: {', '.join(sorted(missing))}")


def _float_range(start: float, stop: float, step: float) -> list[float]:
    count = int(round((stop - start) / step))
    return [round(start + index * step, 6) for index in range(count + 1)]
