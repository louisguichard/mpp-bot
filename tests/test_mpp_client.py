import unittest

from mpp_optimizer.mpp_client import MppClient


class MppClientTests(unittest.TestCase):
    def test_writes_are_disabled_by_default(self):
        client = MppClient(token="not-used")
        with self.assertRaises(PermissionError):
            client.set_forecast("match-id", 1, 0)

    def test_calendar_can_target_an_archived_season(self):
        class RecordingClient(MppClient):
            def get(self, path):
                return path

        client = RecordingClient(token="not-used")
        self.assertEqual(
            client.get_championship_calendar(9, 2023),
            "/championship-calendar/9?seasonYear=2023",
        )

    def test_public_archive_routes(self):
        class RecordingClient(MppClient):
            def get(self, path):
                return path

        client = RecordingClient(token="not-used")
        self.assertEqual(
            client.get_general_standings(9, 2023),
            "/general-standings/top-users-standings?championshipId=9&season=2023",
        )
        self.assertEqual(
            client.get_user_forecast_history(9, "user_1", 2023, before_date="2024-07-02"),
            "/user-match-forecasts/championship/9/history?"
            "championshipId=9&userId=user_1&season=2023&beforeDate=2024-07-02",
        )


if __name__ == "__main__":
    unittest.main()
