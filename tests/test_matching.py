import unittest

from mpp_optimizer.matching import MatchReference, link_matches, mpp_match_references
from mpp_optimizer.odds_client import NormalizedEvent


def event(event_id, home, away, starts_at):
    return NormalizedEvent(
        provider="polymarket",
        event_id=event_id,
        home_team=home,
        away_team=away,
        starts_at=starts_at,
        status="active",
        league="World Cup",
        bookmaker_count=1,
        market_count=3,
        selection_count=6,
        has_1x2=True,
        has_correct_score=False,
        freshest_update=None,
        oldest_update=None,
    )


class MatchingTests(unittest.TestCase):
    def test_links_french_mpp_name_to_polymarket(self):
        links = link_matches(
            [MatchReference("mpp", "mpp-1", "Mexique", "Afrique du Sud", "2026-06-11T19:00:00Z")],
            [event("poly-1", "Mexico", "South Africa", "2026-06-11T19:00:00Z")],
        )
        self.assertEqual(len(links), 1)
        self.assertGreater(links[0].confidence, 0.99)

    def test_links_known_aliases_and_detects_reversed_order(self):
        links = link_matches(
            [MatchReference("mpp", "mpp-2", "Corée du Sud", "Tchéquie", "2026-06-12T02:00:00Z")],
            [event("poly-2", "Czechia", "Korea Republic", "2026-06-12T02:02:00Z")],
        )
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0].reversed_teams)

    def test_links_typographic_apostrophe(self):
        links = link_matches(
            [MatchReference("mpp", "mpp-ivory", "Côte d’Ivoire", "Équateur", "2026-06-14T23:00:00Z")],
            [event("poly-ivory", "Côte d'Ivoire", "Ecuador", "2026-06-14T23:00:00Z")],
        )
        self.assertEqual(len(links), 1)

    def test_rejects_wrong_date(self):
        links = link_matches(
            [MatchReference("mpp", "mpp-3", "France", "Sénégal", "2026-06-16T19:00:00Z")],
            [event("poly-3", "France", "Senegal", "2026-06-18T19:00:00Z")],
        )
        self.assertEqual(links, [])

    def test_builds_reference_from_mpp_payload(self):
        references = mpp_match_references(
            [
                {
                    "matchId": "mpp-4",
                    "date": "2026-06-11T19:00:00Z",
                    "home": {"clubId": "mex"},
                    "away": {"clubId": "rsa"},
                }
            ],
            {
                "mex": {"name": {"fr-FR": "Mexique"}},
                "rsa": {"name": {"fr-FR": "Afrique du Sud"}},
            },
        )
        self.assertEqual(references[0].home_team, "Mexique")


if __name__ == "__main__":
    unittest.main()
