from __future__ import annotations

import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import load_dotenv
from .matching import normalize_name
from .odds_client import ApiFootballClient, OddsApiIoClient, PolymarketClient, polymarket_1x2


WEB_DIR = Path(__file__).resolve().parents[2] / "web"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EXTENSION_DIR = Path(__file__).resolve().parents[2] / "extension"


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/extension/"):
            self._file(EXTENSION_DIR / parsed.path.removeprefix("/extension/"))
            return
        if parsed.path == "/api/match-detail":
            query = parse_qs(parsed.query)
            self._json(_match_detail(query.get("home", ["France"])[0], query.get("away", ["Senegal"])[0]))
            return
        if parsed.path == "/api/compare":
            query = parse_qs(parsed.query)
            hours = int(query.get("hours", ["36"])[0])
            league = query.get("league", ["international-fifa-world-cup"])[0]
            self._json(
                {
                    "apiFootball": _safe_snapshot(lambda: ApiFootballClient().snapshot()),
                    "oddsApiIo": _safe_snapshot(
                        lambda: OddsApiIoClient().snapshot(hours=hours, league=league)
                    ),
                    "polymarket": _safe_snapshot(lambda: PolymarketClient().snapshot()),
                }
            )
            return
        if parsed.path == "/api/health":
            self._json({"status": "ok"})
            return
        if parsed.path == "/api/recommendations":
            path = DATA_DIR / "recommendations.json"
            self._json(json.loads(path.read_text()) if path.exists() else [])
            return
        super().do_GET()

    def _file(self, path: Path) -> None:
        if not path.is_file() or path.parent != EXTENSION_DIR:
            self.send_error(404)
            return
        body = path.read_bytes()
        content_type = "text/javascript" if path.suffix == ".js" else "text/css"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def _safe_snapshot(callback):
    try:
        return callback().to_dict()
    except Exception as error:
        return {"error": str(error), "events": [], "demo": False}


def _match_detail(home: str, away: str) -> dict:
    return {
        "match": {"home": home, "away": away},
        "apiFootball": _safe_detail(lambda: _api_football_detail(home, away)),
        "oddsApiIo": _safe_detail(lambda: _odds_api_io_detail(home, away)),
        "polymarket": _safe_detail(lambda: _polymarket_detail(home, away)),
    }


def _safe_detail(callback) -> dict:
    started = time.perf_counter()
    try:
        result = callback()
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        return result
    except Exception as error:
        return {"error": str(error), "latency_ms": round((time.perf_counter() - started) * 1000)}


def _api_football_detail(home: str, away: str) -> dict:
    client = ApiFootballClient()
    if not client.api_key:
        raise ValueError("API_FOOTBALL_KEY absente.")
    payload, headers, _ = client._get(
        "/fixtures", {"date": "2026-06-16"}, {"x-apisports-key": client.api_key}
    )
    event = next(
        (
            row for row in payload.get("response", [])
            if _same_match(
                home, away,
                row.get("teams", {}).get("home", {}).get("name", ""),
                row.get("teams", {}).get("away", {}).get("name", ""),
            )
        ),
        None,
    )
    return {
        "provider": "API-Football", "found": bool(event),
        "plan_errors": payload.get("errors") or {}, "quota": _quota(headers),
        "event": event, "raw": payload,
    }


def _odds_api_io_detail(home: str, away: str) -> dict:
    client = OddsApiIoClient()
    if not client.api_key:
        raise ValueError("ODDS_API_KEY absente.")
    events, event_headers, _ = client._get(
        "/events",
        {"apiKey": client.api_key, "sport": "football", "league": "international-fifa-world-cup", "status": "pending", "limit": 100},
    )
    event = next(
        (row for row in events if _same_match(home, away, row.get("home", ""), row.get("away", ""))),
        None,
    )
    if not event:
        return {"provider": "odds-api.io", "found": False, "event_count": len(events), "raw": events}
    selected, selected_headers, _ = client._get("/bookmakers/selected", {"apiKey": client.api_key})
    bookmaker_names = selected.get("bookmakers", [])
    odds, odds_headers, _ = client._get(
        "/odds",
        {"apiKey": client.api_key, "eventId": event["id"], "bookmakers": ",".join(bookmaker_names)},
    )
    markets = [
        {"bookmaker": bookmaker, **market}
        for bookmaker, rows in odds.get("bookmakers", {}).items()
        for market in rows if isinstance(market, dict)
    ]
    updates = [row.get("updatedAt") for row in markets if row.get("updatedAt")]
    return {
        "provider": "odds-api.io", "found": True, "event": event,
        "bookmakers": bookmaker_names, "urls": odds.get("urls", {}),
        "market_count": len(markets),
        "selection_count": sum(len(row.get("odds", [])) for row in markets),
        "freshest_update": max(updates, default=None), "oldest_update": min(updates, default=None),
        "moneyline": [row for row in markets if row.get("name") == "ML"],
        "correct_score": [row for row in markets if row.get("name") == "Correct Score"],
        "market_names": sorted({row.get("name", "") for row in markets}),
        "quota": _quota({**event_headers, **selected_headers, **odds_headers}), "raw": odds,
    }


def _polymarket_detail(home: str, away: str) -> dict:
    client = PolymarketClient()
    payload, _, _ = client._get(
        "/events/keyset", {"active": "true", "closed": "false", "limit": 100, "series_id": client.series_id}
    )
    events = payload.get("events", payload)
    event = next(
        (
            row for row in events
            if len(str(row.get("title", "")).split(" vs. ", 1)) == 2
            and _same_match(home, away, *str(row.get("title", "")).split(" vs. ", 1))
        ),
        None,
    )
    if not event:
        return {"provider": "Polymarket", "found": False, "event_count": len(events), "raw": payload}
    return {
        "provider": "Polymarket", "found": True,
        "event": {
            key: event.get(key) for key in (
                "id", "ticker", "slug", "title", "description", "endDate", "updatedAt",
                "liquidity", "volume", "volume24hr", "openInterest", "competitive",
                "enableOrderBook", "restricted", "resolutionSource",
            )
        },
        "probabilities": polymarket_1x2(event),
        "moneylines": [market for market in event.get("markets", []) if market.get("sportsMarketType") == "moneyline"],
        "raw": event,
    }


def _same_match(home: str, away: str, candidate_home: str, candidate_away: str) -> bool:
    return normalize_name(home) == normalize_name(candidate_home) and normalize_name(away) == normalize_name(candidate_away)


def _quota(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if "ratelimit" in key or "requests" in key}


def main() -> None:
    load_dotenv()
    address = ("127.0.0.1", 8765)
    print(f"MPP provider comparison: http://{address[0]}:{address[1]}")
    ThreadingHTTPServer(address, DashboardHandler).serve_forever()


if __name__ == "__main__":
    main()
