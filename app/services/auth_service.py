"""Shared username/password authentication and mobile bearer-token storage."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from app.middlewares.validation import validate_password, validate_username


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)


class AuthService:
    """Own the credential file used by both browser and mobile authentication."""

    def __init__(self, users_path: str | Path, user_data_dir: str | Path) -> None:
        self.users_path = Path(users_path)
        self.user_data_dir = Path(user_data_dir)
        self._lock = threading.RLock()

    @staticmethod
    def _safe_username(username: str) -> str:
        if not username or ".." in username or "/" in username or "\\" in username:
            raise ValueError("用户名包含非法字符")
        safe = "".join(
            ch for ch in username if ch.isalnum() or ch in "_-" or "一" <= ch <= "鿿"
        )
        if not safe or safe != username:
            raise ValueError("用户名包含非法字符")
        return safe

    def _load_users_unlocked(self) -> dict:
        try:
            data = json.loads(self.users_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _ensure_user_data(self, username: str) -> None:
        path = self.user_data_dir / f"{self._safe_username(username)}_data.json"
        if path.exists():
            return
        _atomic_write_json(
            path,
            {
                "total_points": 0,
                "den_items": ["base_floor", "base_wall"],
                "unlocked_items": ["base_floor", "base_wall"],
                "current_den": {
                    "floor": "base_floor",
                    "wall": "base_wall",
                    "decoration": [],
                    "ambience": "day",
                },
                "monitoring_permission": False,
            },
        )

    def register(self, username: str, password: str) -> dict:
        validate_username(username)
        validate_password(password)
        self._safe_username(username)
        with self._lock:
            users = self._load_users_unlocked()
            if username in users:
                raise ValueError("username_exists")
            users[username] = {
                "password": generate_password_hash(password),
                "created_at": time.time(),
            }
            _atomic_write_json(self.users_path, users)
            self._ensure_user_data(username)
            return {"username": username, "created_at": users[username]["created_at"]}

    def authenticate(self, username: str, password: str) -> bool:
        if not username or not password:
            return False
        with self._lock:
            users = self._load_users_unlocked()
            record = users.get(username)
            return bool(
                isinstance(record, dict)
                and isinstance(record.get("password"), str)
                and check_password_hash(record["password"], password)
            )


class MobileTokenStore:
    """Persist only SHA-256 token digests; raw bearer tokens are returned once."""

    def __init__(self, path: str | Path, *, ttl_seconds: int = 30 * 24 * 3600) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._lock = threading.RLock()

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _iso_timestamp(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _load_unlocked(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _expiry_epoch(record: dict) -> float:
        raw = record.get("expires_at", 0)
        try:
            return float(raw)
        except (TypeError, ValueError):
            if isinstance(raw, str):
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    return 0.0
            return 0.0

    def _prune_unlocked(self, records: dict[str, dict], now: float) -> bool:
        expired = [key for key, value in records.items() if self._expiry_epoch(value) <= now]
        for key in expired:
            records.pop(key, None)
        return bool(expired)

    def issue(self, username: str, *, now: float | None = None) -> dict:
        issued_at = time.time() if now is None else float(now)
        expires_at = issued_at + self.ttl_seconds
        token = secrets.token_urlsafe(32)
        digest = self.digest(token)
        with self._lock:
            records = self._load_unlocked()
            self._prune_unlocked(records, issued_at)
            records[digest] = {
                "username": username,
                "expires_at": self._iso_timestamp(expires_at),
            }
            _atomic_write_json(self.path, records)
        return {
            "token": token,
            "username": username,
            "expires_at": self._iso_timestamp(expires_at),
        }

    def resolve(self, token: str, *, now: float | None = None) -> str | None:
        if not token:
            return None
        checked_at = time.time() if now is None else float(now)
        with self._lock:
            records = self._load_unlocked()
            changed = self._prune_unlocked(records, checked_at)
            record = records.get(self.digest(token))
            if changed:
                _atomic_write_json(self.path, records)
            if not isinstance(record, dict):
                return None
            username = record.get("username")
            return username if isinstance(username, str) and username else None

    def revoke(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            records = self._load_unlocked()
            removed = records.pop(self.digest(token), None) is not None
            if removed:
                _atomic_write_json(self.path, records)
            return removed
