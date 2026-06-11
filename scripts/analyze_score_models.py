#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from statistics import mean

from mpp_optimizer.model import calibrate_poisson, outcome, remove_vig, score_matrix
from mpp_optimizer.odds_client import OddsApiIoClient


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "SCORE_MODEL_ANALYSIS.json"


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def correct_score_markets(odds: dict, bookmaker: str = "Bet365") -> tuple[dict, dict] | None:
    for market in odds.get("bookmakers", {}).get(bookmaker, []):
        if market.get("name") != "Correct Score":
            continue
        implied = {}
        for item in market.get("odds", []):
            label = item.get("label", "")
            if "-" not in label:
                continue
            home, away = (int(value) for value in label.split("-", 1))
            price = float(item["odds"])
            implied[(home, away)] = 1 / price
        total = sum(implied.values())
        proportional = {score: probability / total for score, probability in implied.items()}
        low, high = 1.0, 4.0
        for _ in range(60):
            exponent = (low + high) / 2
            if sum(probability**exponent for probability in implied.values()) > 1:
                low = exponent
            else:
                high = exponent
        exponent = (low + high) / 2
        power = {score: probability**exponent for score, probability in implied.items()}
        return proportional, power
    return None


def moneyline_market(odds: dict, bookmaker: str = "Bet365") -> dict[str, float] | None:
    for market in odds.get("bookmakers", {}).get(bookmaker, []):
        if market.get("name") != "ML" or not market.get("odds"):
            continue
        row = market["odds"][0]
        if all(key in row for key in ("home", "draw", "away")):
            return remove_vig({key: float(row[key]) for key in ("home", "draw", "away")})
    return None


def normalized_on_market(
    model: dict[tuple[int, int], float], market: dict[tuple[int, int], float]
) -> dict[tuple[int, int], float]:
    comparable = {score: probability for score, probability in market.items() if model.get(score, 0) > 0}
    market_total = sum(comparable.values())
    model_total = sum(model[score] for score in comparable)
    return {
        score: model[score] / model_total
        for score in comparable
    }, {
        score: probability / market_total
        for score, probability in comparable.items()
    }


def corrected_model(
    matrix: dict[tuple[int, int], float],
    home_xg: float,
    away_xg: float,
    rho: float,
    goal_tilt: float,
) -> dict[tuple[int, int], float]:
    result = {}
    for (home, away), probability in matrix.items():
        tau = 1.0
        if (home, away) == (0, 0):
            tau = 1 - home_xg * away_xg * rho
        elif (home, away) == (0, 1):
            tau = 1 + home_xg * rho
        elif (home, away) == (1, 0):
            tau = 1 + away_xg * rho
        elif (home, away) == (1, 1):
            tau = 1 - rho
        result[(home, away)] = max(0.000001, probability * tau * math.exp(goal_tilt * (home + away)))
    original_outcomes = {"home": 0.0, "draw": 0.0, "away": 0.0}
    corrected_outcomes = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for score, probability in matrix.items():
        original_outcomes[outcome(*score)] += probability
    for score, probability in result.items():
        corrected_outcomes[outcome(*score)] += probability
    return {
        score: probability * original_outcomes[outcome(*score)] / corrected_outcomes[outcome(*score)]
        for score, probability in result.items()
    }


def js_divergence(left: dict, right: dict) -> float:
    keys = set(left) | set(right)
    middle = {key: (left.get(key, 0) + right.get(key, 0)) / 2 for key in keys}

    def kl(source: dict, target: dict) -> float:
        return sum(
            probability * math.log(probability / target[key])
            for key, probability in source.items()
            if probability > 0
        )

    return (kl(left, middle) + kl(right, middle)) / 2


def metrics(rows: list[dict], rho: float = 0.0, goal_tilt: float = 0.0) -> dict:
    per_match = []
    for row in rows:
        model = corrected_model(row["matrix"], row["home_xg"], row["away_xg"], rho, goal_tilt)
        model, market = normalized_on_market(model, row["market"])
        market_rank = sorted(market, key=market.get, reverse=True)
        model_rank = sorted(model, key=model.get, reverse=True)
        per_match.append(
            {
                "js": js_divergence(model, market),
                "mae": mean(abs(model[score] - market[score]) for score in market),
                "top1": market_rank[0] == model_rank[0],
                "top3_overlap": len(set(market_rank[:3]) & set(model_rank[:3])),
            }
        )
    return {
        "matches": len(rows),
        "js_mean": mean(item["js"] for item in per_match),
        "mae_mean": mean(item["mae"] for item in per_match),
        "top1_accuracy": mean(item["top1"] for item in per_match),
        "top3_overlap": mean(item["top3_overlap"] for item in per_match),
    }


def fit_parameters(rows: list[dict]) -> tuple[float, float]:
    candidates = []
    for rho_step in range(-20, 21, 2):
        for tilt_step in range(-20, 21, 2):
            rho = rho_step / 100
            tilt = tilt_step / 100
            candidates.append((metrics(rows, rho, tilt)["js_mean"], rho, tilt))
    return min(candidates)[1:]


def cross_validate(rows: list[dict], folds: int = 5) -> tuple[dict, list[tuple[float, float]]]:
    predictions = []
    parameters = []
    for fold in range(folds):
        training = [row for index, row in enumerate(rows) if index % folds != fold]
        validation = [row for index, row in enumerate(rows) if index % folds == fold]
        rho, tilt = fit_parameters(training)
        parameters.append((rho, tilt))
        for row in validation:
            model = corrected_model(row["matrix"], row["home_xg"], row["away_xg"], rho, tilt)
            model, market = normalized_on_market(model, row["market"])
            market_rank = sorted(market, key=market.get, reverse=True)
            model_rank = sorted(model, key=model.get, reverse=True)
            predictions.append(
                {
                    "js": js_divergence(model, market),
                    "mae": mean(abs(model[score] - market[score]) for score in market),
                    "top1": market_rank[0] == model_rank[0],
                    "top3_overlap": len(set(market_rank[:3]) & set(model_rank[:3])),
                }
            )
    return {
        "matches": len(predictions),
        "js_mean": mean(item["js"] for item in predictions),
        "mae_mean": mean(item["mae"] for item in predictions),
        "top1_accuracy": mean(item["top1"] for item in predictions),
        "top3_overlap": mean(item["top3_overlap"] for item in predictions),
    }, parameters


def score_biases(rows: list[dict]) -> list[dict]:
    totals: dict[str, list[float]] = {}
    for row in rows:
        model, market = normalized_on_market(row["matrix"], row["market"])
        for score, market_probability in market.items():
            home, away = score
            labels = [
                f"total_{min(home + away, 5)}{'+' if home + away >= 5 else ''}",
                "draw" if home == away else "one_goal_margin" if abs(home - away) == 1 else "wide_result",
                f"score_{home}-{away}" if home <= 3 and away <= 3 else "score_other",
            ]
            for label in labels:
                totals.setdefault(label, []).append(market_probability / model[score])
    return [
        {"category": label, "bookmaker_to_poisson_ratio": mean(values), "observations": len(values)}
        for label, values in sorted(totals.items())
        if len(values) >= 10
    ]


def main() -> None:
    load_env()
    client = OddsApiIoClient()
    if not client.api_key:
        raise SystemExit("ODDS_API_KEY absente.")
    selected, _, _ = client._get("/bookmakers/selected", {"apiKey": client.api_key})
    bookmakers = ",".join(selected.get("bookmakers", []))
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
    rows = []
    for offset in range(0, len(events), 10):
        ids = ",".join(str(event["id"]) for event in events[offset : offset + 10])
        batch, _, _ = client._get(
            "/odds/multi",
            {"apiKey": client.api_key, "eventIds": ids, "bookmakers": bookmakers},
        )
        if isinstance(batch, dict):
            batch = batch.get("response") or batch.get("events") or list(batch.values())
        for odds in batch:
            markets = correct_score_markets(odds)
            moneyline = moneyline_market(odds)
            if not markets or not moneyline:
                continue
            market, market_power = markets
            home_xg, away_xg = calibrate_poisson(moneyline)
            rows.append(
                {
                    "match": f"{odds.get('home')} - {odds.get('away')}",
                    "market": market,
                    "market_power": market_power,
                    "home_xg": home_xg,
                    "away_xg": away_xg,
                    "matrix": score_matrix(home_xg, away_xg, 8),
                }
            )

    power_rows = [{**row, "market": row["market_power"]} for row in rows]
    baseline = metrics(rows)
    baseline_power = metrics(power_rows)
    rho, goal_tilt = fit_parameters(rows)
    fitted = metrics(rows, rho, goal_tilt)
    cross_validated, fold_parameters = cross_validate(rows)
    power_rho, power_goal_tilt = fit_parameters(power_rows)
    power_fitted = metrics(power_rows, power_rho, power_goal_tilt)
    power_cross_validated, power_fold_parameters = cross_validate(power_rows)
    report = {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
        "source": "odds-api.io / Bet365 FIFA World Cup pending events",
        "baseline_independent_poisson": baseline,
        "baseline_independent_poisson_power_devig": baseline_power,
        "fitted_dixon_coles_goal_tilt": {
            "rho": rho,
            "goal_tilt": goal_tilt,
            **fitted,
        },
        "cross_validated_dixon_coles_goal_tilt": {
            **cross_validated,
            "fold_parameters": fold_parameters,
        },
        "fitted_power_devig_dixon_coles_goal_tilt": {
            "rho": power_rho,
            "goal_tilt": power_goal_tilt,
            **power_fitted,
        },
        "cross_validated_power_devig_dixon_coles_goal_tilt": {
            **power_cross_validated,
            "fold_parameters": power_fold_parameters,
        },
        "biases": score_biases(rows),
        "power_devig_biases": score_biases(power_rows),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
