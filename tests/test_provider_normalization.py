import unittest

from mpp_optimizer.odds_client import (
    normalize_api_football,
    normalize_odds_api_io,
    normalize_polymarket,
    polymarket_1x2,
)


class ProviderNormalizationTests(unittest.TestCase):
    def test_api_football(self):
        event = normalize_api_football(
            {
                "fixture": {"id": 1, "date": "2026-06-10T18:00:00Z", "status": {"short": "NS"}},
                "league": {"name": "World Cup"},
                "update": "2026-06-09T10:00:00Z",
                "bookmakers": [
                    {"bets": [{"name": "Match Winner", "values": [{}, {}, {}]}, {"name": "Correct Score", "values": [{}]}]}
                ],
            }
        )
        self.assertTrue(event.has_1x2)
        self.assertTrue(event.has_correct_score)
        self.assertEqual(event.selection_count, 4)

    def test_odds_api_io(self):
        event = normalize_odds_api_io(
            {"id": 2, "home": "A", "away": "B", "date": "2026-06-10T18:00:00Z", "league": {"name": "Cup"}},
            {"bookmakers": {"Bet365": [{"name": "ML", "odds": [{}], "updatedAt": "2026-06-09T10:00:00Z"}]}},
        )
        self.assertTrue(event.has_1x2)
        self.assertEqual(event.bookmaker_count, 1)

    def test_polymarket(self):
        event = normalize_polymarket(
            {
                "id": "3",
                "title": "France vs. Brazil",
                "active": True,
                "liquidity": "10000",
                "volume": "5000",
                "markets": [
                    {"sportsMarketType": "moneyline", "outcomes": "[\"Yes\", \"No\"]", "updatedAt": "2026-06-09T10:00:00Z"},
                    {"sportsMarketType": "moneyline", "outcomes": "[\"Yes\", \"No\"]", "updatedAt": "2026-06-09T10:00:01Z"},
                    {"sportsMarketType": "moneyline", "outcomes": "[\"Yes\", \"No\"]", "updatedAt": "2026-06-09T10:00:02Z"},
                ],
            }
        )
        self.assertTrue(event.has_1x2)
        self.assertFalse(event.has_correct_score)
        self.assertEqual(event.liquidity, 10000)

    def test_polymarket_1x2(self):
        probabilities = polymarket_1x2(
            {
                "title": "France vs. Brazil",
                "markets": [
                    {"sportsMarketType": "moneyline", "groupItemTitle": "France", "bestBid": 0.49, "bestAsk": 0.51},
                    {"sportsMarketType": "moneyline", "groupItemTitle": "Draw (France vs. Brazil)", "bestBid": 0.19, "bestAsk": 0.21},
                    {"sportsMarketType": "moneyline", "groupItemTitle": "Brazil", "bestBid": 0.29, "bestAsk": 0.31},
                ],
            }
        )
        self.assertAlmostEqual(sum(probabilities.values()), 1)
        self.assertAlmostEqual(probabilities["home"], 0.5)


if __name__ == "__main__":
    unittest.main()
