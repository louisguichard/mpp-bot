import unittest

from mpp_optimizer.odds_client import consensus_1x2


class OddsClientTests(unittest.TestCase):
    def test_consensus_1x2(self):
        event = {
            "home_team": "Paris",
            "away_team": "Marseille",
            "bookmakers": [
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Paris", "price": 1.8},
                                {"name": "Draw", "price": 3.7},
                                {"name": "Marseille", "price": 4.5},
                            ],
                        }
                    ]
                },
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Paris", "price": 1.85},
                                {"name": "Draw", "price": 3.6},
                                {"name": "Marseille", "price": 4.4},
                            ],
                        }
                    ]
                },
            ],
        }
        odds = consensus_1x2(event)
        implied_total = sum(1 / value for value in odds.values())
        self.assertAlmostEqual(implied_total, 1.0)
        self.assertLess(odds["home"], odds["away"])


if __name__ == "__main__":
    unittest.main()

