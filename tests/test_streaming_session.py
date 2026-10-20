from __future__ import annotations

import time
import threading
import math
from dataclasses import replace

import cv2
import numpy as np

from focus_engine.config import DEFAULT_CONFIG
from focus_engine.goal_profiles import build_goal_profile
from focus_engine.models import FrameAnalysis
from focus_engine.pipeline import FocusAnalyzer
from focus_engine.scoring import build_summary, fallback_scoring, finalize_frame_scores
from focus_engine.session import SessionState, StreamingSessionManager


def _frame(
    state: str,
    captured_at: float,
    *,
    confidence: float = 0.8,
    index: int = 0,
) -> FrameAnalysis:
    category = {"focused": "focus", "distracted": "distract"}.get(state, "neutral")
    score = {"focused": 85.0, "distracted": 15.0}.get(state, 35.0)
    return FrameAnalysis(
        index=index,
        filename=f"frame-{index}.jpg",
        image_valid=True,
        frame_id=f"frame-{index}",
        captured_at=captured_at,
        processed_at=captured_at + 0.1,
        state=state,
        raw_state=state,
        raw_confidence=confidence,
        raw_category=category,
        source="fake",
        category_type=category,
        category_label="测试场景",
        focus_score=score,
        focus_probability=score / 100,
        relevance_score=score / 100,
        base_relevance_score=score / 100,
        distraction_score=1 - score / 100,
        score_confidence=confidence,
        scoring_source="siliconflow",
        status={"focused": "专注", "distracted": "分心"}.get(state, "轻微偏离"),
    )


class _FakeVlm:
    def generate_session_summary(self, goal: str, summary: dict) -> str:
        return f"{goal}:{summary.get('scored_images', 0)}"


class _FakeAnalyzer:
    def __init__(self, frames: list[FrameAnalysis] | None = None, delay: float = 0.0) -> None:
        self.frames = list(frames or [])
        self.delay = delay
        self.vlm = _FakeVlm()

    def analyze_frame(self, profile, filename, file_bytes, **kwargs) -> FrameAnalysis:
        if self.delay:
            time.sleep(self.delay)
        if self.frames:
            result = replace(self.frames.pop(0))
        else:
            result = _frame("uncertain", float(kwargs.get("captured_at") or time.time()))
        result.filename = filename
        result.frame_id = str(kwargs.get("frame_id") or "")
        result.captured_at = float(kwargs.get("captured_at") or time.time())
        result.processed_at = time.time()
        return result


def _state(mode: str) -> SessionState:
    now = time.time()
    return SessionState(
        session_id="abc123",
        goal="学习 Python",
        profile=build_goal_profile("学习 Python"),
        created_at=now,
        updated_at=now,
        duration_seconds=1500,
        monitoring_mode=mode,
    )


def test_neutral_score_35_stays_uncertain() -> None:
    item = _frame("uncertain", time.time(), confidence=0.99)
    item.category_type = "neutral"
    item.focus_score = 35.0

    finalize_frame_scores([item])

    assert item.state == "uncertain"
    assert item.status == "轻微偏离"


def test_invalid_duration_and_nonfinite_capture_time_are_normalized() -> None:
    manager = StreamingSessionManager(_FakeAnalyzer())
    try:
        try:
            manager.start("学习 Python", duration_minutes=0)
            assert False, "duration 0 must be rejected"
        except ValueError as exc:
            assert str(exc) == "invalid_duration"

        now = time.time()
        normalized = manager._coerce_captured_at(float("nan"), now, now - 10)
        assert math.isfinite(normalized)
        assert normalized == now
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_fallback_is_unscorable_without_fake_score() -> None:
    result = fallback_scoring(build_goal_profile("学习 Python"), object())

    assert result["review_required"] is True
    assert result["focus_score"] == 0.0
    assert result["score_breakdown"]["ocr_quality_score"] == 0.0


def test_low_coverage_does_not_report_one_success_as_full_focus() -> None:
    profile = build_goal_profile("学习 Python")
    focused = _frame("focused", 100.0, confidence=0.9, index=0)
    failed = _frame("unscorable", 115.0, index=1)
    failed.review_required = True
    failed.status = "待复核"

    summary = build_summary(profile, [focused, failed], processing_ms=10, end_time=130.0)

    assert summary["valid_coverage_ratio"] == 0.5
    assert summary["quality_status"] == "low_confidence"
    assert summary["focus_ratio"] == 50.0
    assert summary["scored_focus_ratio"] == 100.0
    assert summary["focus_duration_seconds"] == 15.0


def test_monitoring_modes_and_high_rearm() -> None:
    manager = StreamingSessionManager(_FakeAnalyzer())
    base = time.time()
    try:
        low = _state("low")
        low.frames.append(_frame("distracted", base, confidence=0.95))
        assert manager._evaluate_alert(low, low.frames[-1]) is None

        medium = _state("medium")
        events = []
        for index, state in enumerate(("focused", "distracted", "distracted")):
            item = _frame(state, base + index * 15, index=index)
            medium.frames.append(item)
            events.append(manager._evaluate_alert(medium, item))
        assert events[:2] == [None, None]
        assert events[2] is not None
        assert events[2]["mode"] == "medium"

        high = _state("high")
        first = _frame("distracted", base, confidence=0.80, index=0)
        high.frames.append(first)
        assert manager._evaluate_alert(high, first) is None
        second = _frame("distracted", base + 15, confidence=0.80, index=1)
        high.frames.append(second)
        assert manager._evaluate_alert(high, second) is not None

        still_distracted = _frame("distracted", base + 60, confidence=0.95, index=2)
        high.frames.append(still_distracted)
        assert manager._evaluate_alert(high, still_distracted) is None

        for index, seconds in enumerate((75, 90), start=3):
            focused = _frame("focused", base + seconds, index=index)
            high.frames.append(focused)
            assert manager._evaluate_alert(high, focused) is None
        rearmed = _frame("distracted", base + 105, confidence=0.90, index=5)
        high.frames.append(rearmed)
        assert manager._evaluate_alert(high, rearmed) is not None

        raw_immediate = _state("high")
        raw_frame = _frame("distracted", base, confidence=0.90)
        raw_frame.state = "uncertain"
        raw_immediate.frames.append(raw_frame)
        assert manager._evaluate_alert(raw_immediate, raw_frame) is not None
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_live_payload_is_incremental_and_complete_keeps_items() -> None:
    now = time.time()
    analyzer = _FakeAnalyzer([_frame("focused", now, confidence=0.9)])
    manager = StreamingSessionManager(analyzer)
    try:
        started = manager.start("学习 Python", monitoring_mode="low")
        session_id = started["session"]["session_id"]
        payload = manager.add_frame(
            session_id,
            "screen.jpg",
            b"test",
            frame_id="f-1",
            captured_at=now,
        )

        assert payload["latest_item"]["frame_id"] == "f-1"
        assert payload["alert_event"] is None
        assert "items" not in payload
        assert payload["summary"]["valid_coverage_ratio"] == 1.0
        assert payload["summary"]["score_reliable"] is False
        assert payload["summary"]["quality_status"] in {"insufficient_evidence", "legacy_only"}

        completed = manager.complete(session_id, discard=False)
        assert len(completed["items"]) == 1
        assert session_id in manager.sessions
        manager.discard(session_id)
        assert session_id not in manager.sessions
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_live_payload_does_not_call_high_coverage_weak_evidence_reliable() -> None:
    now = time.time()
    frames = [
        _frame("uncertain", now + index * 15, confidence=0.9, index=index)
        for index in range(4)
    ]
    for frame in frames:
        frame.score_version = "multidim-v1"
        frame.goal_relevance_score = 50.0
        frame.task_evidence_score = 50.0
        frame.context_fit_score = 50.0
        frame.distraction_score = 0.5
    manager = StreamingSessionManager(_FakeAnalyzer())
    state = _state("low")
    state.created_at = now
    state.duration_seconds = 60
    state.frames = frames
    state.completed_at = now + 60
    try:
        payload = manager._build_payload(state)

        assert payload["summary"]["valid_coverage_ratio"] == 1.0
        assert payload["summary"]["decisive_evidence_ratio"] == 0.0
        assert payload["summary"]["score_reliable"] is False
        assert payload["summary"]["quality_status"] == "insufficient_evidence"
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_live_coverage_uses_expected_capture_clock_not_only_submitted_frames() -> None:
    now = time.time()
    analyzer = _FakeAnalyzer([_frame("focused", now, confidence=0.9)])
    manager = StreamingSessionManager(analyzer)
    try:
        started = manager.start("学习 Python", monitoring_mode="low")
        session_id = started["session"]["session_id"]
        manager.sessions[session_id].created_at = now - 45
        payload = manager.add_frame(
            session_id,
            "screen.jpg",
            b"test",
            frame_id="only-frame",
            captured_at=now,
        )

        assert payload["summary"]["expected_observations"] == 3
        assert payload["summary"]["capture_coverage_ratio"] == 0.333
        assert payload["summary"]["model_success_ratio"] == 1.0
        assert payload["summary"]["valid_coverage_ratio"] == 0.333
        assert payload["summary"]["quality_status"] == "low_confidence"
        # 唯一截图是在第 45 秒才采集，之前的时间不能按帧数折算成专注。
        assert payload["summary"]["focus_ratio"] == 0.0
        assert payload["summary"]["unscorable_duration_seconds"] >= 44.0
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_frame_deadline_returns_unscorable() -> None:
    config = replace(DEFAULT_CONFIG, frame_request_timeout_seconds=0.03)
    manager = StreamingSessionManager(_FakeAnalyzer(delay=0.15), config)
    try:
        started = manager.start("学习 Python")
        session_id = started["session"]["session_id"]
        began = time.perf_counter()
        payload = manager.add_frame(session_id, "slow.jpg", b"test", frame_id="slow")
        elapsed = time.perf_counter() - began

        assert elapsed < 0.12
        assert payload["latest_item"]["state"] == "unscorable"
        assert payload["summary"]["valid_coverage_ratio"] == 0.0
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_discard_waits_for_inflight_frame_and_removes_session() -> None:
    manager = StreamingSessionManager(_FakeAnalyzer(delay=0.08))
    started = manager.start("学习 Python")
    session_id = started["session"]["session_id"]
    worker = threading.Thread(
        target=lambda: manager.add_frame(session_id, "slow.jpg", b"test", frame_id="late"),
        daemon=True,
    )
    try:
        worker.start()
        time.sleep(0.01)
        manager.discard(session_id)
        worker.join(timeout=1.0)

        assert not worker.is_alive()
        assert session_id not in manager.sessions
    finally:
        manager._frame_executor.shutdown(wait=True)


class _BlockingItemsDict(dict):
    def __init__(self, values):
        super().__init__(values)
        self.iterating = threading.Event()
        self.release = threading.Event()

    def items(self):
        for index, item in enumerate(super().items()):
            yield item
            if index == 0:
                self.iterating.set()
                if not self.release.wait(timeout=2):
                    raise TimeoutError('test did not release sessions iteration')


def test_sessions_dictionary_mutation_waits_for_prune_snapshot() -> None:
    manager = StreamingSessionManager(_FakeAnalyzer())
    manager.start('first session')
    second_id = manager.start('second session')['session']['session_id']
    blocking_sessions = _BlockingItemsDict(manager.sessions)
    manager.sessions = blocking_sessions
    errors = []

    def run_prune():
        try:
            manager._prune()
        except BaseException as exc:
            errors.append(exc)

    prune_worker = threading.Thread(target=run_prune, daemon=True)
    discard_worker = threading.Thread(
        target=lambda: manager.discard(second_id),
        daemon=True,
    )
    try:
        prune_worker.start()
        assert blocking_sessions.iterating.wait(timeout=1)
        discard_worker.start()
        time.sleep(0.05)
        assert discard_worker.is_alive()
    finally:
        blocking_sessions.release.set()
        prune_worker.join(timeout=2)
        discard_worker.join(timeout=2)
        manager._frame_executor.shutdown(wait=True)

    assert not prune_worker.is_alive()
    assert not discard_worker.is_alive()
    assert errors == []
    assert manager.get_state(second_id) is None


def test_cross_frame_hash_reuses_only_until_recheck_deadline() -> None:
    class CountingVlm:
        def __init__(self) -> None:
            self.calls = 0
            self.bypass_cache_values = []

        def status(self):
            return {"provider": "siliconflow", "configured": True, "model": "test"}

        def vision_ready_message(self):
            return True, "test"

        def analyze(self, profile, filename, image, thumbnail_hash, *, bypass_cache=False):
            self.calls += 1
            self.bypass_cache_values.append(bypass_cache)
            return {
                "ocr_text": "",
                "ocr_quality": 0.0,
                "category_type": "focus",
                "category_label": "代码编辑器",
                "semantic_match_score": 0.8,
                "keyword_hit_score": 0.8,
                "strong_hit_score": 0.8,
                "coverage_score": 0.8,
                "structure_score": 0.8,
                "app_context_score": 0.8,
                "relevance_score": 0.85,
                "distraction_score": 0.05,
                "focus_score": 85.0,
                "focus_probability": 0.85,
                "confidence": 0.9,
                "status": "专注",
                "matched_keywords": ["Python"],
                "strong_hits": ["Python"],
                "scene_hits": [],
                "support_hits": [],
                "negative_hits": [],
                "matched_context_patterns": [],
                "positive_rule": "出现 Python 代码",
                "negative_rule": "",
                "reason": "截图中正在编辑 Python 代码",
                "fallback_reason": "",
                "review_required": False,
                "cache_hit": False,
                "score_breakdown": {"llm_latency_ms": 1.0},
            }

        def generate_session_summary(self, goal, summary):
            return "ok"

    analyzer = FocusAnalyzer(replace(DEFAULT_CONFIG, duplicate_recheck_seconds=60))
    vlm = CountingVlm()
    analyzer.vlm = vlm
    image = np.full((80, 120, 3), 180, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    raw = encoded.tobytes()
    profile = build_goal_profile("学习 Python")

    first = analyzer.analyze_frame(profile, "first.jpg", raw, frame_id="1", captured_at=100.0)
    first.state = "focused"
    second = analyzer.analyze_frame(
        profile,
        "second.jpg",
        raw,
        frame_id="2",
        captured_at=115.0,
        previous_frame=first,
        last_model_analysis_at=100.0,
    )
    third = analyzer.analyze_frame(
        profile,
        "third.jpg",
        raw,
        frame_id="3",
        captured_at=161.0,
        previous_frame=second,
        last_model_analysis_at=100.0,
    )

    assert second.source == "reuse"
    assert second.duplicate_of == "first.jpg"
    assert third.source == "siliconflow"
    assert vlm.calls == 2
    assert vlm.bypass_cache_values == [False, True]


def test_model_cache_hits_are_not_independent_evidence() -> None:
    base = time.time()
    first = _frame("focused", base, confidence=0.9, index=0)
    cached_second = replace(
        _frame("focused", base + 61, confidence=0.9, index=1),
        cache_hit=True,
    )
    cached_third = replace(
        _frame("focused", base + 122, confidence=0.9, index=2),
        cache_hit=True,
    )

    summary = build_summary(
        build_goal_profile("学习 Python"),
        [first, cached_second, cached_third],
        processing_ms=1,
        start_time=base,
        end_time=base + 137,
    )

    assert summary["cache_hits"] == 2
    assert summary["independent_decisive_count"] == 1
    assert summary["score_reliable"] is False


def test_reuse_does_not_trigger_high_or_medium_alert() -> None:
    manager = StreamingSessionManager(_FakeAnalyzer())
    base = time.time()
    try:
        high = _state("high")
        first = _frame("distracted", base, confidence=0.80, index=0)
        high.frames.append(first)
        assert manager._evaluate_alert(high, first) is None

        reused = replace(
            first,
            index=1,
            filename="reuse.jpg",
            frame_id="frame-1",
            captured_at=base + 15,
            source="reuse",
            scoring_source="reuse",
            duplicate_of=first.filename,
        )
        high.frames.append(reused)
        assert manager._evaluate_alert(high, reused) is None
        assert high.consecutive_distracted == 1

        medium = _state("medium")
        for index, seconds in enumerate((0, 15, 30)):
            item = _frame("distracted", base + seconds, index=index)
            medium.frames.append(item)
            event = manager._evaluate_alert(medium, item)
            if index < 2:
                assert event is None
            else:
                assert event is not None

        # 冷却结束后的复用结果也不能单独制造提醒。
        medium.last_alert_at = base - 200
        reused_medium = replace(
            medium.frames[-1],
            index=3,
            filename="medium-reuse.jpg",
            captured_at=base + 45,
            source="reuse",
            scoring_source="reuse",
            duplicate_of=medium.frames[-1].filename,
        )
        medium.frames.append(reused_medium)
        assert manager._evaluate_alert(medium, reused_medium) is None
    finally:
        manager._frame_executor.shutdown(wait=True)
