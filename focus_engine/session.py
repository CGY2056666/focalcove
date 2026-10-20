# 本部分使用 AI 辅助进行了编程：Qwen3.5plus 2026.04.02
from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from .config import AnalyzerConfig, DEFAULT_CONFIG
from .goal_profiles import build_goal_profile
from .models import FrameAnalysis, GoalProfile
from .pipeline import FocusAnalyzer
from .scoring import (
    WINDOW_CONSISTENCY_HISTORY,
    build_summary,
    expected_observation_count,
    finalize_frame_scores,
)
from .scoring_policy import SCORE_VERSION, ScoringPolicy, load_scoring_policy

logger = logging.getLogger(__name__)

VALID_MONITORING_MODES = {"low", "medium", "high"}
VALID_SCORE_STATES = {"focused", "uncertain", "distracted"}


@dataclass
class SessionState:
    session_id: str
    goal: str
    profile: GoalProfile
    created_at: float
    updated_at: float
    duration_seconds: int
    owner_username: str = ""
    monitoring_mode: str = "medium"
    status: str = "running"
    completed_at: float | None = None
    frames: list[FrameAnalysis] = field(default_factory=list)
    ai_advice: str = ""
    last_frame_hash: str = ""
    last_model_analysis_at: float | None = None
    last_alert_at: float | None = None
    alert_count: int = 0
    consecutive_distracted: int = 0
    consecutive_focused: int = 0
    high_alert_armed: bool = True
    seen_frame_ids: set[str] = field(default_factory=set)
    lock: Any = field(default_factory=threading.RLock, repr=False)


class StreamingSessionManager:
    def __init__(self, analyzer: FocusAnalyzer, config: AnalyzerConfig = DEFAULT_CONFIG) -> None:
        self.analyzer = analyzer
        self.config = config
        analyzer_policy = getattr(analyzer, "scoring_policy", None)
        self.scoring_policy = (
            analyzer_policy
            if isinstance(analyzer_policy, ScoringPolicy)
            else load_scoring_policy(config.scoring_policy_path).policy
        )
        self.sessions: dict[str, SessionState] = {}
        # Lock ordering: code may acquire SessionState.lock and then this lock,
        # but must never hold this lock while waiting for a SessionState.lock.
        # Global dictionary operations therefore take snapshots/lookups only.
        self._sessions_lock = threading.RLock()
        # 超时任务自身还受 16 秒模型超时约束；此处额外保证 17 秒帧处理硬截止。
        self._frame_executor = ThreadPoolExecutor(
            max_workers=max(2, min(config.max_workers, 4)),
            thread_name_prefix="focus-frame",
        )

    def _prune(self) -> None:
        now = time.time()
        with self._sessions_lock:
            candidates = [
                (session_id, state)
                for session_id, state in self.sessions.items()
                if now - state.updated_at > self.config.session_ttl_seconds
            ]
        for session_id, state in candidates:
            # A frame can refresh updated_at while pruning is in progress.
            # Recheck under the per-session lock before removing the state.
            with state.lock:
                if now - state.updated_at <= self.config.session_ttl_seconds:
                    continue
                with self._sessions_lock:
                    if self.sessions.get(session_id) is state:
                        self.sessions.pop(session_id, None)

    def get_state(self, session_id: str) -> SessionState | None:
        with self._sessions_lock:
            return self.sessions.get(session_id)

    def states_snapshot(self) -> tuple[SessionState, ...]:
        with self._sessions_lock:
            return tuple(self.sessions.values())

    def _validate_settings(
        self,
        duration_minutes: int | None = None,
        capture_interval_seconds: int | None = None,
    ) -> int:
        _ = capture_interval_seconds
        duration = (
            self.config.session_default_duration_minutes
            if duration_minutes is None
            else duration_minutes
        )
        if duration < self.config.session_min_duration_minutes or duration > self.config.session_max_duration_minutes:
            raise ValueError("invalid_duration")
        return duration * 60

    def _session_meta(self, state: SessionState) -> dict[str, object]:
        now = state.completed_at or time.time()
        elapsed_seconds = max(0, int(now - state.created_at))
        remaining_seconds = max(0, state.duration_seconds - elapsed_seconds)
        progress_percent = round(min(100.0, (elapsed_seconds / max(state.duration_seconds, 1)) * 100), 1)
        interval = self.config.session_capture_interval_seconds
        return {
            "session_id": state.session_id,
            "status": state.status,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "completed_at": state.completed_at,
            "duration_seconds": state.duration_seconds,
            "monitoring_mode": state.monitoring_mode,
            "capture_mode": "continuous",
            "capture_interval_seconds": interval,
            "expected_frames": max(1, state.duration_seconds // interval),
            "captured_frames": len(state.frames),
            "elapsed_seconds": elapsed_seconds,
            "remaining_seconds": remaining_seconds,
            "progress_percent": progress_percent,
            "alert_count": state.alert_count,
        }

    @staticmethod
    def _coerce_captured_at(value: object, now: float, created_at: float) -> float:
        timestamp = 0.0
        if isinstance(value, str):
            text = value.strip()
            try:
                timestamp = float(text)
            except ValueError:
                try:
                    timestamp = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    timestamp = 0.0
        elif isinstance(value, (int, float)):
            timestamp = float(value)

        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        if not math.isfinite(timestamp) or timestamp < 1_000_000_000:
            timestamp = now
        return min(max(timestamp, created_at), now + 5.0)

    @staticmethod
    def _timeout_frame(
        filename: str,
        frame_id: str,
        captured_at: float,
        reason: str,
    ) -> FrameAnalysis:
        return FrameAnalysis(
            index=0,
            filename=filename,
            image_valid=True,
            frame_id=frame_id,
            captured_at=captured_at,
            processed_at=time.time(),
            state="unscorable",
            source="timeout",
            category_type="neutral",
            category_label="待复核场景",
            status="待复核",
            decision_reason=reason,
            base_decision_reason=reason,
            fallback_reason=reason,
            scoring_source="fallback",
            used_fallback=True,
            review_required=True,
            warning=reason,
        )

    def _analyze_with_deadline(
        self,
        state: SessionState,
        filename: str,
        file_bytes: bytes,
        frame_id: str,
        captured_at: float,
    ) -> FrameAnalysis:
        previous = state.frames[-1] if state.frames else None
        future = self._frame_executor.submit(
            self.analyzer.analyze_frame,
            state.profile,
            filename,
            file_bytes,
            frame_id=frame_id,
            captured_at=captured_at,
            previous_frame=previous,
            last_model_analysis_at=state.last_model_analysis_at,
        )
        try:
            # 给 Flask JSON 序列化和网络返回留出余量，保证端到端不超过配置截止时间。
            analysis_budget = max(0.01, self.config.frame_request_timeout_seconds - 0.5)
            return future.result(timeout=analysis_budget)
        except FutureTimeoutError:
            future.cancel()
            deadline = self.config.frame_request_timeout_seconds
            return self._timeout_frame(
                filename,
                frame_id,
                captured_at,
                f"模型分析超过 {deadline:g} 秒，本帧待复核。",
            )
        except Exception as exc:
            logger.warning("帧分析失败：%s", str(exc)[:160])
            return self._timeout_frame(filename, frame_id, captured_at, "模型分析失败，本帧待复核。")

    def _finalize_live_frame(self, frames: list[FrameAnalysis], frame: FrameAnalysis) -> FrameAnalysis:
        # 实时与离线都使用相同数量的独立历史证据；复用帧不会挤掉真正的模型结果。
        history_count = max(
            self.scoring_policy.stable_window - 1,
            WINDOW_CONSISTENCY_HISTORY,
        )
        independent_history = [item for item in frames if not self._is_reused_frame(item)]
        history = list(independent_history[-history_count:]) if history_count else []
        new_frame = replace(frame, score_breakdown=dict(frame.score_breakdown))
        working_items = history + [new_frame]
        finalize_frame_scores(
            working_items,
            start_index=len(working_items) - 1,
            policy=self.scoring_policy,
        )
        return working_items[-1]

    @staticmethod
    def _is_reused_frame(frame: FrameAnalysis) -> bool:
        return (
            bool(frame.cache_hit)
            or bool(frame.duplicate_of)
            or frame.source == "reuse"
            or frame.scoring_source == "reuse"
        )

    def _medium_distract_ratio(self, frames: list[FrameAnalysis], now: float) -> tuple[int, float]:
        window_start = now - 60.0
        valid = sorted(
            (
                frame
                for frame in frames
                if frame.state in VALID_SCORE_STATES and frame.captured_at >= window_start
            ),
            key=lambda frame: frame.captured_at,
        )
        evidence_count = sum(not self._is_reused_frame(frame) for frame in valid)
        if evidence_count < 3:
            return evidence_count, 0.0

        total_seconds = 0.0
        distract_seconds = 0.0
        for index, frame in enumerate(valid):
            if index + 1 < len(valid):
                seconds = valid[index + 1].captured_at - frame.captured_at
            else:
                seconds = float(self.config.session_capture_interval_seconds)
            seconds = max(1.0, min(seconds, 30.0))
            total_seconds += seconds
            if frame.state == "distracted":
                distract_seconds += seconds
        return evidence_count, distract_seconds / max(total_seconds, 1.0)

    @staticmethod
    def _alert_event(state: SessionState, now: float, reason: str) -> dict[str, object]:
        state.last_alert_at = now
        state.alert_count += 1
        return {
            "event_id": uuid.uuid4().hex[:16],
            "triggered_at": now,
            "reason": reason,
            "mode": state.monitoring_mode,
        }

    def _evaluate_alert(self, state: SessionState, frame: FrameAnalysis) -> dict[str, object] | None:
        now = frame.captured_at or time.time()
        if state.monitoring_mode == "low":
            return None

        if state.monitoring_mode == "medium":
            # 复用结果可以延长分心时长，但不能单独触发一条新提醒。
            if self._is_reused_frame(frame):
                return None
            # 用户已经回到专注状态时不补发迟到提醒。
            if frame.state != "distracted":
                return None
            sample_count, distract_ratio = self._medium_distract_ratio(state.frames, now)
            cooldown_ready = state.last_alert_at is None or now - state.last_alert_at >= 120.0
            if sample_count >= 3 and distract_ratio > 0.50 and cooldown_ready:
                return self._alert_event(
                    state,
                    now,
                    f"最近 60 秒分心占比约 {round(distract_ratio * 100)}%。",
                )
            return None

        # 高模式的连续判断必须来自新的模型证据，静止画面复用不投票也不重置状态。
        if self._is_reused_frame(frame):
            return None

        previous_evidence = next(
            (
                candidate
                for candidate in reversed(state.frames[:-1])
                if not self._is_reused_frame(candidate)
            ),
            None,
        )
        if (
            previous_evidence is not None
            and previous_evidence.captured_at > 0
            and now - previous_evidence.captured_at > 60.0
        ):
            state.consecutive_distracted = 0
            state.consecutive_focused = 0

        raw_state = frame.raw_state or {
            "focus": "focused",
            "distract": "distracted",
        }.get(frame.category_type, "uncertain")
        raw_confidence = frame.raw_confidence if frame.raw_state else frame.score_confidence

        if raw_state == "focused" and raw_confidence >= self.scoring_policy.focused_confidence_min:
            state.consecutive_focused += 1
            state.consecutive_distracted = 0
            if state.consecutive_focused >= 2:
                state.high_alert_armed = True
        elif raw_state == "distracted" and raw_confidence >= self.scoring_policy.distracted_confidence_min:
            state.consecutive_distracted += 1
            state.consecutive_focused = 0
        else:
            # uncertain / unscorable 既不触发提醒，也不能证明已经恢复专注。
            state.consecutive_distracted = 0
            state.consecutive_focused = 0

        cooldown_ready = state.last_alert_at is None or now - state.last_alert_at >= 30.0
        immediate = (
            raw_state == "distracted"
            and raw_confidence >= self.scoring_policy.high_confidence_min
        )
        sustained = (
            raw_state == "distracted"
            and raw_confidence >= self.scoring_policy.distracted_confidence_min
            and state.consecutive_distracted >= 2
        )
        if state.high_alert_armed and cooldown_ready and (immediate or sustained):
            state.high_alert_armed = False
            reason = "检测到高置信度分心场景。" if immediate else "连续两次检测到分心场景。"
            return self._alert_event(state, now, reason)
        return None

    def _build_payload(
        self,
        state: SessionState,
        *,
        alert_event: dict[str, object] | None = None,
        include_items: bool = False,
        latest_item: FrameAnalysis | None = None,
    ) -> dict:
        items = list(state.frames)
        processing_ms = sum(max(item.processing_ms, 0) for item in items)
        summary = build_summary(
            state.profile,
            items,
            processing_ms=processing_ms,
            start_time=state.created_at,
            end_time=state.completed_at or time.time(),
            default_interval=float(self.config.session_capture_interval_seconds),
        )
        state.updated_at = time.time()
        session_meta = self._session_meta(state)
        submitted_frames = len(items)
        scored_frames = int(summary.get("scored_images", 0))
        expected_observations = expected_observation_count(
            float(session_meta["elapsed_seconds"]),
            float(session_meta["capture_interval_seconds"]),
            planned_seconds=float(session_meta["duration_seconds"]),
        )
        capture_coverage_ratio = (
            min(1.0, submitted_frames / expected_observations)
            if expected_observations
            else 0.0
        )
        model_success_ratio = scored_frames / submitted_frames if submitted_frames else 0.0
        coverage_ratio = capture_coverage_ratio * model_success_ratio
        score_version = str(summary.get("score_version") or "legacy-v1").lower()
        independent_decisive_count = int(summary.get("independent_decisive_count") or 0)
        decisive_evidence_ratio = float(summary.get("decisive_evidence_ratio") or 0.0)
        has_reference_score = summary.get("avg_focus_score") is not None
        score_reliable = bool(
            coverage_ratio >= 0.70
            and score_version == SCORE_VERSION
            and has_reference_score
            and independent_decisive_count >= 3
            and decisive_evidence_ratio >= 0.50
        )
        if coverage_ratio < 0.70:
            quality_status = "low_confidence"
            reliability_reason = "有效评分覆盖率不足70%"
        elif score_version != SCORE_VERSION:
            quality_status = "legacy_only"
            reliability_reason = "包含旧版评分，不能用于新版积分或推荐"
        elif not has_reference_score:
            quality_status = "insufficient_evidence"
            reliability_reason = "没有可计算参考分的有效画面"
        elif independent_decisive_count < 3:
            quality_status = "insufficient_evidence"
            reliability_reason = "非复用的明确状态画面少于3个"
        elif decisive_evidence_ratio < 0.50:
            quality_status = "insufficient_evidence"
            reliability_reason = "明确证据时间占可评分时间不足50%"
        else:
            quality_status = "reliable"
            reliability_reason = "覆盖率与明确证据均达到要求"
        summary.update(
            {
                "alert_count": state.alert_count,
                "expected_observations": expected_observations,
                "capture_coverage_ratio": round(capture_coverage_ratio, 3),
                "model_success_ratio": round(model_success_ratio, 3),
                "valid_coverage_ratio": round(coverage_ratio, 3),
                "valid_coverage_percent": round(coverage_ratio * 100, 1),
                "coverage_ratio": round(coverage_ratio, 3),
                "coverage_method": "valid_observations_over_expected_v2",
                "coverage_version": 2,
                "quality_status": quality_status,
                "score_reliable": score_reliable,
                "score_reference_only": bool(scored_frames) and not score_reliable,
                "score_reliability_reason": reliability_reason,
            }
        )
        latest = latest_item or (items[-1] if items else None)
        payload = {
            "session": session_meta,
            "should_alert": alert_event is not None,
            "alert_event": alert_event,
            "latest_item": latest.to_dict() if latest else None,
            "goal": state.goal,
            "goal_profile": state.profile.to_dict(),
            "summary": summary,
            "ai_advice": state.ai_advice,
        }
        if include_items:
            # 会话完成时历史构建仍需要完整帧；实时响应不发送该字段。
            payload["items"] = [item.to_dict() for item in items]
        return payload

    def start(
        self,
        goal: str,
        duration_minutes: int | None = None,
        monitoring_mode: str = "medium",
        capture_interval_seconds: int | None = None,
        owner_username: str = "",
    ) -> dict:
        self._prune()
        if monitoring_mode not in VALID_MONITORING_MODES:
            raise ValueError("invalid_monitoring_mode")
        profile = build_goal_profile(goal)
        duration_seconds = self._validate_settings(duration_minutes, capture_interval_seconds)
        session_id = uuid.uuid4().hex[:12]
        now = time.time()
        state = SessionState(
            session_id=session_id,
            goal=goal,
            profile=profile,
            created_at=now,
            updated_at=now,
            duration_seconds=duration_seconds,
            owner_username=owner_username,
            monitoring_mode=monitoring_mode,
        )
        with self._sessions_lock:
            self.sessions[session_id] = state
        return self._build_payload(state)

    def add_frame(
        self,
        session_id: str,
        filename: str,
        file_bytes: bytes,
        *,
        frame_id: str | None = None,
        captured_at: object = None,
    ) -> dict:
        self._prune()
        state = self.get_state(session_id)
        if state is None:
            raise KeyError("session_not_found")

        with state.lock:
            if state.status != "running":
                raise RuntimeError("session_not_running")

            now = time.time()
            normalized_frame_id = str(frame_id or uuid.uuid4().hex[:16])[:80]
            normalized_captured_at = self._coerce_captured_at(captured_at, now, state.created_at)
            if normalized_frame_id in state.seen_frame_ids:
                existing = next(
                    (item for item in reversed(state.frames) if item.frame_id == normalized_frame_id),
                    None,
                )
                return self._build_payload(state, latest_item=existing)

            frame = self._analyze_with_deadline(
                state,
                filename,
                file_bytes,
                normalized_frame_id,
                normalized_captured_at,
            )
            frame.index = len(state.frames)
            finalized_frame = self._finalize_live_frame(state.frames, frame)
            finalized_frame.index = len(state.frames)
            state.frames.append(finalized_frame)
            state.seen_frame_ids.add(normalized_frame_id)
            state.last_frame_hash = finalized_frame.thumbnail_hash
            if finalized_frame.duplicate_of is None and not finalized_frame.review_required and finalized_frame.image_valid:
                state.last_model_analysis_at = finalized_frame.processed_at or now

            state.updated_at = time.time()
            alert_event = self._evaluate_alert(state, finalized_frame)
            if state.created_at + state.duration_seconds <= state.updated_at:
                state.status = "completed"
                state.completed_at = state.updated_at

            return self._build_payload(state, alert_event=alert_event, latest_item=finalized_frame)

    def snapshot(self, session_id: str) -> dict:
        self._prune()
        state = self.get_state(session_id)
        if state is None or state.status != "running":
            raise KeyError("session_not_found")
        with state.lock:
            return self._build_payload(state)

    def complete(self, session_id: str, *, discard: bool = True) -> dict:
        self._prune()
        state = self.get_state(session_id)
        if state is None:
            raise KeyError("session_not_found")

        with state.lock:
            if state.status != "completed":
                state.status = "completed"
                state.completed_at = time.time()

            if not state.ai_advice:
                temp_payload = self._build_payload(state)
                advice_summary = temp_payload.get("summary", {})
                if advice_summary.get("avg_focus_score") is None:
                    state.ai_advice = "本次会话缺少明确的专注或分心证据，建议补充有效截图后再评估。"
                else:
                    state.ai_advice = self.analyzer.vlm.generate_session_summary(
                        state.goal,
                        advice_summary,
                    )
            payload = self._build_payload(state, include_items=True)

        if discard:
            self.discard(session_id)
        return payload

    def discard(self, session_id: str) -> None:
        """持久化成功后再显式删除内存会话；重复调用安全。"""
        state = self.get_state(session_id)
        if state is None:
            return
        # 与 add_frame/complete 共用锁：discard 返回后不会再有晚到帧写入该会话。
        with state.lock:
            if state.status == "running":
                state.status = "discarded"
            with self._sessions_lock:
                if self.sessions.get(session_id) is state:
                    self.sessions.pop(session_id, None)
