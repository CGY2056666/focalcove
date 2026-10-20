from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from typing import Dict, List

HISTORY_DIR = Path(__file__).parent.parent / "user_history"
_JSON_LOCKS: dict[str, threading.Lock] = {}
_LOCK_DICT_LOCK = threading.Lock()


def _sanitize_username(username: str | None) -> str:
    if not username:
        return "default"
    if ".." in username or "/" in username or "\\" in username:
        raise ValueError("用户名包含非法字符")
    safe = "".join(ch for ch in username if ch.isalnum() or ch in "_-" or "一" <= ch <= "鿿")
    return safe or "default"


def _resolve_history_dir(history_dir: str | Path | None = None) -> Path:
    return Path(history_dir) if history_dir else HISTORY_DIR


def _ensure_history_dir(history_dir: str | Path | None = None) -> Path:
    directory = _resolve_history_dir(history_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _get_lock(filepath: str) -> threading.Lock:
    with _LOCK_DICT_LOCK:
        if filepath not in _JSON_LOCKS:
            _JSON_LOCKS[filepath] = threading.Lock()
        return _JSON_LOCKS[filepath]


def get_history_file(username: str | None = None, history_dir: str | Path | None = None) -> Path:
    safe = _sanitize_username(username)
    return _resolve_history_dir(history_dir) / f"{safe}_history.json"


def init_history_file(username: str | None = None, history_dir: str | Path | None = None) -> None:
    _ensure_history_dir(history_dir)
    history_file = get_history_file(username, history_dir)
    if not history_file.exists():
        history_file.write_text("[]", encoding="utf-8")
        if os.name == "posix":
            os.chmod(history_file, 0o600)


def _read_history(username: str | None = None, history_dir: str | Path | None = None) -> List[Dict]:
    init_history_file(username, history_dir)
    history_file = get_history_file(username, history_dir)
    lock = _get_lock(str(history_file))
    with lock:
        try:
            with open(history_file, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            data = []
    return data if isinstance(data, list) else []


def _write_history(
    history: List[Dict],
    username: str | None = None,
    history_dir: str | Path | None = None,
) -> None:
    _ensure_history_dir(history_dir)
    history_file = get_history_file(username, history_dir)
    lock = _get_lock(str(history_file))
    with lock:
        temporary = history_file.with_suffix(f"{history_file.suffix}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, history_file)


def _history_sort_key(session: Dict) -> float:
    try:
        return float(session.get("end_time") or session.get("completed_at") or session.get("updated_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def save_session_history(
    session_data: Dict,
    username: str | None = None,
    history_dir: str | Path | None = None,
) -> Dict:
    history = _read_history(username, history_dir)
    entry = dict(session_data or {})
    session_id = str(entry.get("session_id") or f"{entry.get('goal', '')}_{entry.get('end_time', '')}")
    entry["session_id"] = session_id
    entry["earned_points"] = entry.get("earned_points", 0)
    history = [item for item in history if str(item.get("session_id")) != session_id]
    history.append(entry)
    history.sort(key=_history_sort_key)
    _write_history(history, username, history_dir)
    return entry


def load_all_history(
    username: str | None = None,
    history_dir: str | Path | None = None,
) -> List[Dict]:
    return _read_history(username, history_dir)


def load_recent_history(
    limit: int = 6,
    username: str | None = None,
    history_dir: str | Path | None = None,
) -> List[Dict]:
    history = sorted(load_all_history(username, history_dir), key=_history_sort_key, reverse=True)
    return history[: max(0, int(limit))]


def load_history_by_goal_type(
    goal_type: str,
    username: str | None = None,
    history_dir: str | Path | None = None,
) -> List[Dict]:
    return [
        session
        for session in load_all_history(username, history_dir)
        if session.get("goal_type") == goal_type
    ]
