from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://connect.ligue1.fr/oauth/token"
CLIENT_ID = "grX5jWGWWQ4Uq91oe7KPNDZ96FS3jr0X"


class TokenStore(Protocol):
    def load(self) -> dict[str, Any]: ...

    def save(self, tokens: dict[str, Any]) -> None: ...


class FileTokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self, tokens: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens, indent=2) + "\n")
        self.path.chmod(0o600)


class GoogleSecretTokenStore:
    """Persist rotating OAuth tokens as Secret Manager versions."""

    def __init__(self, project_id: str, secret_id: str) -> None:
        from google.cloud import secretmanager

        self.client = secretmanager.SecretManagerServiceClient()
        self.secret_name = f"projects/{project_id}/secrets/{secret_id}"

    def load(self) -> dict[str, Any]:
        response = self.client.access_secret_version(
            request={"name": f"{self.secret_name}/versions/latest"}
        )
        return json.loads(response.payload.data.decode())

    def save(self, tokens: dict[str, Any]) -> None:
        self.client.add_secret_version(
            request={
                "parent": self.secret_name,
                "payload": {"data": json.dumps(tokens).encode()},
            }
        )


class MppTokenManager:
    def __init__(
        self,
        store: TokenStore,
        *,
        token_url: str = TOKEN_URL,
        client_id: str = CLIENT_ID,
        refresh_margin_seconds: int = 300,
    ) -> None:
        self.store = store
        self.token_url = token_url
        self.client_id = client_id
        self.refresh_margin_seconds = refresh_margin_seconds

    def access_token(self) -> str:
        tokens = self.store.load()
        access_token = tokens.get("access_token")
        if access_token and _jwt_expiry(access_token) > time.time() + self.refresh_margin_seconds:
            return access_token
        return self.refresh(tokens)

    def refresh(self, tokens: dict[str, Any] | None = None) -> str:
        current = tokens or self.store.load()
        refresh_token = current.get("refresh_token")
        if not refresh_token:
            raise ValueError("The bot token store does not contain a refresh_token.")
        body = urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": refresh_token,
            }
        ).encode()
        request = Request(
            self.token_url,
            data=body,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=20) as response:
            refreshed = json.load(response)
        merged = {**current, **refreshed}
        self.store.save(merged)
        return merged["access_token"]


def token_store_from_environment() -> TokenStore:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
    secret_id = os.getenv("MPP_BOT_TOKEN_SECRET")
    if project_id and secret_id:
        return GoogleSecretTokenStore(project_id, secret_id)
    path = Path(os.getenv("MPP_BOT_TOKEN_FILE", ".secrets/mpp-bot-tokens.json"))
    store = FileTokenStore(path)
    if not path.exists() and os.getenv("MPP_REFRESH_TOKEN"):
        store.save(
            {
                "access_token": os.getenv("MPP_TOKEN", ""),
                "refresh_token": os.environ["MPP_REFRESH_TOKEN"],
            }
        )
    return store


def _jwt_expiry(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0
