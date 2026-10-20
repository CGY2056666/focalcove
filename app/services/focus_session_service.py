"""专注会话的轻量应用服务。

Blueprint 只负责 HTTP 参数；这里编排内存会话、JSON 历史、推荐和积分。
"""
from __future__ import annotations

from collections import OrderedDict
import logging
import threading
from typing import Any

from app.helpers import (
    build_history_entry,
    load_recent_history_snapshot,
    serialize_history_entry,
)
from app.services.history_service import load_all, save_session
from app.services.user_service import mutate_user


logger = logging.getLogger(__name__)


class FocusSessionService:
    def __init__(
        self,
        session_manager,
        recommender,
        *,
        evaluation_collector=None,
        completed_cache_size: int = 64,
    ) -> None:
        self.session_manager = session_manager
        self.recommender = recommender
        self.evaluation_collector = evaluation_collector
        self.completed_cache_size = max(1, completed_cache_size)
        self._completed: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lifecycle_lock = threading.RLock()
        self._rewarded_session_ids: set[str] = set()
        self._completed_owners: dict[str, str] = {}

    def _remember_completed(self, session_id: str, payload: dict[str, Any]) -> None:
        self._completed[session_id] = payload
        self._completed.move_to_end(session_id)
        while len(self._completed) > self.completed_cache_size:
            expired_id, _ = self._completed.popitem(last=False)
            self._completed_owners.pop(expired_id, None)

    def _assert_owner(self, session_id: str, username: str) -> None:
        completed_owner = self._completed_owners.get(session_id)
        if completed_owner is not None:
            if completed_owner != username:
                raise PermissionError("session_forbidden")
            return
        sessions = getattr(self.session_manager, "sessions", None)
        # Small unit-test doubles predate ownership-aware managers; production
        # StreamingSessionManager always exposes the sessions mapping.
        if sessions is None:
            return
        get_state = getattr(self.session_manager, 'get_state', None)
        state = get_state(session_id) if callable(get_state) else sessions.get(session_id)
        if state is None:
            raise KeyError("session_not_found")
        if state.owner_username != username:
            raise PermissionError("session_forbidden")

    def current(self, username: str) -> dict[str, Any]:
        with self._lifecycle_lock:
            self.session_manager._prune()
            states_snapshot = getattr(self.session_manager, 'states_snapshot', None)
            states = (
                states_snapshot()
                if callable(states_snapshot)
                else tuple(self.session_manager.sessions.values())
            )
            for state in states:
                if state.owner_username == username and state.status == "running":
                    return self.session_manager.snapshot(state.session_id)
        raise KeyError("session_not_found")

    def assert_owner(self, session_id: str, *, username: str = '') -> None:
        self._assert_owner(session_id, username)

    def start(
        self,
        goal: str,
        *,
        username: str = "",
        duration_minutes: int | None = None,
        monitoring_mode: str = "medium",
    ) -> dict[str, Any]:
        with self._lifecycle_lock:
            if username:
                try:
                    self.current(username)
                except KeyError:
                    pass
                else:
                    raise RuntimeError("active_session_exists")
            payload = self.session_manager.start(
                goal,
                duration_minutes=duration_minutes,
                monitoring_mode=monitoring_mode,
                owner_username=username,
            )
        history = load_all(username)
        payload["duration_recommendation"] = self.recommender.recommend(
            goal,
            username=username,
            history=history,
        )
        return payload

    def add_frame(
        self,
        session_id: str,
        filename: str,
        file_bytes: bytes,
        *,
        frame_id: str | None = None,
        captured_at: float | None = None,
        username: str = "",
    ) -> dict[str, Any]:
        self._assert_owner(session_id, username)
        payload = self.session_manager.add_frame(
            session_id,
            filename,
            file_bytes,
            frame_id=frame_id,
            captured_at=captured_at,
        )
        collector = self.evaluation_collector
        if collector is not None:
            try:
                latest_item = payload.get("latest_item") or {}
                collector.collect(
                    image_bytes=file_bytes,
                    filename=filename,
                    session_id=session_id,
                    goal=str(payload.get("goal") or ""),
                    captured_at=latest_item.get("captured_at", captured_at),
                    frame_result=latest_item,
                )
            except Exception as exc:
                # 评测采集只是旁路功能，任何失败都不能改变实时评分响应。
                logger.warning("评测截图采集失败：%s", str(exc)[:160])
        return payload

    def snapshot(self, session_id: str, *, username: str = "") -> dict[str, Any]:
        self._assert_owner(session_id, username)
        return self.session_manager.snapshot(session_id)

    def complete(self, session_id: str, *, username: str = "") -> dict[str, Any]:
        # 完成与放弃共用生命周期锁，终态只能由其中一个操作原子决定。
        with self._lifecycle_lock:
            self._assert_owner(session_id, username)
            return self._complete_once(session_id, username=username)

    def complete_with_status(
        self, session_id: str, *, username: str = ""
    ) -> tuple[dict[str, Any], bool]:
        """Complete atomically and report whether this was an idempotent retry."""
        with self._lifecycle_lock:
            self._assert_owner(session_id, username)
            already_completed = session_id in self._completed
            return self._complete_once(session_id, username=username), already_completed

    def _complete_once(self, session_id: str, *, username: str = "") -> dict[str, Any]:
        cached = self._completed.get(session_id)
        if cached is not None:
            self._completed.move_to_end(session_id)
            return cached

        # 先生成完整结果但保留内存状态；JSON 保存成功后才真正丢弃。
        payload = self.session_manager.complete(session_id, discard=False)
        history_entry = build_history_entry(payload)
        history = [
            item
            for item in load_all(username)
            if str(item.get("session_id") or "") != session_id
        ]
        next_plan = self.recommender.recommend_next(
            history_entry,
            username=username,
            history=history,
        )
        history_entry["next_recommend"] = next_plan.get("next_recommend", {})
        history_entry["feedback_text"] = next_plan.get("feedback_text", "")
        history_entry["current_summary"] = next_plan.get("current_summary", {})
        saved_entry = save_session(history_entry, username)

        if session_id not in self._rewarded_session_ids:
            earned_points = int(saved_entry.get("earned_points", 0) or 0)

            def award_points(user_data: dict) -> None:
                user_data["total_points"] = (
                    int(user_data.get("total_points", 0) or 0) + earned_points
                )

            mutate_user(username, award_points)
            # 若后续组装响应失败，重试也不会在本进程内再次发放积分。
            self._rewarded_session_ids.add(session_id)

        payload["history_entry"] = serialize_history_entry(saved_entry)
        payload["next_duration_plan"] = next_plan
        payload["recent_history"] = load_recent_history_snapshot(username=username)
        payload["success_url"] = "/report"

        self.session_manager.discard(session_id)
        self._completed_owners[session_id] = username
        self._remember_completed(session_id, payload)
        return payload

    def reset(self, session_id: str | None, *, username: str = "") -> None:
        if not session_id:
            return
        with self._lifecycle_lock:
            self._assert_owner(session_id, username)
            if session_id in self._completed:
                return
            self.session_manager.discard(session_id)
