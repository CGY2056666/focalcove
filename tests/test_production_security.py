from __future__ import annotations

import pytest
from flask import jsonify, request

from app import create_app
from app.config import AppConfig


def _production_config(tmp_path, *, secret: str, trust_proxy: bool):
    return type(
        "ProductionConfig",
        (AppConfig,),
        {
            "TESTING": False,
            "FOCUS_ENV": "production",
            "SECRET_KEY": secret,
            "REQUIRE_HTTPS": True,
            "SESSION_COOKIE_SECURE": True,
            "FOCUS_TRUST_PROXY_HEADERS": trust_proxy,
            "USERS_JSON_PATH": str(tmp_path / "users.json"),
            "USER_DATA_JSON_DIR": str(tmp_path / "user_data"),
            "USER_HISTORY_JSON_DIR": str(tmp_path / "user_history"),
            "MOBILE_SESSIONS_JSON_PATH": str(tmp_path / "tokens.json"),
        },
    )


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "x" * 31,
        "focus-app-dev-secret",
        "replace_with_at_least_32_random_bytes",
        "placeholder-placeholder-placeholder-placeholder",
    ],
)
def test_production_rejects_short_default_and_placeholder_secrets(tmp_path, secret) -> None:
    config = _production_config(tmp_path, secret=secret, trust_proxy=False)
    with pytest.raises(RuntimeError, match="at least 32"):
        create_app(config)


def test_production_rejects_runtime_paths_inside_source_checkout() -> None:
    config = type(
        "UnsafeProductionConfig",
        (AppConfig,),
        {
            "TESTING": False,
            "FOCUS_ENV": "production",
            "SECRET_KEY": "valid-production-secret-with-more-than-32-characters",
            "REQUIRE_HTTPS": True,
            "SESSION_COOKIE_SECURE": True,
            "FOCUS_TRUST_PROXY_HEADERS": False,
        },
    )
    with pytest.raises(RuntimeError, match="runtime paths"):
        create_app(config)


def test_invalid_mobile_capture_configuration_fails_fast(tmp_path) -> None:
    config = _production_config(
        tmp_path,
        secret="capture-policy-production-key-123456789",
        trust_proxy=False,
    )
    config.MOBILE_CAPTURE_INTERVAL_SECONDS = 10
    config.MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS = 10
    with pytest.raises(RuntimeError, match="capture configuration"):
        create_app(config)


def test_production_health_is_minimal_and_mobile_responses_are_not_cached(tmp_path) -> None:
    config = _production_config(
        tmp_path,
        secret="minimal-health-production-key-123456789",
        trust_proxy=True,
    )
    app = create_app(config)
    try:
        client = app.test_client()
        health = client.get("/health")
        assert health.status_code == 200
        assert health.get_json() == {
            "status": "ok",
            "service": "focus-compass",
            "api_version": "v1",
        }
        response = client.get(
            "/api/v1/bootstrap",
            headers={"X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 401
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert response.headers["Pragma"] == "no-cache"
    finally:
        app.extensions["session_manager"]._frame_executor.shutdown(wait=True)


def test_proxy_headers_are_ignored_unless_explicitly_trusted(tmp_path) -> None:
    config = _production_config(
        tmp_path,
        secret="a-valid-random-production-key-1234567890",
        trust_proxy=False,
    )
    app = create_app(config)
    try:
        response = app.test_client().post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "wrongpass"},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "https_required"
    finally:
        app.extensions["session_manager"]._frame_executor.shutdown(wait=True)


def test_trusted_proxy_uses_proto_and_for_but_never_forwarded_host(tmp_path) -> None:
    config = _production_config(
        tmp_path,
        secret="another-valid-production-key-123456789",
        trust_proxy=True,
    )
    app = create_app(config)

    def request_details():
        return jsonify({"host": request.host, "remote_addr": request.remote_addr})

    app.add_url_rule("/api/v1/_request-details", view_func=request_details)
    try:
        response = app.test_client().get(
            "/api/v1/_request-details",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.50",
                "X-Forwarded-Host": "attacker.example",
            },
        )
        assert response.status_code == 200
        assert response.get_json() == {
            "host": "localhost",
            "remote_addr": "203.0.113.50",
        }
    finally:
        app.extensions["session_manager"]._frame_executor.shutdown(wait=True)


def test_unhandled_mobile_error_is_json_in_production(tmp_path) -> None:
    config = _production_config(
        tmp_path,
        secret="yet-another-valid-production-key-123456",
        trust_proxy=True,
    )
    app = create_app(config)

    def boom():
        raise RuntimeError("sensitive detail")

    app.add_url_rule("/api/v1/_boom", view_func=boom)
    try:
        response = app.test_client().get(
            "/api/v1/_boom",
            headers={"X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 500
        assert response.get_json() == {
            "error": {
                "code": "internal_error",
                "message": "服务器内部错误",
                "retryable": True,
            }
        }
        assert b"sensitive detail" not in response.data
    finally:
        app.extensions["session_manager"]._frame_executor.shutdown(wait=True)
