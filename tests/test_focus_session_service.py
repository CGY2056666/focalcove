from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import pytest

from app.services.focus_session_service import FocusSessionService


class _Manager:
    def __init__(self):
        self.complete_calls = 0
        self.discarded: list[str] = []

    def complete(self, session_id, *, discard=True):
        self.complete_calls += 1
        return {"session": {"session_id": session_id}, "summary": {}, "items": []}

    def discard(self, session_id):
        self.discarded.append(session_id)


class _Recommender:
    def recommend_next(self, current, *, username=None, history=None):
        return {
            "next_recommend": {"base_recommend": 25},
            "feedback_text": "保持节奏",
            "current_summary": {},
        }


class _BlockingManager(_Manager):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, session_id, *, discard=True):
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release completion")
        return super().complete(session_id, discard=discard)


def _recording_mutate(saved_users: list[dict]):
    def mutate(username, mutation):
        data = {"total_points": 2}
        result = mutation(data)
        saved_users.append(dict(data))
        return data, result

    return mutate


def test_complete_is_idempotent_within_running_process(monkeypatch):
    from app.services import focus_session_service as module

    manager = _Manager()
    saved_users: list[dict] = []
    monkeypatch.setattr(module, "build_history_entry", lambda payload: {"session_id": "abc", "earned_points": 3})
    monkeypatch.setattr(module, "load_all", lambda username: [])
    monkeypatch.setattr(module, "save_session", lambda entry, username: dict(entry))
    monkeypatch.setattr(module, "mutate_user", _recording_mutate(saved_users))
    monkeypatch.setattr(module, "serialize_history_entry", lambda entry: dict(entry))
    monkeypatch.setattr(module, "load_recent_history_snapshot", lambda username=None: [])

    service = FocusSessionService(manager, _Recommender())
    first = service.complete("abc", username="tester")
    second = service.complete("abc", username="tester")

    assert first is second
    assert manager.complete_calls == 1
    assert manager.discarded == ["abc"]
    assert saved_users == [{"total_points": 5}]
    assert first["success_url"] == "/report"


def test_complete_retry_after_response_assembly_failure_does_not_double_points(monkeypatch):
    from app.services import focus_session_service as module

    manager = _Manager()
    saved_users: list[dict] = []
    recent_calls = 0

    def flaky_recent(username=None):
        nonlocal recent_calls
        recent_calls += 1
        if recent_calls == 1:
            raise RuntimeError("temporary read failure")
        return []

    monkeypatch.setattr(module, "build_history_entry", lambda payload: {"session_id": "abc", "earned_points": 3})
    monkeypatch.setattr(module, "load_all", lambda username: [])
    monkeypatch.setattr(module, "save_session", lambda entry, username: dict(entry))
    monkeypatch.setattr(module, "mutate_user", _recording_mutate(saved_users))
    monkeypatch.setattr(module, "serialize_history_entry", lambda entry: dict(entry))
    monkeypatch.setattr(module, "load_recent_history_snapshot", flaky_recent)

    service = FocusSessionService(manager, _Recommender())
    with pytest.raises(RuntimeError, match="temporary read failure"):
        service.complete("abc", username="tester")

    result = service.complete("abc", username="tester")

    assert result["history_entry"]["session_id"] == "abc"
    assert manager.complete_calls == 2
    assert manager.discarded == ["abc"]
    assert saved_users == [{"total_points": 5}]


def test_complete_retries_and_abandon_share_one_atomic_lifecycle(monkeypatch):
    from app.services import focus_session_service as module

    manager = _BlockingManager()
    saved_users: list[dict] = []
    monkeypatch.setattr(
        module,
        "build_history_entry",
        lambda payload: {"session_id": "abc", "earned_points": 3},
    )
    monkeypatch.setattr(module, "load_all", lambda username: [])
    monkeypatch.setattr(module, "save_session", lambda entry, username: dict(entry))
    monkeypatch.setattr(module, "mutate_user", _recording_mutate(saved_users))
    monkeypatch.setattr(module, "serialize_history_entry", lambda entry: dict(entry))
    monkeypatch.setattr(module, "load_recent_history_snapshot", lambda username=None: [])
    service = FocusSessionService(manager, _Recommender())

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(service.complete, "abc", username="tester")
        assert manager.entered.wait(timeout=1)
        retry = pool.submit(service.complete, "abc", username="tester")
        abandon = pool.submit(service.reset, "abc", username="tester")
        with pytest.raises(FutureTimeoutError):
            retry.result(timeout=0.05)
        with pytest.raises(FutureTimeoutError):
            abandon.result(timeout=0.05)
        assert manager.discarded == []
        manager.release.set()
        first_result = first.result(timeout=2)
        retry_result = retry.result(timeout=2)
        assert abandon.result(timeout=2) is None

    assert first_result is retry_result
    assert manager.complete_calls == 1
    assert manager.discarded == ["abc"]
    assert saved_users == [{"total_points": 5}]
