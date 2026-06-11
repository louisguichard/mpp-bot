import unittest
from datetime import UTC, datetime

from mpp_optimizer.bot import ForecastBot
from mpp_optimizer.rarity import SupervisedRarityModel


class FakeMpp:
    def __init__(self):
        self.writes = []
        self.matches = {
            "mpp-1": {
                "matchId": "mpp-1",
                "date": "2026-06-16T19:00:00Z",
                "home": {"clubId": "fr"},
                "away": {"clubId": "sn"},
                "quotations": {"home": 46, "draw": 128, "away": 153},
                "stats": {"bets": {"home": 0.88, "draw": 0.09, "away": 0.03}},
                "userForecasts": {},
            }
        }

    def get_current_matches(self):
        return self.matches

    def get_clubs(self):
        return {
            "championshipClubs": {
                "fr": {"name": {"fr-FR": "France"}},
                "sn": {"name": {"fr-FR": "Sénégal"}},
            }
        }

    def set_forecast(self, match_id, home_score, away_score):
        self.writes.append((match_id, home_score, away_score))
        self.matches[match_id]["userForecasts"]["general"] = {
            "homeScore": home_score,
            "awayScore": away_score,
        }


class FakePolymarket:
    def events(self):
        return [
            {
                "id": "poly-1",
                "title": "France vs. Senegal",
                "active": True,
                "endDate": "2026-06-16T19:00:00Z",
                "markets": [
                    {
                        "sportsMarketType": "moneyline",
                        "groupItemTitle": "France",
                        "gameStartTime": "2026-06-16T19:00:00Z",
                        "bestBid": 0.64,
                        "bestAsk": 0.66,
                    },
                    {
                        "sportsMarketType": "moneyline",
                        "groupItemTitle": "Draw",
                        "gameStartTime": "2026-06-16T19:00:00Z",
                        "bestBid": 0.20,
                        "bestAsk": 0.22,
                    },
                    {
                        "sportsMarketType": "moneyline",
                        "groupItemTitle": "Senegal",
                        "gameStartTime": "2026-06-16T19:00:00Z",
                        "bestBid": 0.13,
                        "bestAsk": 0.15,
                    },
                ],
            },
            {
                "id": "poly-noise",
                "title": "France vs. Senegal - Exact Score",
                "active": True,
                "endDate": "2026-06-16T19:00:00Z",
                "markets": [],
            },
        ]


class EmptyPolymarket:
    def events(self):
        return []


def rarity_model():
    rows = []
    for kind, score in (("win", (1, 0)), ("draw", (1, 1))):
        for level in (1, 2, 3, 4, 5, 3, 3):
            rows.append({"k": kind, "w": score[0], "l": score[1], "q": 100, "b": 0.3, "y": level})
    return SupervisedRarityModel(
        {
            "parameters": {
                "score_identity_penalty": 1,
                "goal_distance_weight": 1,
                "quotation_distance_weight": 1,
                "bet_share_distance_weight": 3,
                "neighbors": 7,
                "distance_floor": 0.15,
            },
            "rows": rows,
        }
    )


class ForecastBotTests(unittest.TestCase):
    def setUp(self):
        self.mpp = FakeMpp()
        self.bot = ForecastBot(self.mpp, FakePolymarket(), rarity_model())
        self.now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    def test_plan_schedules_exactly_fifteen_minutes_before_match(self):
        plans = self.bot.plan(now=self.now)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].execute_at, "2026-06-16T18:45:00+00:00")

    def test_dry_run_never_writes(self):
        result = self.bot.execute("mpp-1", now=self.now)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(self.mpp.writes, [])

    def test_explicit_write_is_verified(self):
        result = self.bot.execute("mpp-1", write=True, now=self.now)
        self.assertEqual(result["mode"], "write")
        self.assertTrue(result["verified"])
        self.assertEqual(len(self.mpp.writes), 1)

    def test_stale_cloud_task_is_a_noop(self):
        result = self.bot.execute("mpp-1", write=True, require_due=True, now=self.now)
        self.assertEqual(result["status"], "skipped-not-due")
        self.assertEqual(self.mpp.writes, [])

    def test_idempotent_write_does_not_patch_twice(self):
        due = datetime(2026, 6, 16, 18, 45, tzinfo=UTC)
        first = self.bot.execute("mpp-1", write=True, require_due=True, now=due)
        second = self.bot.execute("mpp-1", write=True, require_due=True, now=due)
        self.assertEqual(first["status"], "written")
        self.assertEqual(second["status"], "already-current")
        self.assertEqual(len(self.mpp.writes), 1)

    def test_missing_market_is_safe_noop_for_cloud_task(self):
        bot = ForecastBot(self.mpp, EmptyPolymarket(), rarity_model())
        due = datetime(2026, 6, 16, 18, 45, tzinfo=UTC)
        result = bot.execute("mpp-1", write=True, require_due=True, now=due)
        self.assertEqual(result["status"], "skipped-no-unambiguous-market")
        self.assertEqual(self.mpp.writes, [])

    def test_sync_dry_run_never_writes(self):
        result = self.bot.sync(now=self.now)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["would_write"], 1)
        self.assertEqual(self.mpp.writes, [])

    def test_sync_first_run_plays_every_open_match(self):
        result = self.bot.sync(write=True, now=self.now)
        self.assertEqual(result["written"], 1)
        self.assertEqual(result["unverified"], [])
        self.assertEqual(len(self.mpp.writes), 1)
        self.assertTrue(result["matches"][0]["verified"])

    def test_sync_is_idempotent_when_nothing_changed(self):
        self.bot.sync(write=True, now=self.now)
        second = self.bot.sync(write=True, now=self.now)
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["already_current"], 1)
        self.assertEqual(len(self.mpp.writes), 1)

    def test_sync_updates_a_forecast_that_drifted(self):
        self.mpp.matches["mpp-1"]["userForecasts"]["general"] = {
            "homeScore": 9,
            "awayScore": 9,
        }
        result = self.bot.sync(write=True, now=self.now)
        self.assertEqual(result["written"], 1)
        entry = result["matches"][0]
        self.assertEqual(entry["previous"], {"homeScore": 9, "awayScore": 9})
        self.assertEqual(len(self.mpp.writes), 1)
        self.assertEqual(len(result["changes"]), 1)
        change = result["changes"][0]
        self.assertEqual(change["previous"], "9-9")
        self.assertEqual(change["status"], "written")
        self.assertIn("–", change["match"])
        recommendation = entry["recommendation"]
        self.assertEqual(
            change["new"],
            f"{recommendation['home_score']}-{recommendation['away_score']}",
        )

    def test_sync_skips_started_matches(self):
        started = datetime(2026, 6, 16, 19, 30, tzinfo=UTC)
        result = self.bot.sync(write=True, now=started)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.mpp.writes, [])

    def test_sync_sweeps_past_an_unmatched_match(self):
        self.mpp.matches["mpp-2"] = {
            "matchId": "mpp-2",
            "date": "2026-06-17T19:00:00Z",
            "home": {"clubId": "xx"},
            "away": {"clubId": "yy"},
            "quotations": {"home": 80, "draw": 100, "away": 120},
            "stats": {"bets": {"home": 0.5, "draw": 0.3, "away": 0.2}},
            "userForecasts": {},
        }
        result = self.bot.sync(write=True, now=self.now)
        statuses = {entry["match_id"]: entry["status"] for entry in result["matches"]}
        self.assertEqual(statuses["mpp-1"], "written")
        self.assertEqual(statuses["mpp-2"], "skipped-no-unambiguous-market")
        self.assertEqual(len(self.mpp.writes), 1)


if __name__ == "__main__":
    unittest.main()
