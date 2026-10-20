"""Non-image production smoke test for the Focus Compass mobile API."""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen


class SmokeFailure(RuntimeError):
    pass


def normalize_base_url(value: str, *, allow_http_localhost: bool = False) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Server URL cannot contain credentials, query parameters, or fragments")
    allowed_http = allow_http_localhost and parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }
    if parsed.scheme != "https" and not allowed_http:
        raise ValueError("Server URL must use HTTPS")
    if not parsed.hostname:
        raise ValueError("Server URL must include a hostname")
    return raw.rstrip("/") + "/"


def assert_error_envelope(payload: object, expected_code: str | None = None) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        raise SmokeFailure("Response does not use the mobile error envelope")
    error = payload["error"]
    if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
        raise SmokeFailure("Mobile error envelope is missing code or message")
    if not isinstance(error.get("retryable"), bool):
        raise SmokeFailure("Mobile error envelope is missing retryable")
    if expected_code is not None and error["code"] != expected_code:
        raise SmokeFailure(
            f"Expected error code {expected_code!r}, received {error['code']!r}"
        )


def assert_den_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise SmokeFailure("den: response is not an object")
    if not isinstance(payload.get("points"), int):
        raise SmokeFailure("den: points are missing")
    items = payload.get("items")
    config = payload.get("config")
    if not isinstance(items, list) or len(items) != 12:
        raise SmokeFailure("den: expected the 12 real room items")
    if not isinstance(config, dict) or not {
        "floor", "wall", "decoration", "ambience"
    } <= set(config):
        raise SmokeFailure("den: canonical room config is missing")
    item_ids = {
        item.get("id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if {"base_floor", "base_wall"} - item_ids or "coffee_voucher" in item_ids:
        raise SmokeFailure("den: catalog contains the wrong item set")


def bootstrap_path(goal: str) -> str:
    return f"/api/v1/bootstrap?goal={quote(goal, safe='')}"


class ApiClient:
    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.token: str | None = None
        self._ssl_context = ssl.create_default_context()

    def request(self, method: str, path: str, payload: object | None = None) -> tuple[int, object]:
        data = None
        headers = {"Accept": "application/json", "User-Agent": "focus-compass-smoke/1"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = urlopen(request, timeout=self.timeout, context=self._ssl_context)
            status = response.status
            body = response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
        except URLError as error:
            raise SmokeFailure(f"Cannot reach server: {error.reason}") from error
        try:
            decoded = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SmokeFailure(f"{method} {path} did not return JSON (HTTP {status})") from error
        return status, decoded


def _expect(status: int, expected: int, label: str) -> None:
    if status != expected:
        raise SmokeFailure(f"{label}: expected HTTP {expected}, received {status}")


def run_smoke(
    client: ApiClient,
    *,
    username: str | None = None,
    password: str | None = None,
    check_health: bool = True,
) -> list[str]:
    passed: list[str] = []
    if check_health:
        status, payload = client.request("GET", "/health")
        _expect(status, 200, "health")
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise SmokeFailure("health: response status is not ok")
        passed.append("health")

    status, payload = client.request("GET", "/api/v1/bootstrap")
    _expect(status, 401, "unauthenticated mobile contract")
    assert_error_envelope(payload, "invalid_token")
    passed.append("unauthenticated_error_envelope")

    if not username and not password:
        return passed
    if not username or not password:
        raise SmokeFailure("Both smoke username and password are required")

    created_session: str | None = None
    try:
        status, payload = client.request(
            "POST",
            "/api/v1/auth/login",
            {"username": username, "password": password},
        )
        _expect(status, 200, "login")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise SmokeFailure("login: access token is missing")
        client.token = payload["access_token"]
        passed.append("login")

        status, payload = client.request("GET", bootstrap_path("上线冒烟检查"))
        _expect(status, 200, "bootstrap")
        if not isinstance(payload, dict) or "capture_policy" not in payload:
            raise SmokeFailure("bootstrap: capture policy is missing")
        passed.append("bootstrap")

        status, payload = client.request("GET", "/api/v1/den")
        _expect(status, 200, "den")
        assert_den_payload(payload)
        passed.append("den")

        status, payload = client.request("GET", "/api/v1/focus-sessions/current")
        if status == 200:
            raise SmokeFailure(
                "The smoke account already has an active session; refusing to modify it"
            )
        _expect(status, 404, "current session")
        assert_error_envelope(payload, "session_not_found")
        passed.append("current_session_empty")

        status, payload = client.request(
            "POST",
            "/api/v1/focus-sessions",
            {
                "goal": "上线冒烟检查（不会上传截图）",
                "duration_minutes": 1,
                "monitoring_mode": "low",
            },
        )
        _expect(status, 201, "start session")
        if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str):
            raise SmokeFailure("start session: session_id is missing")
        created_session = payload["session_id"]
        passed.append("start_session")

        status, payload = client.request(
            "GET", f"/api/v1/focus-sessions/{created_session}"
        )
        _expect(status, 200, "session snapshot")
        if not isinstance(payload, dict) or payload.get("session_id") != created_session:
            raise SmokeFailure("session snapshot: wrong session_id")
        passed.append("session_snapshot")

        status, _ = client.request(
            "DELETE", f"/api/v1/focus-sessions/{created_session}"
        )
        _expect(status, 200, "discard session")
        created_session = None
        passed.append("discard_session")
    finally:
        if client.token and created_session:
            client.request("DELETE", f"/api/v1/focus-sessions/{created_session}")
        if client.token:
            status, _ = client.request("POST", "/api/v1/auth/logout")
            if status == 200:
                passed.append("logout")
            client.token = None
    return passed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test the non-image mobile API loop")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("FOCUS_API_BASE_URL", ""),
        help="HTTPS server root, for example https://your-domain.example/",
    )
    parser.add_argument("--username", default=os.environ.get("FOCUS_SMOKE_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("FOCUS_SMOKE_PASSWORD"))
    parser.add_argument("--skip-health", action="store_true")
    parser.add_argument("--allow-http-localhost", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        base_url = normalize_base_url(
            args.base_url, allow_http_localhost=args.allow_http_localhost
        )
        passed = run_smoke(
            ApiClient(base_url),
            username=args.username,
            password=args.password,
            check_health=not args.skip_health,
        )
    except (ValueError, SmokeFailure) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "checks": passed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
