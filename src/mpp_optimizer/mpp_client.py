from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MppClient:
    """Small MPP API client. Writes require an explicit opt-in."""

    def __init__(
        self,
        token: str | None = None,
        *,
        allow_write: bool = False,
        base_url: str = "https://api.mpp.football",
    ) -> None:
        self.token = token or os.getenv("MPP_TOKEN")
        self.allow_write = allow_write
        self.base_url = base_url.rstrip("/")

    def get_current_matches(self) -> Any:
        return self.get("/championships-current-matches")

    def get_clubs(self) -> Any:
        return self.get("/championship-clubs")

    def get_match(self, match_id: str) -> Any:
        return self.get(f"/championship-match/{match_id}")

    def get_user_forecasts(self, entity_id: str) -> Any:
        return self.get(f"/user-match-forecasts/{entity_id}")

    def get_contest_match_forecasts(self, contest_id: str, match_id: str) -> Any:
        return self.get(f"/user-match-forecasts/contest/{contest_id}/match/{match_id}")

    def get_championship_calendar(
        self, championship_id: str | int, season: str | int | None = None
    ) -> Any:
        # `season` causes a server error on older international archives;
        # `seasonYear` works for both historical and current calendars.
        suffix = f"?seasonYear={season}" if season is not None else ""
        return self.get(f"/championship-calendar/{championship_id}{suffix}")

    def get_general_standings(self, championship_id: str | int, season: str | int) -> Any:
        query = urlencode({"championshipId": championship_id, "season": season})
        return self.get(f"/general-standings/top-users-standings?{query}")

    def get_user_forecast_history(
        self,
        championship_id: str | int,
        user_id: str,
        season: str | int,
        *,
        before_date: str | None = None,
    ) -> Any:
        parameters = {
            "championshipId": championship_id,
            "userId": user_id,
            "season": season,
        }
        if before_date:
            parameters["beforeDate"] = before_date
        return self.get(
            f"/user-match-forecasts/championship/{championship_id}/history?"
            f"{urlencode(parameters)}"
        )

    def set_forecast(
        self,
        match_id: str,
        home_score: int,
        away_score: int,
        *,
        entity_id: str = "general",
        origin_page: str = "home",
    ) -> Any:
        if not self.allow_write:
            raise PermissionError("MPP writes are disabled. Pass allow_write=True explicitly.")
        return self._request(
            "PATCH",
            f"/user-match-forecasts/entity/{entity_id}/match/{match_id}",
            {
                "homeScore": home_score,
                "awayScore": away_score,
                "originPage": origin_page,
            },
        )

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.token:
            raise ValueError("Set MPP_TOKEN in the environment.")
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "application": "mppLfp",
                "app-context": "internationalEvent",
                "platform": "web",
                "client-language": "fr-FR",
                "client-version": "11.10.0",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 401:
                raise PermissionError(
                    "Le token MPP n'est plus valide. Régénérer MPP_TOKEN avec le refresh token."
                ) from error
            raise
