"""认证模块测试"""
from __future__ import annotations

import json


class TestRegistration:
    def test_register_page_renders(self, client):
        r = client.get("/register")
        assert r.status_code == 200

    def test_register_success(self, client):
        r = client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "mypassword123",
                "confirm_password": "mypassword123",
            },
        )
        assert r.status_code == 200

    def test_register_password_mismatch(self, client):
        r = client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "mypassword123",
                "confirm_password": "different",
            },
        )
        assert "不一致".encode() in r.data

    def test_register_weak_password(self, client):
        r = client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "123",
                "confirm_password": "123",
            },
        )
        assert r.status_code == 200

    def test_register_existing_user(self, auth_client):
        r = auth_client.post(
            "/register",
            data={
                "username": "testuser",
                "password": "otherpass123",
                "confirm_password": "otherpass123",
            },
        )
        assert "已存在".encode() in r.data

    def test_register_path_traversal_rejected(self, client):
        r = client.post(
            "/register",
            data={
                "username": "../../etc/passwd",
                "password": "testpass123",
                "confirm_password": "testpass123",
            },
        )
        assert "注册成功".encode() not in r.data


class TestLogin:
    def test_login_page_renders(self, client):
        r = client.get("/login")
        assert r.status_code == 200

    def test_login_success(self, auth_client):
        r = auth_client.get("/", follow_redirects=True)
        # 已登录用户访问首页返回200
        assert r.status_code == 200

    def test_login_wrong_password(self, client):
        client.post(
            "/register",
            data={
                "username": "logintest",
                "password": "correct123",
                "confirm_password": "correct123",
            },
        )
        client.get("/logout")
        r = client.post(
            "/login",
            data={"username": "logintest", "password": "wrongpass1"},
        )
        assert "错误".encode() in r.data

    def test_protected_route_redirects(self, client):
        r = client.get("/")
        assert r.status_code == 302
        assert b"/login" in r.data

    def test_logout_discards_owned_active_session(self, app, auth_client):
        started = auth_client.post(
            "/api/session/start",
            json={"goal": "阅读", "duration_minutes": 25},
        )
        session_id = started.get_json()["session"]["session_id"]
        assert session_id in app.extensions["session_manager"].sessions

        response = auth_client.get("/logout")

        assert response.status_code == 302
        assert session_id not in app.extensions["session_manager"].sessions


class TestBrowserAuthRateLimit:
    def test_login_is_rate_limited_after_repeated_attempts(self, client):
        for _ in range(10):
            response = client.post(
                "/login",
                data={"username": "nobody", "password": "wrongpass1"},
            )
            assert response.status_code == 200

        response = client.post(
            "/login",
            data={"username": "nobody", "password": "wrongpass1"},
        )

        assert response.status_code == 429
        assert "尝试过于频繁".encode() in response.data

    def test_register_is_rate_limited_after_repeated_attempts(self, client):
        for index in range(10):
            response = client.post(
                "/register",
                data={
                    "username": f"ratelimit{index}",
                    "password": "",
                    "confirm_password": "",
                },
            )
            assert response.status_code == 200

        response = client.post(
            "/register",
            data={
                "username": "ratelimit_final",
                "password": "",
                "confirm_password": "",
            },
        )

        assert response.status_code == 429
        assert "尝试过于频繁".encode() in response.data


class TestPageRoutes:
    def test_rules_page_renders_for_authenticated_user(self, client, monkeypatch):
        from app.blueprints import pages_bp

        monkeypatch.setattr(
            pages_bp,
            "runtime_snapshot",
            lambda *args, **kwargs: {"user_points": 0},
        )

        with client.session_transaction() as sess:
            sess["username"] = "routeuser"
            sess.pop("running_session_id", None)

        r = client.get("/rules")
        assert r.status_code == 200
        assert "使用前须知".encode() in r.data
        assert "查看完整使用手册".encode() in r.data
