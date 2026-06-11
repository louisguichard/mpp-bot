from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .model import outcome
from .mpp_client import MppClient


FORECAST_URL = re.compile(
    rb"https://api\.mpp\.football/user-match-forecasts/contest/"
    rb"(?P<contest>[^/]+)/match/(?P<match>mpp_championship_match_[0-9]+)"
)
MATCH_URL = re.compile(
    rb"https://api\.mpp\.football/championship-match/"
    rb"(?P<match>mpp_championship_match_[0-9]+)"
)


@dataclass(frozen=True)
class ImportedMatch:
    match_id: str
    contest_id: str
    forecast_count: int
    actual_score: str | None
    actual_score_share: float | None
    rarity_level: int | None
    extra_bonus: int | None


class HistoryDatabase:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT NOT NULL,
                contest_id TEXT NOT NULL,
                actual_home_score INTEGER,
                actual_away_score INTEGER,
                actual_outcome TEXT,
                forecast_count INTEGER NOT NULL,
                correct_outcome_count INTEGER,
                exact_count INTEGER,
                exact_share_all REAL,
                exact_share_within_outcome REAL,
                rarity_level INTEGER,
                extra_bonus INTEGER,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                PRIMARY KEY (match_id, contest_id)
            );

            CREATE TABLE IF NOT EXISTS score_counts (
                match_id TEXT NOT NULL,
                contest_id TEXT NOT NULL,
                home_score INTEGER NOT NULL,
                away_score INTEGER NOT NULL,
                predicted_outcome TEXT NOT NULL,
                forecast_count INTEGER NOT NULL,
                share_all REAL NOT NULL,
                share_within_outcome REAL NOT NULL,
                is_actual_score INTEGER NOT NULL,
                PRIMARY KEY (match_id, contest_id, home_score, away_score)
            );

            CREATE TABLE IF NOT EXISTS match_metadata (
                match_id TEXT PRIMARY KEY,
                championship_id TEXT,
                season INTEGER,
                game_week_number INTEGER,
                match_date TEXT,
                home_club_id TEXT,
                away_club_id TEXT,
                home_score INTEGER,
                away_score INTEGER,
                home_quotation INTEGER,
                draw_quotation INTEGER,
                away_quotation INTEGER,
                home_bet_share REAL,
                draw_bet_share REAL,
                away_bet_share REAL,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def import_match_metadata(
        self,
        match_id: str,
        match: dict[str, Any],
        *,
        source: str,
    ) -> None:
        home = match.get("home") or {}
        away = match.get("away") or {}
        quotations = match.get("quotations") or {}
        bets = (match.get("stats") or {}).get("bets") or {}
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO match_metadata VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    match_id,
                    str(match["championshipId"]) if match.get("championshipId") is not None else None,
                    match.get("season"),
                    match.get("gameWeekNumber"),
                    match.get("date"),
                    home.get("clubId"),
                    away.get("clubId"),
                    home.get("score"),
                    away.get("score"),
                    quotations.get("home"),
                    quotations.get("draw"),
                    quotations.get("away"),
                    bets.get("home"),
                    bets.get("draw"),
                    bets.get("away"),
                    source,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def import_forecasts(
        self,
        match_id: str,
        contest_id: str,
        forecasts: dict[str, Any],
        *,
        source: str,
    ) -> ImportedMatch:
        values = [forecast for forecast in forecasts.values() if isinstance(forecast, dict)]
        exact = [
            forecast
            for forecast in values
            if int(forecast.get("points", {}).get("extra") or 0) > 0
        ]
        actual = None
        if exact:
            actual = (int(exact[0]["homeScore"]), int(exact[0]["awayScore"]))
        score_counts: dict[tuple[int, int], int] = {}
        outcome_counts = {"home": 0, "draw": 0, "away": 0}
        for forecast in values:
            score = (int(forecast["homeScore"]), int(forecast["awayScore"]))
            score_counts[score] = score_counts.get(score, 0) + 1
            outcome_counts[outcome(*score)] += 1

        forecast_count = len(values)
        actual_outcome = outcome(*actual) if actual else None
        correct_count = outcome_counts[actual_outcome] if actual_outcome else None
        exact_count = score_counts.get(actual, 0) if actual else None
        rarity_level = _consistent_point_value(exact, "rarityLevel")
        extra_bonus = _consistent_point_value(exact, "extra")
        now = datetime.now(UTC).isoformat()
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    contest_id,
                    actual[0] if actual else None,
                    actual[1] if actual else None,
                    actual_outcome,
                    forecast_count,
                    correct_count,
                    exact_count,
                    exact_count / forecast_count if exact_count is not None and forecast_count else None,
                    exact_count / correct_count if exact_count is not None and correct_count else None,
                    rarity_level,
                    extra_bonus,
                    source,
                    now,
                ),
            )
            self.connection.execute(
                "DELETE FROM score_counts WHERE match_id = ? AND contest_id = ?",
                (match_id, contest_id),
            )
            for (home, away), count in score_counts.items():
                predicted_outcome = outcome(home, away)
                self.connection.execute(
                    """
                    INSERT INTO score_counts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        contest_id,
                        home,
                        away,
                        predicted_outcome,
                        count,
                        count / forecast_count,
                        count / outcome_counts[predicted_outcome],
                        int(actual == (home, away)),
                    ),
                )
        return ImportedMatch(
            match_id=match_id,
            contest_id=contest_id,
            forecast_count=forecast_count,
            actual_score=f"{actual[0]}-{actual[1]}" if actual else None,
            actual_score_share=exact_count / correct_count if exact_count is not None and correct_count else None,
            rarity_level=rarity_level,
            extra_bonus=extra_bonus,
        )

    def summary(self) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS matches,
                   SUM(forecast_count) AS forecasts,
                   SUM(CASE WHEN actual_home_score IS NOT NULL THEN 1 ELSE 0 END) AS resolved
            FROM matches
            """
        ).fetchone()
        levels = self.connection.execute(
            """
            SELECT rarity_level, extra_bonus, COUNT(*) AS matches,
                   AVG(exact_share_within_outcome) AS average_share
            FROM matches
            WHERE rarity_level IS NOT NULL
            GROUP BY rarity_level, extra_bonus
            ORDER BY rarity_level
            """
        ).fetchall()
        metadata_count = self.connection.execute(
            "SELECT COUNT(*) AS matches FROM match_metadata"
        ).fetchone()["matches"]
        return {
            "matches": row["matches"],
            "forecasts": row["forecasts"] or 0,
            "resolved_matches": row["resolved"] or 0,
            "matches_with_metadata": metadata_count,
            "rarity_levels": [dict(level) for level in levels],
        }


def import_chrome_cache(cache_dir: Path | str, database: HistoryDatabase) -> list[ImportedMatch]:
    imported: dict[tuple[str, str], ImportedMatch] = {}
    for path in Path(cache_dir).glob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for match in MATCH_URL.finditer(data):
            payload = _json_after(data, match.end())
            if not isinstance(payload, dict):
                continue
            match_id = match.group("match").decode()
            database.import_match_metadata(
                match_id,
                payload,
                source=f"chrome-cache:{path.name}",
            )
        for match in FORECAST_URL.finditer(data):
            payload = _json_after(data, match.end())
            if not isinstance(payload, dict):
                continue
            contest_id = match.group("contest").decode()
            match_id = match.group("match").decode()
            result = database.import_forecasts(
                match_id,
                contest_id,
                payload,
                source=f"chrome-cache:{path.name}",
            )
            imported[(match_id, contest_id)] = result
    return list(imported.values())


def scrape_matches(
    client: MppClient,
    database: HistoryDatabase,
    match_ids: Iterable[str],
    *,
    contest_id: str = "general",
    delay_seconds: float = 0.25,
    retries: int = 3,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[ImportedMatch]:
    imported = []
    for match_id in dict.fromkeys(match_ids):
        for attempt in range(retries + 1):
            try:
                match = client.get_match(match_id)
                if isinstance(match, dict):
                    database.import_match_metadata(match_id, match, source="mpp-api")
                forecasts = client.get_contest_match_forecasts(contest_id, match_id)
                if not any(isinstance(forecast, dict) for forecast in forecasts.values()):
                    break
                imported.append(
                    database.import_forecasts(
                        match_id,
                        contest_id,
                        forecasts,
                        source="mpp-api",
                    )
                )
                break
            except Exception as error:
                if attempt >= retries:
                    if on_error:
                        on_error(match_id, error)
                    break
                time.sleep(delay_seconds * (2 ** attempt))
        time.sleep(delay_seconds)
    return imported


def scrape_public_archive(
    client: MppClient,
    database: HistoryDatabase,
    championship_id: str | int,
    season: str | int,
    *,
    delay_seconds: float = 0.1,
    workers: int = 1,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[ImportedMatch]:
    standings = client.get_general_standings(championship_id, season)
    users = [
        item.get("user", {}).get("id")
        for item in standings.get("standings", [])
        if item.get("user", {}).get("id")
    ]
    def fetch_user(user_id: str) -> tuple[str, list[dict[str, Any]]]:
        collected_matches = []
        before_date = None
        seen_dates: set[str] = set()
        while True:
            page = None
            for attempt in range(6):
                try:
                    page = client.get_user_forecast_history(
                        championship_id,
                        user_id,
                        season,
                        before_date=before_date,
                    )
                    break
                except Exception as error:
                    status = getattr(error, "code", None)
                    if attempt < 5 and (status == 429 or status is None or status >= 500):
                        time.sleep(max(delay_seconds, 0.5) * (2**attempt))
                        continue
                    if on_error:
                        on_error(f"{championship_id}:{season}:{anonymous_user_id(user_id)}", error)
                    break
            if page is None:
                break
            for dated_matches in page.get("matchesByDate", {}).values():
                collected_matches.extend(dated_matches)
            next_date = page.get("nextDate")
            if not next_date or next_date in seen_dates:
                break
            seen_dates.add(next_date)
            before_date = next_date
            time.sleep(delay_seconds)
        return anonymous_user_id(user_id), collected_matches

    forecasts_by_match: dict[str, dict[str, Any]] = {}
    metadata_by_match: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(fetch_user, user_id) for user_id in users]
        for future in as_completed(futures):
            anonymous_id, matches = future.result()
            for match in matches:
                match_id = match.get("matchId")
                forecast = match.get("userForecast")
                if not match_id:
                    continue
                metadata_by_match[match_id] = match
                if isinstance(forecast, dict):
                    forecasts_by_match.setdefault(match_id, {})[anonymous_id] = forecast

    imported = []
    source = f"mpp-public-history:{championship_id}:{season}"
    for match_id, match in metadata_by_match.items():
        match.setdefault("season", int(season))
        database.import_match_metadata(match_id, match, source=source)
        forecasts = forecasts_by_match.get(match_id, {})
        if forecasts:
            imported.append(
                database.import_forecasts(match_id, "general", forecasts, source=source)
            )
    return imported


def _json_after(data: bytes, offset: int) -> Any | None:
    start = data.find(b"{", offset)
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(data[start:].decode("utf-8", errors="ignore"))
        return value
    except json.JSONDecodeError:
        return None


def _consistent_point_value(forecasts: list[dict[str, Any]], key: str) -> int | None:
    values = {
        int(forecast.get("points", {}).get(key))
        for forecast in forecasts
        if forecast.get("points", {}).get(key) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def anonymous_user_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]
