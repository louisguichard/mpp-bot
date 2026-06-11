from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import MatchInput, optimize, remove_vig, calibrate_poisson


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank MPP scores by expected points.")
    parser.add_argument("match", type=Path, help="Path to a match JSON file.")
    parser.add_argument("--top", type=int, default=10, help="Number of scores to display.")
    args = parser.parse_args()

    raw = json.loads(args.match.read_text())
    match = MatchInput(**raw)
    market = remove_vig(match.bookmaker_odds)
    home_xg, away_xg = calibrate_poisson(market, match.max_goals)

    print(f"{match.home_team} - {match.away_team}")
    print(
        "Marché sans marge: "
        + " / ".join(f"{key} {market[key]:.1%}" for key in ("home", "draw", "away"))
    )
    print(f"Buts attendus calibrés: {home_xg:.2f} - {away_xg:.2f}\n")
    print("Rang  Score  Issue  P(score)  P(issue)  Espérance  Edge foule")
    for rank, item in enumerate(optimize(match)[: args.top], start=1):
        edge = "-" if item.market_edge_vs_crowd is None else f"{item.market_edge_vs_crowd:+.1%}"
        print(
            f"{rank:>4}  {item.home_score}-{item.away_score:<3}  "
            f"{item.outcome:<5}  {item.score_probability:>7.1%}  "
            f"{item.outcome_probability:>8.1%}  {item.expected_points:>9.2f}  {edge:>9}"
        )


if __name__ == "__main__":
    main()

