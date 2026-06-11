import unittest

from mpp_optimizer.model import (
    RARITY_BONUSES,
    MatchInput,
    estimate_score_crowd,
    exact_score_probabilities_from_odds,
    optimize,
    outcome,
    rarity_level_from_share,
    remove_vig,
    score_matrix,
)


class ModelTests(unittest.TestCase):
    def test_remove_vig_sums_to_one(self):
        probabilities = remove_vig({"home": 1.8, "draw": 3.5, "away": 4.5})
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_outcome(self):
        self.assertEqual(outcome(2, 1), "home")
        self.assertEqual(outcome(1, 1), "draw")
        self.assertEqual(outcome(0, 1), "away")

    def test_optimizer_returns_best_first(self):
        match = MatchInput(
            home_team="A",
            away_team="B",
            bookmaker_odds={"home": 1.8, "draw": 3.5, "away": 4.5},
            mpp_quotations={"home": 80, "draw": 130, "away": 170},
        )
        recommendations = optimize(match)
        self.assertGreaterEqual(
            recommendations[0].expected_points,
            recommendations[-1].expected_points,
        )
        self.assertAlmostEqual(
            recommendations[0].expected_points,
            recommendations[0].expected_base_points
            + recommendations[0].expected_exact_bonus,
        )

    def test_correct_score_market_replaces_poisson(self):
        match = MatchInput(
            home_team="A",
            away_team="B",
            bookmaker_odds={"home": 2.0, "draw": 3.0, "away": 4.0},
            mpp_quotations={"home": 100, "draw": 100, "away": 100},
            exact_score_probabilities={"0-0": 0.1, "1-0": 0.6, "0-1": 0.3},
        )
        recommendations = optimize(match)
        one_nil = next(item for item in recommendations if item.home_score == 1 and item.away_score == 0)
        self.assertAlmostEqual(one_nil.score_probability, 0.6)

    def test_rarity_bands_and_market_margin(self):
        self.assertEqual(RARITY_BONUSES, {1: 20.0, 2: 30.0, 3: 50.0, 4: 70.0, 5: 100.0})
        self.assertEqual(rarity_level_from_share(0.31), 1)
        self.assertEqual(rarity_level_from_share(0.30), 2)
        self.assertEqual(rarity_level_from_share(0.25), 2)
        self.assertEqual(rarity_level_from_share(0.10), 3)
        self.assertEqual(rarity_level_from_share(0.01), 4)
        self.assertEqual(rarity_level_from_share(0.001), 5)
        probabilities = exact_score_probabilities_from_odds({"1-0": 5, "0-0": 10})
        self.assertAlmostEqual(sum(probabilities.values()), 1)
        proportional_longshot = (1 / 10) / ((1 / 1.5) + (1 / 2) + (1 / 10))
        power = exact_score_probabilities_from_odds({"favorite": 1.5, "middle": 2, "longshot": 10})
        self.assertLess(power["longshot"], proportional_longshot)

    def test_estimated_score_crowd_is_conditional_on_outcome(self):
        crowd = estimate_score_crowd({(1, 0): 0.4, (2, 0): 0.2, (0, 0): 0.1, (1, 1): 0.3})
        self.assertAlmostEqual(crowd["1-0"] + crowd["2-0"], 1.0)
        self.assertAlmostEqual(crowd["0-0"] + crowd["1-1"], 1.0)
        self.assertGreater(crowd["1-0"], crowd["2-0"])

    def test_dixon_coles_rho_shifts_low_score_mass(self):
        independent = score_matrix(1.4, 1.1, 8, rho=0.0)
        adjusted = score_matrix(1.4, 1.1, 8, rho=-0.10)
        self.assertGreater(adjusted[(0, 0)], independent[(0, 0)])
        self.assertGreater(adjusted[(1, 1)], independent[(1, 1)])
        self.assertLess(adjusted[(1, 0)], independent[(1, 0)])
        self.assertAlmostEqual(sum(adjusted.values()), 1.0)

    def test_calibration_fits_a_strong_favourite_inside_the_grid(self):
        from mpp_optimizer.model import calibrate_poisson, outcome_probabilities

        home_xg, away_xg = calibrate_poisson({"home": 0.93, "draw": 0.05, "away": 0.02})
        probabilities = outcome_probabilities(score_matrix(home_xg, away_xg, 8))
        self.assertLessEqual(home_xg, 4.4)
        self.assertAlmostEqual(probabilities["home"], 0.93, delta=0.015)

    def test_upset_minimal_win_is_not_treated_as_rare(self):
        crowd = estimate_score_crowd(score_matrix(4.0, 0.4, 8))
        self.assertGreater(crowd["0-1"], 0.30)
        self.assertEqual(rarity_level_from_share(crowd["0-1"]), 1)


if __name__ == "__main__":
    unittest.main()
