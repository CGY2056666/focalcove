"""用户积分与小屋数据服务：JSON 是原型的唯一运行时数据源。"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from flask import current_app

from app.services.shop_catalog import DEN_ITEM_BY_ID, normalise_den_config


_DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "user_data"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_T = TypeVar("_T")


def _default_user_data() -> dict:
    return {
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
    }


def _sanitize_username(username: str | None) -> str:
    if not username:
        return "default"
    if ".." in username or "/" in username or "\\" in username:
        raise ValueError("用户名包含非法字符")
    safe = "".join(ch for ch in username if ch.isalnum() or ch in "_-" or "一" <= ch <= "鿿")
    return safe or "default"


def _user_data_dir() -> Path:
    configured = current_app.config.get("USER_DATA_JSON_DIR")
    return Path(configured) if configured else _DEFAULT_DIR


def _user_file(username: str | None) -> Path:
    return _user_data_dir() / f"{_sanitize_username(username)}_data.json"


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _normalise(data: dict | None) -> dict:
    result = _default_user_data()
    if isinstance(data, dict):
        result.update(data)
    result["total_points"] = max(0, int(result.get("total_points", 0) or 0))
    raw_unlocked = result.get("unlocked_items") or []
    if not isinstance(raw_unlocked, list):
        raw_unlocked = []
    unlocked_items = [
        item_id
        for index, item_id in enumerate(raw_unlocked)
        if isinstance(item_id, str) and item_id not in raw_unlocked[:index]
    ]
    for base_item in ("base_floor", "base_wall"):
        if base_item not in unlocked_items:
            unlocked_items.insert(0 if base_item == "base_floor" else 1, base_item)
    result["unlocked_items"] = unlocked_items

    raw_den_items = result.get("den_items") or []
    if not isinstance(raw_den_items, list):
        raw_den_items = []
    den_items: list[str] = []
    for item_id in [*raw_den_items, *unlocked_items]:
        if isinstance(item_id, str) and item_id in DEN_ITEM_BY_ID and item_id not in den_items:
            den_items.append(item_id)
    result["den_items"] = den_items
    result["current_den"] = normalise_den_config(
        result.get("current_den"),
        unlocked_items,
    )
    result["monitoring_permission"] = bool(result.get("monitoring_permission", False))
    return result


def get_user(username: str | None) -> dict:
    path = _user_file(username)
    lock = _lock_for(path)
    with lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = None
    return _normalise(data)


def save_user(username: str, data: dict) -> None:
    path = _user_file(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(path)
    payload = json.dumps(_normalise(data), ensure_ascii=False, indent=2)
    with lock:
        temporary = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)


def mutate_user(username: str, mutation: Callable[[dict], _T]) -> tuple[dict, _T]:
    """Atomically load, mutate and persist one user's runtime data."""
    path = _user_file(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(path)
    with lock:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = None
        data = _normalise(raw)
        result = mutation(data)
        normalised = _normalise(data)
        payload = json.dumps(normalised, ensure_ascii=False, indent=2)
        temporary = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    return normalised, result
