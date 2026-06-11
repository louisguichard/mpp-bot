import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mpp_optimizer.auth import FileTokenStore, MppTokenManager


class MemoryStore:
    def __init__(self, value):
        self.value = value

    def load(self):
        return self.value

    def save(self, tokens):
        self.value = tokens


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def token_with_expiry(expiry):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class AuthTests(unittest.TestCase):
    def test_valid_access_token_is_reused(self):
        access_token = token_with_expiry(time.time() + 3600)
        manager = MppTokenManager(MemoryStore({"access_token": access_token}))
        self.assertEqual(manager.access_token(), access_token)

    def test_refresh_is_persisted_and_keeps_rotating_token_when_not_returned(self):
        store = MemoryStore({"access_token": "expired", "refresh_token": "refresh-old"})
        manager = MppTokenManager(store)
        refreshed = token_with_expiry(time.time() + 3600)
        with patch("mpp_optimizer.auth.urlopen", return_value=FakeResponse({"access_token": refreshed})):
            self.assertEqual(manager.access_token(), refreshed)
        self.assertEqual(store.value["refresh_token"], "refresh-old")

    def test_file_store_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tokens.json"
            store = FileTokenStore(path)
            store.save({"refresh_token": "secret"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
