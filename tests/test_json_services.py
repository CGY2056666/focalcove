from __future__ import annotations

import json
import os
import stat as stat_module

import pytest
from flask import Flask

from app.services.auth_service import AuthService
from app.services.history_service import load_all, save_session
from app.services.user_service import get_user, mutate_user, save_user


def _isolated_app(tmp_path) -> Flask:
    app = Flask(__name__)
    app.config.update(
        USER_HISTORY_JSON_DIR=str(tmp_path / "history"),
        USER_DATA_JSON_DIR=str(tmp_path / "users"),
    )
    return app


def test_history_service_uses_configured_json_and_returns_newest_first(tmp_path):
    app = _isolated_app(tmp_path)
    with app.app_context():
        save_session({"session_id": "old", "end_time": 10}, "alice")
        save_session({"session_id": "new", "end_time": 20}, "alice")
        entries = load_all("alice")

    assert [entry["session_id"] for entry in entries] == ["new", "old"]
    saved = json.loads((tmp_path / "history" / "alice_history.json").read_text("utf-8"))
    assert {entry["session_id"] for entry in saved} == {"old", "new"}


def test_user_service_uses_configured_json_only(tmp_path):
    app = _isolated_app(tmp_path)
    with app.app_context():
        user = get_user("alice")
        user["total_points"] = 42
        save_user("alice", user)
        loaded = get_user("alice")

    assert loaded["total_points"] == 42
    assert (tmp_path / "users" / "alice_data.json").exists()


def test_user_service_never_overwrites_corrupt_runtime_data(tmp_path):
    app = _isolated_app(tmp_path)
    path = tmp_path / "users" / "alice_data.json"
    path.parent.mkdir(parents=True)
    original = "{broken-json"
    path.write_text(original, encoding="utf-8")

    with app.app_context():
        with pytest.raises(json.JSONDecodeError):
            get_user("alice")
        with pytest.raises(json.JSONDecodeError):
            mutate_user("alice", lambda data: data.__setitem__("total_points", 99))

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_runtime_json_files_are_owner_only(tmp_path):
    app = _isolated_app(tmp_path)
    with app.app_context():
        user = get_user("alice")
        save_user("alice", user)
        save_session({"session_id": "one", "end_time": 10}, "alice")

    auth_service = AuthService(tmp_path / "users.json", tmp_path / "auth_users")
    auth_service.register("bob", "testpass123")

    runtime_files = [
        tmp_path / "users.json",
        tmp_path / "users" / "alice_data.json",
        tmp_path / "history" / "alice_history.json",
    ]
    for path in runtime_files:
        assert stat_module.S_IMODE(path.stat().st_mode) == 0o600, path
