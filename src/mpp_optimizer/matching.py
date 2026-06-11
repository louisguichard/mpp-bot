from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .odds_client import NormalizedEvent


ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "team_aliases.json"


@dataclass(frozen=True)
class MatchReference:
    source: str
    match_id: str
    home_team: str
    away_team: str
    starts_at: str


@dataclass(frozen=True)
class MatchLink:
    mpp_match_id: str
    provider: str
    provider_event_id: str
    confidence: float
    time_difference_minutes: int
    reversed_teams: bool
    reason: str


def mpp_match_references(
    matches: Iterable[dict],
    clubs: dict[str, dict],
    *,
    language: str = "fr-FR",
) -> list[MatchReference]:
    """Convert MPP match payloads plus championship clubs into match references."""
    references = []
    for match in matches:
        home_id = match.get("home", {}).get("clubId")
        away_id = match.get("away", {}).get("clubId")
        home = clubs.get(home_id, {})
        away = clubs.get(away_id, {})
        references.append(
            MatchReference(
                source="mpp",
                match_id=str(match.get("matchId", "")),
                home_team=_club_name(home, language),
                away_team=_club_name(away, language),
                starts_at=match.get("date", ""),
            )
        )
    return references


def link_matches(
    mpp_matches: Iterable[MatchReference],
    provider_events: Iterable[NormalizedEvent],
    *,
    max_time_difference_hours: int = 8,
    aliases_path: Path = ALIASES_PATH,
) -> list[MatchLink]:
    aliases = load_aliases(aliases_path)
    events = list(provider_events)
    links: list[MatchLink] = []
    for match in mpp_matches:
        candidates: list[tuple[float, int, bool, NormalizedEvent, str]] = []
        for event in events:
            time_difference = _minutes_between(match.starts_at, event.starts_at)
            if time_difference > max_time_difference_hours * 60:
                continue
            direct = (
                team_similarity(match.home_team, event.home_team, aliases)
                + team_similarity(match.away_team, event.away_team, aliases)
            ) / 2
            reversed_score = (
                team_similarity(match.home_team, event.away_team, aliases)
                + team_similarity(match.away_team, event.home_team, aliases)
            ) / 2
            reversed_teams = reversed_score > direct
            team_score = max(direct, reversed_score)
            if team_score < 0.72:
                continue
            time_score = max(0.0, 1 - time_difference / (max_time_difference_hours * 60))
            confidence = 0.85 * team_score + 0.15 * time_score
            reason = f"équipes {team_score:.0%}, horaire ±{time_difference} min"
            candidates.append((confidence, time_difference, reversed_teams, event, reason))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates:
            continue
        best = candidates[0]
        if len(candidates) > 1 and best[0] - candidates[1][0] < 0.08:
            continue
        links.append(
            MatchLink(
                mpp_match_id=match.match_id,
                provider=best[3].provider,
                provider_event_id=best[3].event_id,
                confidence=best[0],
                time_difference_minutes=best[1],
                reversed_teams=best[2],
                reason=best[4],
            )
        )
    return links


def team_similarity(left: str, right: str, aliases: dict[str, str]) -> float:
    left_key = canonical_team(left, aliases)
    right_key = canonical_team(right, aliases)
    if left_key == right_key:
        return 1.0
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def canonical_team(name: str, aliases: dict[str, str]) -> str:
    normalized = normalize_name(name)
    return aliases.get(normalized, normalized)


def normalize_name(name: str) -> str:
    # Replace typographic apostrophes before ASCII folding so "d’Ivoire" does
    # not collapse into "divoire".
    name = re.sub(r"['’`]", " ", name)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.lower()).strip()


def load_aliases(path: Path = ALIASES_PATH) -> dict[str, str]:
    groups = json.loads(path.read_text())
    aliases: dict[str, str] = {}
    for canonical, variants in groups.items():
        canonical_key = normalize_name(canonical)
        aliases[canonical_key] = canonical_key
        for variant in variants:
            aliases[normalize_name(variant)] = canonical_key
    return aliases


def _minutes_between(left: str, right: str) -> int:
    left_date = _parse_date(left)
    right_date = _parse_date(right)
    return round(abs((left_date - right_date).total_seconds()) / 60)


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _club_name(club: dict, language: str) -> str:
    names = club.get("name", {})
    return names.get(language) or names.get("en-GB") or names.get("fr-FR") or club.get("shortName", "")
