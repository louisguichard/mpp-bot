from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .model import remove_vig


@dataclass(frozen=True)
class NormalizedEvent:
    provider: str
    event_id: str
    home_team: str
    away_team: str
    starts_at: str
    status: str
    league: str
    bookmaker_count: int
    market_count: int
    selection_count: int
    has_1x2: bool
    has_correct_score: bool
    freshest_update: str | None
    oldest_update: str | None
    liquidity: float | None = None
    volume: float | None = None
    markets: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    fetched_at: str
    latency_ms: int
    events: tuple[NormalizedEvent, ...]
    quota: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [event.to_dict() for event in self.events]
        return payload


class JsonApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, dict[str, str], int]:
        query = urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        started = time.perf_counter()
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "MPP-Odds-Lab/0.1",
                **(headers or {}),
            },
        )
        with urlopen(request, timeout=25) as response:
            body = json.load(response)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
        return body, response_headers, round((time.perf_counter() - started) * 1000)


class ApiFootballClient(JsonApiClient):
    """API-Football v3: 100 requests/day on the free plan."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://v3.football.api-sports.io",
    ) -> None:
        super().__init__(base_url)
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY")

    def snapshot(self, date: str | None = None, page: int = 1) -> ProviderSnapshot:
        if not self.api_key:
            return demo_snapshot("api-football")
        payload, headers, latency = self._get(
            "/odds",
            {"date": date or datetime.now().date().isoformat(), "page": page},
            {"x-apisports-key": self.api_key},
        )
        events = tuple(normalize_api_football(item) for item in payload.get("response", []))
        quota = {
            key: value
            for key, value in headers.items()
            if "ratelimit" in key or "requests" in key
        }
        return ProviderSnapshot(
            provider="api-football",
            fetched_at=now_iso(),
            latency_ms=latency,
            events=events,
            quota=quota,
        )


class OddsApiIoClient(JsonApiClient):
    """Odds-API.io v3."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.odds-api.io/v3",
    ) -> None:
        super().__init__(base_url)
        self.api_key = api_key or os.getenv("ODDS_API_IO_KEY") or os.getenv("ODDS_API_KEY")

    def snapshot(
        self,
        hours: int = 36,
        limit: int = 20,
        league: str | None = "international-fifa-world-cup",
    ) -> ProviderSnapshot:
        if not self.api_key:
            return demo_snapshot("odds-api-io")
        start = datetime.now(UTC)
        selected, selected_headers, selected_latency = self._get(
            "/bookmakers/selected", {"apiKey": self.api_key}
        )
        bookmakers = ",".join(selected.get("bookmakers", []))
        events, event_headers, event_latency = self._get(
            "/events",
            {
                "apiKey": self.api_key,
                "sport": "football",
                "league": league,
                "status": "pending",
                "from": None if league else start.isoformat(),
                "to": None if league else (start + timedelta(hours=hours)).isoformat(),
                "limit": limit,
            },
        )
        event_ids = [str(event["id"]) for event in events[:limit]]
        odds: list[dict[str, Any]] = []
        odds_headers: dict[str, str] = {}
        odds_latency = 0
        for offset in range(0, len(event_ids), 10):
            ids = ",".join(event_ids[offset : offset + 10])
            batch, batch_headers, batch_latency = self._get(
                "/odds/multi",
                {"apiKey": self.api_key, "eventIds": ids, "bookmakers": bookmakers},
            )
            if isinstance(batch, dict):
                batch = batch.get("response") or batch.get("events") or list(batch.values())
            odds.extend(item for item in batch if isinstance(item, dict))
            odds_headers.update(batch_headers)
            odds_latency += batch_latency
        odds_by_id = {
            str(item.get("id") or item.get("eventId")): item
            for item in odds
            if isinstance(item, dict)
        }
        normalized = tuple(
            normalize_odds_api_io(event, odds_by_id.get(str(event["id"]), {}))
            for event in events[:limit]
        )
        quota = {
            key: value
            for key, value in {**selected_headers, **event_headers, **odds_headers}.items()
            if "ratelimit" in key
        }
        return ProviderSnapshot(
            provider="odds-api-io",
            fetched_at=now_iso(),
            latency_ms=selected_latency + event_latency + odds_latency,
            events=normalized,
            quota=quota,
        )


class PolymarketClient(JsonApiClient):
    """Public Polymarket Gamma API. No key required."""

    def __init__(
        self,
        series_id: str | None = None,
        base_url: str = "https://gamma-api.polymarket.com",
    ) -> None:
        super().__init__(base_url)
        self.series_id = series_id or os.getenv("POLYMARKET_SERIES_ID", "11433")

    def snapshot(self, limit: int = 20) -> ProviderSnapshot:
        payload, _, latency = self._get(
            "/events/keyset",
            {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "series_id": self.series_id,
            },
        )
        events = payload.get("events", []) if isinstance(payload, dict) else payload
        return ProviderSnapshot(
            provider="polymarket",
            fetched_at=now_iso(),
            latency_ms=latency,
            events=tuple(normalize_polymarket(event) for event in events),
        )

    def events(self, *, pages: int = 5, limit: int = 100) -> list[dict[str, Any]]:
        """Return raw active events, following the public keyset pagination."""
        events: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(pages):
            payload, _, _ = self._get(
                "/events/keyset",
                {
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "series_id": self.series_id,
                    "after_cursor": cursor or None,
                },
            )
            page = payload.get("events", []) if isinstance(payload, dict) else payload
            events.extend(item for item in page if isinstance(item, dict))
            cursor = payload.get("next_cursor", "") if isinstance(payload, dict) else ""
            if not cursor or len(page) < limit:
                break
        return events


def normalize_api_football(item: dict[str, Any]) -> NormalizedEvent:
    fixture = item.get("fixture", {})
    league = item.get("league", {})
    bookmakers = item.get("bookmakers", [])
    markets = [bet for bookmaker in bookmakers for bet in bookmaker.get("bets", [])]
    market_names = sorted({market.get("name", "") for market in markets if market.get("name")})
    selection_count = sum(len(market.get("values", [])) for market in markets)
    updates = [
        value
        for value in (item.get("update"), fixture.get("timestamp"))
        if isinstance(value, str)
    ]
    return NormalizedEvent(
        provider="api-football",
        event_id=str(fixture.get("id", "")),
        home_team=item.get("teams", {}).get("home", {}).get("name", f"Fixture {fixture.get('id', '?')}"),
        away_team=item.get("teams", {}).get("away", {}).get("name", "Équipes non incluses"),
        starts_at=fixture.get("date", ""),
        status=fixture.get("status", {}).get("short", "pending"),
        league=league.get("name", ""),
        bookmaker_count=len(bookmakers),
        market_count=len(markets),
        selection_count=selection_count,
        has_1x2=_has_market(market_names, ("match winner", "1x2", "winner")),
        has_correct_score=_has_market(market_names, ("correct score", "exact score")),
        freshest_update=max(updates, default=None),
        oldest_update=min(updates, default=None),
        markets=tuple(market_names),
    )


def normalize_odds_api_io(event: dict[str, Any], odds: dict[str, Any]) -> NormalizedEvent:
    bookmakers = odds.get("bookmakers", {})
    market_rows = [
        market
        for markets in bookmakers.values()
        for market in markets
        if isinstance(market, dict)
    ]
    market_names = sorted({market.get("name", "") for market in market_rows if market.get("name")})
    updates = [
        market["updatedAt"]
        for market in market_rows
        if isinstance(market.get("updatedAt"), str)
    ]
    selection_count = sum(
        len(market.get("odds", []))
        for market in market_rows
        if isinstance(market.get("odds"), list)
    )
    return NormalizedEvent(
        provider="odds-api-io",
        event_id=str(event.get("id", "")),
        home_team=event.get("home", "?"),
        away_team=event.get("away", "?"),
        starts_at=event.get("date", ""),
        status=event.get("status", "pending"),
        league=event.get("league", {}).get("name", ""),
        bookmaker_count=len(bookmakers),
        market_count=len(market_rows),
        selection_count=selection_count,
        has_1x2=_has_market(market_names, ("ml", "match winner", "1x2")),
        has_correct_score=_has_market(market_names, ("correct score", "exact score")),
        freshest_update=max(updates, default=None),
        oldest_update=min(updates, default=None),
        markets=tuple(market_names),
    )


def normalize_polymarket(event: dict[str, Any]) -> NormalizedEvent:
    markets = event.get("markets", [])
    moneyline = [market for market in markets if market.get("sportsMarketType") == "moneyline"]
    updates = [
        value
        for value in [event.get("updatedAt"), *(market.get("updatedAt") for market in markets)]
        if isinstance(value, str)
    ]
    title = event.get("title", "? vs. ?")
    teams = title.split(" vs. ", 1)
    return NormalizedEvent(
        provider="polymarket",
        event_id=str(event.get("id", "")),
        home_team=teams[0],
        away_team=teams[1] if len(teams) == 2 else "?",
        starts_at=next(
            (market.get("gameStartTime") for market in markets if market.get("gameStartTime")),
            event.get("endDate", ""),
        ),
        status="active" if event.get("active") else "inactive",
        league="Polymarket sports series",
        bookmaker_count=1,
        market_count=len(markets),
        selection_count=sum(len(json.loads(market.get("outcomes", "[]"))) for market in markets),
        has_1x2=len(moneyline) >= 3,
        has_correct_score=False,
        freshest_update=max(updates, default=None),
        oldest_update=min(updates, default=None),
        liquidity=_float_or_none(event.get("liquidity")),
        volume=_float_or_none(event.get("volume")),
        markets=tuple(sorted({market.get("sportsMarketType", "other") for market in markets})),
    )


def polymarket_1x2(event: dict[str, Any]) -> dict[str, float]:
    """Extract normalized 1X2 probabilities from three Polymarket moneylines."""
    title = event.get("title", "")
    teams = title.split(" vs. ", 1)
    if len(teams) != 2:
        raise ValueError("Polymarket event title does not contain two teams.")
    home, away = teams
    probabilities: dict[str, float] = {}
    for market in event.get("markets", []):
        if market.get("sportsMarketType") != "moneyline":
            continue
        label = market.get("groupItemTitle", "")
        if label == home:
            key = "home"
        elif label == away:
            key = "away"
        elif label.lower().startswith("draw"):
            key = "draw"
        else:
            continue
        probabilities[key] = _market_midpoint(market)
    missing = set(("home", "draw", "away")) - probabilities.keys()
    if missing:
        raise ValueError(f"Missing Polymarket moneylines: {', '.join(sorted(missing))}")
    total = sum(probabilities.values())
    return {key: probabilities[key] / total for key in ("home", "draw", "away")}


def consensus_1x2(event: dict[str, Any]) -> dict[str, float]:
    """Return synthetic decimal odds from average de-vigged bookmaker prices."""
    home_team = event["home_team"]
    away_team = event["away_team"]
    probabilities: list[dict[str, float]] = []
    for bookmaker in event.get("bookmakers", []):
        h2h = next(
            (market for market in bookmaker.get("markets", []) if market["key"] == "h2h"),
            None,
        )
        if not h2h:
            continue
        prices = {item["name"]: item["price"] for item in h2h["outcomes"]}
        if not {home_team, away_team, "Draw"} <= prices.keys():
            continue
        probabilities.append(
            remove_vig(
                {
                    "home": prices[home_team],
                    "draw": prices["Draw"],
                    "away": prices[away_team],
                }
            )
        )
    if not probabilities:
        raise ValueError("No complete h2h bookmaker market found for this event.")
    consensus = {
        outcome: mean(bookmaker[outcome] for bookmaker in probabilities)
        for outcome in ("home", "draw", "away")
    }
    return {outcome: 1 / probability for outcome, probability in consensus.items()}


def demo_snapshot(provider: str) -> ProviderSnapshot:
    now = datetime.now(UTC)
    if provider == "api-football":
        events = (
            NormalizedEvent(
                provider=provider,
                event_id="demo-af-1",
                home_team="Paris SG",
                away_team="Marseille",
                starts_at=(now + timedelta(hours=5)).isoformat(),
                status="NS",
                league="Demo Ligue 1",
                bookmaker_count=9,
                market_count=81,
                selection_count=430,
                has_1x2=True,
                has_correct_score=True,
                freshest_update=(now - timedelta(minutes=18)).isoformat(),
                oldest_update=(now - timedelta(hours=3)).isoformat(),
                markets=("Match Winner", "Correct Score", "Goals Over/Under"),
            ),
        )
        latency = 420
    else:
        events = (
            NormalizedEvent(
                provider=provider,
                event_id="demo-io-1",
                home_team="Paris SG",
                away_team="Marseille",
                starts_at=(now + timedelta(hours=5)).isoformat(),
                status="pending",
                league="Demo Ligue 1",
                bookmaker_count=14,
                market_count=126,
                selection_count=720,
                has_1x2=True,
                has_correct_score=True,
                freshest_update=(now - timedelta(seconds=35)).isoformat(),
                oldest_update=(now - timedelta(minutes=8)).isoformat(),
                markets=("ML", "Correct Score", "Totals", "Both Teams to Score"),
            ),
        )
        latency = 610
    return ProviderSnapshot(
        provider=provider,
        fetched_at=now.isoformat(),
        latency_ms=latency,
        events=events,
        demo=True,
    )


def _has_market(markets: list[str], needles: tuple[str, ...]) -> bool:
    lowered = " ".join(markets).lower()
    return any(needle in lowered for needle in needles)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_midpoint(market: dict[str, Any]) -> float:
    bid = _float_or_none(market.get("bestBid"))
    ask = _float_or_none(market.get("bestAsk"))
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    prices = json.loads(market.get("outcomePrices", "[]"))
    if not prices:
        raise ValueError("Polymarket market has no usable price.")
    return float(prices[0])


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
