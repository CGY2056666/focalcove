"""pytest fixtures"""
from __future__ import annotations

import pytest
from app import create_app
from app.config import AppConfig


@pytest.fixture
def app(tmp_path, monkeypatch):
    users_file = tmp_path / "users.json"
    users_file.write_text("{}", encoding="utf-8")
    user_data_dir = tmp_path / "user_data"
    history_dir = tmp_path / "user_history"
    mobile_sessions_file = tmp_path / "mobile_sessions.json"

    from focus_engine import history_storage

    monkeypatch.setattr(history_storage, "HISTORY_DIR", history_dir)

    class TestConfig(AppConfig):
        TESTING = True
        SECRET_KEY = "test-secret-key"
        USERS_JSON_PATH = str(users_file)
        USER_DATA_JSON_DIR = str(user_data_dir)
        USER_HISTORY_JSON_DIR = str(history_dir)
        MOBILE_SESSIONS_JSON_PATH = str(mobile_sessions_file)

    app = create_app(TestConfig)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """已登录的测试客户端"""
    with client:
        client.post(
            "/register",
            data={
                "username": "testuser",
                "password": "testpass123",
                "confirm_password": "testpass123",
            },
        )
        yield client
