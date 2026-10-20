from __future__ import annotations

import io
import json
import time

import pytest
from app.blueprints.mobile_api_bp import serialize_mobile_history
from app.middlewares.ratelimit import RateLimiter
from app.services.auth_service import MobileTokenStore
from focus_engine.models import FrameAnalysis


def _register(client, username: str) -> tuple[str, dict[str, str]]:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "mobilepass123"},
    )
    assert response.status_code == 201
    payload = response.get_json()
    token = payload["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_mobile_token_is_hashed_and_logout_revokes(app, client) -> None:
    token, headers = _register(client, "mobileuser")
    token_path = app.config["MOBILE_SESSIONS_JSON_PATH"]
    stored = json.loads(open(token_path, encoding="utf-8").read())
    assert token not in json.dumps(stored)
    assert MobileTokenStore.digest(token) in stored
    record = stored[MobileTokenStore.digest(token)]
    assert set(record) == {"username", "expires_at"}
    assert record["username"] == "mobileuser"

    assert client.get("/api/v1/bootstrap", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    expired = client.get("/api/v1/bootstrap", headers=headers)
    assert expired.status_code == 401
    assert expired.get_json()["error"]["code"] == "invalid_token"


def test_expired_token_is_rejected_and_pruned(tmp_path) -> None:
    path = tmp_path / "tokens.json"
    store = MobileTokenStore(path, ttl_seconds=30)
    issued = store.issue("alice", now=100.0)
    assert store.resolve(issued["token"], now=129.0) == "alice"
    assert store.resolve(issued["token"], now=131.0) is None
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_mobile_auth_errors_have_uniform_shape(client) -> None:
    response = client.get("/api/v1/history")
    assert response.status_code == 401
    assert response.get_json() == {
        "error": {
            "code": "invalid_token",
            "message": "登录已失效，请重新登录",
            "retryable": False,
        }
    }


def test_mobile_responses_are_never_cacheable(client) -> None:
    response = client.get("/api/v1/bootstrap")
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_mobile_http_errors_have_uniform_shape_without_changing_web_errors(client) -> None:
    missing = client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert missing.get_json() == {
        "error": {
            "code": "endpoint_not_found",
            "message": "接口不存在",
            "retryable": False,
        }
    }
    wrong_method = client.get("/api/v1/auth/login")
    assert wrong_method.status_code == 405
    assert wrong_method.get_json()["error"]["code"] == "method_not_allowed"
    assert client.get("/does-not-exist").is_json is False


def test_mobile_unhandled_error_still_propagates_while_testing(app, client) -> None:
    def boom():
        raise RuntimeError("diagnostic failure")

    app.add_url_rule("/api/v1/_test-boom", view_func=boom)
    with pytest.raises(RuntimeError, match="diagnostic failure"):
        client.get("/api/v1/_test-boom")


def test_mobile_auth_is_rate_limited_by_remote_ip(app, client) -> None:
    app.extensions["mobile_auth_rate_limiter"] = RateLimiter(2, 60)
    for _ in range(2):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "missing", "password": "wrongpass"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
        assert response.status_code == 401

    limited = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": "wrongpass"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert limited.status_code == 429
    assert limited.get_json() == {
        "error": {
            "code": "rate_limited",
            "message": "认证请求过于频繁，请稍后再试",
            "retryable": True,
        }
    }
    other_ip = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": "wrongpass"},
        environ_base={"REMOTE_ADDR": "203.0.113.11"},
    )
    assert other_ip.status_code == 401


def test_mobile_frame_rate_limit_is_scoped_by_username_and_session(app, client) -> None:
    _, alice_headers = _register(client, "ratealice")
    _, bob_headers = _register(client, "ratebob")
    alice_session = client.post(
        "/api/v1/focus-sessions",
        headers=alice_headers,
        json={"goal": "阅读", "duration_minutes": 25},
    ).get_json()["session_id"]
    bob_session = client.post(
        "/api/v1/focus-sessions",
        headers=bob_headers,
        json={"goal": "写作", "duration_minutes": 25},
    ).get_json()["session_id"]
    app.extensions["mobile_frame_rate_limiter"] = RateLimiter(1, 60)

    alice_first = client.post(
        f"/api/v1/focus-sessions/{alice_session}/frames", headers=alice_headers
    )
    alice_limited = client.post(
        f"/api/v1/focus-sessions/{alice_session}/frames", headers=alice_headers
    )
    bob_first = client.post(
        f"/api/v1/focus-sessions/{bob_session}/frames", headers=bob_headers
    )

    assert alice_first.status_code == bob_first.status_code == 400
    assert alice_limited.status_code == 429
    assert alice_limited.get_json()["error"]["code"] == "rate_limited"
    assert alice_limited.get_json()["error"]["retryable"] is True


def test_unknown_frame_sessions_do_not_allocate_limiter_keys(app, client) -> None:
    _, headers = _register(client, 'limiterowner')
    limiter = RateLimiter(1, 60, max_keys=4)
    app.extensions['mobile_frame_rate_limiter'] = limiter

    for index in range(20):
        session_id = f'{index + 1000:012x}'
        response = client.post(
            f'/api/v1/focus-sessions/{session_id}/frames',
            headers=headers,
        )
        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'session_not_found'

    assert limiter._requests == {}


def test_mobile_history_exposes_completed_at_and_legacy_ended_at() -> None:
    item = serialize_mobile_history(
        {
            "session_id": "abc123",
            "goal": "阅读",
            "started_at": 100.0,
            "completed_at": 200.0,
        }
    )
    assert item["completed_at"] == 200.0
    assert item["ended_at"] == 200.0


def test_one_active_session_per_user_and_current_recovery(app, client) -> None:
    _, headers = _register(client, "activeuser")
    started = client.post(
        "/api/v1/focus-sessions",
        headers=headers,
        json={"goal": "学习 Python", "duration_minutes": 25, "monitoring_mode": "medium"},
    )
    assert started.status_code == 201
    payload = started.get_json()
    assert {
        "session_id",
        "goal",
        "duration_minutes",
        "started_at",
        "remaining_seconds",
        "status",
        "latest_frame",
        "rolling_summary",
        "alert_event",
        "capture_policy",
    } <= set(payload)
    assert payload["capture_policy"] == {
        "first_immediate": True,
        "interval_seconds": 20,
        "max_edge_pixels": 1024,
        "jpeg_quality": 72,
        "request_timeout_seconds": 18,
    }

    conflict = client.post(
        "/api/v1/focus-sessions",
        headers=headers,
        json={"goal": "另一个目标", "duration_minutes": 25},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["code"] == "active_session_exists"
    current = client.get("/api/v1/focus-sessions/current", headers=headers)
    assert current.status_code == 200
    assert current.get_json()["session_id"] == payload["session_id"]
    app.extensions["session_manager"].sessions.clear()
    interrupted = client.get("/api/v1/focus-sessions/current", headers=headers)
    assert interrupted.status_code == 404
    assert interrupted.get_json()["error"]["code"] == "session_not_found"
    app.extensions["session_manager"]._frame_executor.shutdown(wait=True)


def test_capture_policy_uses_effective_server_configuration(app, client) -> None:
    app.config.update(
        MOBILE_CAPTURE_INTERVAL_SECONDS=30,
        MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS=15,
        MOBILE_CAPTURE_MAX_EDGE_PIXELS=900,
        MOBILE_CAPTURE_JPEG_QUALITY=68,
    )
    _, headers = _register(client, "capturepolicy")
    response = client.get("/api/v1/bootstrap", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["capture_policy"] == {
        "first_immediate": True,
        "interval_seconds": 30,
        "max_edge_pixels": 900,
        "jpeg_quality": 68,
        "request_timeout_seconds": 15,
    }


def test_cross_user_access_is_forbidden(app, client) -> None:
    _, alice_headers = _register(client, "alice")
    _, bob_headers = _register(client, "bob")
    started = client.post(
        "/api/v1/focus-sessions",
        headers=alice_headers,
        json={"goal": "阅读", "duration_minutes": 25},
    ).get_json()
    session_id = started["session_id"]

    assert client.get(f"/api/v1/focus-sessions/{session_id}", headers=bob_headers).status_code == 403
    assert client.post(f"/api/v1/focus-sessions/{session_id}/complete", headers=bob_headers).status_code == 403
    assert client.delete(f"/api/v1/focus-sessions/{session_id}", headers=bob_headers).status_code == 403
    assert client.delete(f"/api/v1/focus-sessions/{session_id}", headers=alice_headers).status_code == 200
    app.extensions["session_manager"]._frame_executor.shutdown(wait=True)


def test_mobile_frame_and_complete_are_idempotent(app, client, monkeypatch) -> None:
    _, headers = _register(client, "frameuser")
    analyzer = app.extensions["analyzer"]
    calls = 0

    def fake_analyze(profile, filename, file_bytes, **kwargs):
        nonlocal calls
        calls += 1
        return FrameAnalysis(
            index=0,
            filename=filename,
            image_valid=True,
            frame_id=str(kwargs.get("frame_id") or ""),
            captured_at=float(kwargs.get("captured_at") or time.time()),
            processed_at=time.time(),
            state="focused",
            source="fake",
            category_type="focus",
            category_label="代码编辑器",
            focus_score=85.0,
            focus_probability=0.85,
            relevance_score=0.85,
            base_relevance_score=0.85,
            score_confidence=0.9,
            distraction_score=0.05,
            scoring_source="fake",
            decision_reason="正在学习",
            base_decision_reason="正在学习",
        )

    monkeypatch.setattr(analyzer, "analyze_frame", fake_analyze)
    session_id = client.post(
        "/api/v1/focus-sessions",
        headers=headers,
        json={"goal": "学习 Python", "duration_minutes": 25, "monitoring_mode": "low"},
    ).get_json()["session_id"]

    def submit_frame():
        return client.post(
            f"/api/v1/focus-sessions/{session_id}/frames",
            headers=headers,
            data={
                "screenshot": (io.BytesIO(b"fake-image"), "screen.jpg"),
                "frame_id": "frame-stable-1",
                "captured_at": str(time.time()),
            },
            content_type="multipart/form-data",
        )

    first_frame = submit_frame()
    second_frame = submit_frame()
    assert first_frame.status_code == second_frame.status_code == 200
    assert calls == 1
    assert first_frame.get_json()["latest_frame"]["frame_id"] == "frame-stable-1"
    assert {
        "frame_id", "status", "score", "explanation", "captured_at"
    } == set(first_frame.get_json()["latest_frame"])
    assert "items" not in first_frame.get_json()

    first_complete = client.post(
        f"/api/v1/focus-sessions/{session_id}/complete", headers=headers
    )
    second_complete = client.post(
        f"/api/v1/focus-sessions/{session_id}/complete", headers=headers
    )
    assert first_complete.status_code == second_complete.status_code == 200
    assert first_complete.get_json()["already_completed"] is False
    assert second_complete.get_json()["already_completed"] is True
    assert first_complete.get_json()["report"] == second_complete.get_json()["report"]
    assert {
        "focus_score",
        "focused_seconds",
        "distracted_seconds",
        "effective_coverage",
        "coverage_ratio",
        "reliable",
        "summary",
    } == set(first_complete.get_json()["report"])
    app.extensions["session_manager"]._frame_executor.shutdown(wait=True)


def test_mobile_runtime_uses_isolated_configured_paths(app, client) -> None:
    _, headers = _register(client, "freshuser")
    assert client.get("/api/v1/history", headers=headers).get_json() == {"items": []}
    assert app.config["MOBILE_SESSIONS_JSON_PATH"].endswith("mobile_sessions.json")
    assert app.config["USERS_JSON_PATH"].endswith("users.json")


def test_browser_session_endpoints_also_enforce_owner(app) -> None:
    alice = app.test_client()
    bob = app.test_client()
    alice.post(
        "/register",
        data={
            "username": "browseralice",
            "password": "browserpass123",
            "confirm_password": "browserpass123",
        },
    )
    started = alice.post(
        "/api/session/start",
        json={"goal": "阅读", "duration_minutes": 25},
    )
    assert started.status_code == 200
    session_id = started.get_json()["session"]["session_id"]

    bob.post(
        "/register",
        data={
            "username": "browserbob",
            "password": "browserpass123",
            "confirm_password": "browserpass123",
        },
    )
    forbidden = bob.get(f"/api/session/{session_id}")
    assert forbidden.status_code == 403
    assert forbidden.get_json() == {"error": "session_forbidden"}
    app.extensions["session_manager"]._frame_executor.shutdown(wait=True)
