#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mpp_optimizer.history import (
    HistoryDatabase,
    import_chrome_cache,
    scrape_matches,
    scrape_public_archive,
)
from mpp_optimizer.mpp_client import MppClient


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "mpp_history.sqlite3"
DEFAULT_CACHE = (
    Path.home()
    / "Library/Caches/Google/Chrome/Default/Cache/Cache_Data"
)
INTERNATIONAL_ARCHIVES = (("8", "2022"), ("9", "2023"), ("19", "2025"))


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collecte historique anonymisée des pronostics MPP.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--import-chrome-cache", action="store_true")
    parser.add_argument("--chrome-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--match-id", action="append", default=[])
    parser.add_argument("--match-id-file", type=Path)
    parser.add_argument("--calendar", action="append", default=[], help="Identifiant du championnat à parcourir.")
    parser.add_argument(
        "--calendar-season",
        action="append",
        default=[],
        metavar="ID:SEASON",
        help="Calendrier d'une saison précise, par exemple 9:2023.",
    )
    parser.add_argument(
        "--international-archives",
        action="store_true",
        help="Tente Mondial 2022, Euro 2024 et CAN 2025.",
    )
    parser.add_argument(
        "--public-archive",
        action="append",
        default=[],
        metavar="ID:SEASON",
        help="Reconstruit une archive depuis les historiques publics du classement.",
    )
    parser.add_argument("--contest", default="general")
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    load_env()
    database = HistoryDatabase(args.database)
    try:
        imported = []
        if args.import_chrome_cache:
            imported.extend(import_chrome_cache(args.chrome_cache, database))
        calendar_seasons = [
            tuple(value.split(":", 1))
            for value in args.calendar_season
            if ":" in value
        ]
        if args.international_archives:
            calendar_seasons.extend(INTERNATIONAL_ARCHIVES)
        client = MppClient()
        if args.match_id or args.match_id_file or args.calendar or calendar_seasons:
            match_ids = list(args.match_id)
            if args.match_id_file:
                match_ids.extend(
                    line.strip()
                    for line in args.match_id_file.read_text().splitlines()
                    if line.strip()
                )
            for championship_id in args.calendar:
                try:
                    calendar = client.get_championship_calendar(championship_id)
                    match_ids.extend(_calendar_match_ids(calendar))
                except Exception as error:
                    print(f"ERREUR calendrier {championship_id}: {error}", file=sys.stderr, flush=True)
            for championship_id, season in calendar_seasons:
                try:
                    calendar = client.get_championship_calendar(championship_id, season)
                    match_ids.extend(_calendar_match_ids(calendar))
                except Exception as error:
                    print(
                        f"ERREUR calendrier {championship_id}, saison {season}: {error}",
                        file=sys.stderr,
                        flush=True,
                    )
            imported.extend(
                scrape_matches(
                    client,
                    database,
                    match_ids,
                    contest_id=args.contest,
                    delay_seconds=args.delay,
                    retries=args.retries,
                    on_error=lambda match_id, error: print(
                        f"ERREUR {match_id}: {error}", file=sys.stderr, flush=True
                    ),
                )
            )
        public_archives = [
            tuple(value.split(":", 1))
            for value in args.public_archive
            if ":" in value
        ]
        if args.international_archives:
            public_archives.extend(INTERNATIONAL_ARCHIVES)
        for championship_id, season in dict.fromkeys(public_archives):
            try:
                imported.extend(
                    scrape_public_archive(
                        client,
                        database,
                        championship_id,
                        season,
                        delay_seconds=args.delay,
                        workers=args.workers,
                        on_error=lambda context, error: print(
                            f"ERREUR archive publique {context}: {error}",
                            file=sys.stderr,
                            flush=True,
                        ),
                    )
                )
            except Exception as error:
                print(
                    f"ERREUR archive publique {championship_id}, saison {season}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
        print(json.dumps({"imported": [item.__dict__ for item in imported], "summary": database.summary()}, ensure_ascii=False, indent=2))
    finally:
        database.close()


def _calendar_match_ids(calendar: object) -> list[str]:
    match_ids: list[str] = []
    if isinstance(calendar, dict):
        for key, value in calendar.items():
            if key == "matchesIds" and isinstance(value, list):
                match_ids.extend(str(item) for item in value)
            else:
                match_ids.extend(_calendar_match_ids(value))
    elif isinstance(calendar, list):
        for value in calendar:
            match_ids.extend(_calendar_match_ids(value))
    return list(dict.fromkeys(match_ids))


if __name__ == "__main__":
    main()
