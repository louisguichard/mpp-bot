import tempfile
import unittest
from pathlib import Path

from mpp_optimizer.history import HistoryDatabase, scrape_public_archive


class HistoryTests(unittest.TestCase):
    def test_imports_aggregated_match_without_user_ids(self):
        forecasts = {
            "user_a": {"homeScore": 1, "awayScore": 0, "points": {"extra": 20, "rarityLevel": 1}},
            "user_b": {"homeScore": 1, "awayScore": 0, "points": {"extra": 20, "rarityLevel": 1}},
            "user_c": {"homeScore": 2, "awayScore": 0, "points": {"extra": 0}},
            "user_d": {"homeScore": 0, "awayScore": 0, "points": {"extra": 0}},
            "user_e": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            database = HistoryDatabase(Path(directory) / "history.sqlite3")
            database.import_match_metadata(
                "match",
                {
                    "championshipId": 8,
                    "date": "2026-06-10T18:00:00.000Z",
                    "quotations": {"home": 50, "draw": 100, "away": 150},
                    "stats": {"bets": {"home": 0.7, "draw": 0.2, "away": 0.1}},
                    "home": {"clubId": "home"},
                    "away": {"clubId": "away"},
                },
                source="test",
            )
            result = database.import_forecasts("match", "general", forecasts, source="test")
            self.assertEqual(result.actual_score, "1-0")
            self.assertAlmostEqual(result.actual_score_share, 2 / 3)
            self.assertEqual(result.extra_bonus, 20)
            self.assertEqual(database.summary()["forecasts"], 4)
            self.assertEqual(database.summary()["matches_with_metadata"], 1)
            metadata = database.connection.execute(
                "SELECT * FROM match_metadata WHERE match_id = 'match'"
            ).fetchone()
            self.assertEqual(metadata["home_quotation"], 50)
            self.assertAlmostEqual(metadata["away_bet_share"], 0.1)
            columns = database.connection.execute("PRAGMA table_info(score_counts)").fetchall()
            self.assertNotIn("user_id", {column["name"] for column in columns})
            database.close()

    def test_scrapes_public_archive_without_storing_user_ids(self):
        class Client:
            def get_general_standings(self, championship_id, season):
                return {"standings": [{"user": {"id": "user_public"}}]}

            def get_user_forecast_history(self, championship_id, user_id, season, *, before_date=None):
                if before_date:
                    return {"matchesByDate": {}, "nextDate": None}
                return {
                    "matchesByDate": {
                        "2024-06-14": [
                            {
                                "matchId": "archive-match",
                                "championshipId": 9,
                                "gameWeekNumber": 1,
                                "date": "2024-06-14T19:00:00.000Z",
                                "quotations": {"home": 40, "draw": 130, "away": 170},
                                "stats": {"bets": {"home": 0.8, "draw": 0.15, "away": 0.05}},
                                "home": {"clubId": "home", "score": 2},
                                "away": {"clubId": "away", "score": 0},
                                "userForecast": {
                                    "homeScore": 2,
                                    "awayScore": 0,
                                    "points": {"extra": 20, "rarityLevel": 1},
                                },
                            }
                        ]
                    },
                    "nextDate": "2024-06-13",
                }

        with tempfile.TemporaryDirectory() as directory:
            database = HistoryDatabase(Path(directory) / "history.sqlite3")
            imported = scrape_public_archive(Client(), database, 9, 2023, delay_seconds=0)
            self.assertEqual(len(imported), 1)
            metadata = database.connection.execute(
                "SELECT * FROM match_metadata WHERE match_id = 'archive-match'"
            ).fetchone()
            self.assertEqual(metadata["season"], 2023)
            self.assertEqual(database.summary()["forecasts"], 1)
            self.assertNotIn(
                "user_public",
                database.path.read_bytes().decode(errors="ignore"),
            )
            database.close()


if __name__ == "__main__":
    unittest.main()
