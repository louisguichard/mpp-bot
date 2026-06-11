from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .matching import MatchReference, link_matches, mpp_match_references
from .mpp_client import MppClient
from .odds_client import PolymarketClient, normalize_polymarket, polymarket_1x2
from .rarity import ForecastRecommendation, SupervisedRarityModel, recommend_scores


@dataclass(frozen=True)
class PlannedForecast:
    match_id: str
    home: str
    away: str
    starts_at: str
    execute_at: str
    polymarket_event_id: str
    confidence: float


class ForecastBot:
    def __init__(
        self,
        mpp: MppClient,
        polymarket: PolymarketClient,
        rarity_model: SupervisedRarityModel,
        *,
        lead_minutes: int = 15,
        minimum_confidence: float = 0.90,
        lock_seconds: int = 60,
        planning_horizon_days: int = 29,
    ) -> None:
        self.mpp = mpp
        self.polymarket = polymarket
        self.rarity_model = rarity_model
        self.lead_minutes = lead_minutes
        self.minimum_confidence = minimum_confidence
        self.lock_seconds = lock_seconds
        self.planning_horizon_days = planning_horizon_days

    def plan(self, *, now: datetime | None = None) -> list[PlannedForecast]:
        current = now or datetime.now(UTC)
        matches, clubs = self._matches_and_clubs()
        raw_events = self.polymarket.events()
        normalized = [
            normalized_event
            for event in raw_events
            if (normalized_event := normalize_polymarket(event)).has_1x2
        ]
        references = mpp_match_references(matches, clubs)
        links = {link.mpp_match_id: link for link in link_matches(references, normalized)}
        events_by_id = {event.event_id: event for event in normalized}
        plans = []
        for reference in references:
            starts_at = _date(reference.starts_at)
            if starts_at <= current or starts_at > current + timedelta(days=self.planning_horizon_days):
                continue
            link = links.get(reference.match_id)
            if not link or link.confidence < self.minimum_confidence:
                continue
            event = events_by_id[link.provider_event_id]
            plans.append(
                PlannedForecast(
                    match_id=reference.match_id,
                    home=reference.home_team,
                    away=reference.away_team,
                    starts_at=starts_at.isoformat(),
                    execute_at=max(current, starts_at - timedelta(minutes=self.lead_minutes)).isoformat(),
                    polymarket_event_id=event.event_id,
                    confidence=round(link.confidence, 4),
                )
            )
        return sorted(plans, key=lambda item: item.execute_at)

    def sync(self, *, write: bool = False, now: datetime | None = None) -> dict[str, Any]:
        """Recompute every open match and update forecasts that changed.

        Used at first launch and at every T-15 relaunch: one pass reads MPP and
        Polymarket once, recomputes all recommendations, writes only the
        forecasts that differ from what is already saved, then verifies all
        writes with a single re-read.
        """
        current = now or datetime.now(UTC)
        matches, clubs = self._matches_and_clubs()
        raw_events = self.polymarket.events()
        normalized = [
            normalized_event
            for event in raw_events
            if (normalized_event := normalize_polymarket(event)).has_1x2
        ]
        raw_by_id = {str(event.get("id", "")): event for event in raw_events}
        references = mpp_match_references(matches, clubs)
        links = {link.mpp_match_id: link for link in link_matches(references, normalized)}
        matches_by_id = {str(match.get("matchId", "")): match for match in matches}

        results: list[dict[str, Any]] = []
        written: dict[str, ForecastRecommendation] = {}
        for reference in references:
            starts_at = _date(reference.starts_at)
            entry: dict[str, Any] = {
                "match_id": reference.match_id,
                "home": reference.home_team,
                "away": reference.away_team,
                "starts_at": starts_at.isoformat(),
            }
            results.append(entry)
            if starts_at <= current + timedelta(seconds=self.lock_seconds):
                entry["status"] = "skipped-started-or-locked"
                continue
            link = links.get(reference.match_id)
            if not link or link.confidence < self.minimum_confidence:
                entry["status"] = "skipped-no-unambiguous-market"
                continue
            match = matches_by_id[reference.match_id]
            try:
                probabilities = polymarket_1x2(raw_by_id[link.provider_event_id])
                if link.reversed_teams:
                    probabilities["home"], probabilities["away"] = (
                        probabilities["away"],
                        probabilities["home"],
                    )
                recommendation = recommend_scores(
                    probabilities,
                    match["quotations"],
                    match["stats"]["bets"],
                    self.rarity_model,
                )[0]
            except (KeyError, ValueError) as error:
                entry["status"] = "error"
                entry["error"] = str(error)
                continue
            entry["confidence"] = round(link.confidence, 4)
            entry["probabilities"] = probabilities
            entry["computed_at"] = current.isoformat()
            entry["recommendation"] = asdict(recommendation)
            existing = match.get("userForecasts", {}).get("general", {})
            if (
                existing.get("homeScore") == recommendation.home_score
                and existing.get("awayScore") == recommendation.away_score
            ):
                entry["status"] = "already-current"
                continue
            if existing.get("homeScore") is not None:
                entry["previous"] = {
                    "homeScore": existing.get("homeScore"),
                    "awayScore": existing.get("awayScore"),
                }
            if not write:
                entry["status"] = "would-write"
                continue
            try:
                self.mpp.set_forecast(
                    reference.match_id, recommendation.home_score, recommendation.away_score
                )
            except Exception as error:  # keep sweeping the remaining matches
                entry["status"] = "error"
                entry["error"] = str(error)
                continue
            entry["status"] = "written"
            written[reference.match_id] = recommendation

        unverified: list[str] = []
        if written:
            verified = self._verify_many(written)
            for entry in results:
                if entry["status"] == "written":
                    entry["verified"] = entry["match_id"] in verified
            unverified = sorted(set(written) - verified)
        statuses = [entry["status"] for entry in results]
        summary = {
            "mode": "write" if write else "dry-run",
            "checked": len(results),
            "written": statuses.count("written"),
            "would_write": statuses.count("would-write"),
            "already_current": statuses.count("already-current"),
            "skipped": sum(status.startswith("skipped") for status in statuses),
            "errors": statuses.count("error"),
            "unverified": unverified,
            "matches": results,
        }
        if write and unverified:
            raise RuntimeError(
                f"MPP did not return the saved forecast for: {', '.join(unverified)}."
            )
        return summary

    def execute(
        self,
        match_id: str,
        *,
        write: bool = False,
        require_due: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        matches, clubs = self._matches_and_clubs()
        match = next((item for item in matches if item.get("matchId") == match_id), None)
        if not match:
            if require_due:
                return {
                    "mode": "write" if write else "dry-run",
                    "status": "skipped-match-not-found",
                    "match_id": match_id,
                }
            raise LookupError(f"MPP match not found: {match_id}")
        starts_at = _date(match["date"])
        if starts_at <= current + timedelta(seconds=self.lock_seconds):
            if require_due:
                return {
                    "mode": "write" if write else "dry-run",
                    "status": "skipped-started-or-locked",
                    "match_id": match_id,
                    "starts_at": starts_at.isoformat(),
                }
            raise ValueError(f"Match {match_id} has started or is inside the write lock.")
        minutes_to_kickoff = (starts_at - current).total_seconds() / 60
        if require_due and not 5 <= minutes_to_kickoff <= self.lead_minutes + 10:
            return {
                "mode": "write" if write else "dry-run",
                "status": "skipped-not-due",
                "match_id": match_id,
                "starts_at": starts_at.isoformat(),
                "minutes_to_kickoff": round(minutes_to_kickoff, 1),
            }
        raw_events = self.polymarket.events()
        normalized = [
            normalized_event
            for event in raw_events
            if (normalized_event := normalize_polymarket(event)).has_1x2
        ]
        reference = mpp_match_references([match], clubs)[0]
        links = link_matches([reference], normalized)
        if not links or links[0].confidence < self.minimum_confidence:
            if require_due:
                return {
                    "mode": "write" if write else "dry-run",
                    "status": "skipped-no-unambiguous-market",
                    "match_id": match_id,
                    "home": reference.home_team,
                    "away": reference.away_team,
                }
            raise LookupError(f"No unambiguous Polymarket market for {reference.home_team} - {reference.away_team}.")
        link = links[0]
        raw_event = next(event for event in raw_events if str(event.get("id", "")) == link.provider_event_id)
        probabilities = polymarket_1x2(raw_event)
        if link.reversed_teams:
            probabilities["home"], probabilities["away"] = probabilities["away"], probabilities["home"]
        recommendation = recommend_scores(
            probabilities,
            match["quotations"],
            match["stats"]["bets"],
            self.rarity_model,
        )[0]
        result = {
            "mode": "write" if write else "dry-run",
            "match_id": match_id,
            "home": reference.home_team,
            "away": reference.away_team,
            "starts_at": starts_at.isoformat(),
            "polymarket_event_id": link.provider_event_id,
            "confidence": round(link.confidence, 4),
            "probabilities": probabilities,
            "recommendation": asdict(recommendation),
        }
        if not write:
            return result
        existing = match.get("userForecasts", {}).get("general", {})
        if (
            existing.get("homeScore") == recommendation.home_score
            and existing.get("awayScore") == recommendation.away_score
        ):
            result["status"] = "already-current"
            result["verified"] = True
            return result
        self.mpp.set_forecast(match_id, recommendation.home_score, recommendation.away_score)
        verified = self._verify(match_id, recommendation)
        if not verified:
            raise RuntimeError(f"MPP did not return the saved forecast for {match_id}.")
        result["verified"] = True
        result["status"] = "written"
        return result

    def _matches_and_clubs(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        matches_payload = self.mpp.get_current_matches()
        matches = list(matches_payload.values()) if isinstance(matches_payload, dict) else list(matches_payload)
        clubs_payload = self.mpp.get_clubs()
        clubs = clubs_payload.get("championshipClubs", clubs_payload)
        return matches, clubs

    def _verify(self, match_id: str, recommendation: ForecastRecommendation) -> bool:
        return match_id in self._verify_many({match_id: recommendation})

    def _verify_many(self, expected: dict[str, ForecastRecommendation]) -> set[str]:
        """Re-read MPP once and return the match ids whose forecast matches."""
        matches_payload = self.mpp.get_current_matches()
        matches = (
            matches_payload
            if isinstance(matches_payload, dict)
            else {str(item.get("matchId", "")): item for item in matches_payload}
        )
        verified = set()
        for match_id, recommendation in expected.items():
            forecast = (matches.get(match_id) or {}).get("userForecasts", {}).get("general", {})
            if (
                forecast.get("homeScore") == recommendation.home_score
                and forecast.get("awayScore") == recommendation.away_score
            ):
                verified.add(match_id)
        return verified


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
