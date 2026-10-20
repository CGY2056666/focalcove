"""会话历史服务：原型阶段以 JSON 为唯一运行时数据源。"""
from __future__ import annotations

from pathlib import Path

from flask import current_app

from focus_engine.history_storage import (
    HISTORY_DIR,
    load_all_history,
    load_recent_history,
    save_session_history,
)


def _history_dir() -> Path:
    configured = current_app.config.get("USER_HISTORY_JSON_DIR")
    return Path(configured) if configured else HISTORY_DIR


def _sort_key(entry: dict) -> float:
    try:
        return float(
            entry.get("end_time")
            or entry.get("completed_at")
            or entry.get("updated_at")
            or 0.0
        )
    except (TypeError, ValueError):
        return 0.0


def save_session(entry: dict, username: str) -> dict:
    """Save one idempotent session record to the configured JSON directory."""

    return save_session_history(entry, username, _history_dir())


def load_recent(limit: int, username: str) -> list[dict]:
    return load_recent_history(limit, username, _history_dir())


def load_all(username: str) -> list[dict]:
    """Return newest first so latest-report callers cannot select an old row."""

    return sorted(
        load_all_history(username, _history_dir()),
        key=_sort_key,
        reverse=True,
    )
