from __future__ import annotations

import json
import math
import time
from dataclasses import replace

from focus_engine.config import DEFAULT_CONFIG
from focus_engine.goal_profiles import build_goal_profile
from focus_engine.models import FrameAnalysis
from focus_engine.pipeline import FocusAnalyzer
from focus_engine.scoring import finalize_frame_scores
from focus_engine.scoring_policy import (
    DEFAULT_SCORING_POLICY,
    ScoringPolicy,
    composite_focus_score,
    load_scoring_policy,
)
from focus_engine.session import SessionState, StreamingSessionManager


def _frame(category: str, confidence: float, index: int = 0) -> FrameAnalysis:
    components = {
        "focus": (100.0, 100.0, 100.0, 0.0),
        "neutral": (50.0, 25.0, 50.0, 0.25),
        "distract": (0.0, 0.0, 25.0, 1.0),
    }[category]
    return FrameAnalysis(
        index=index,
        filename=f"frame-{index}.jpg",
        image_valid=True,
        captured_at=time.time() + index * 15,
        category_type=category,
        category_label="测试场景",
        score_confidence=confidence,
        goal_relevance_score=components[0],
        task_evidence_score=components[1],
        context_fit_score=components[2],
        distraction_score=components[3],
        scoring_source="siliconflow",
    )


def test_default_composite_score_uses_fixed_four_dimension_formula() -> None:
    assert composite_focus_score(100, 100, 100, 0, 1) == 100.0
    assert composite_focus_score(50, 50, 50, 0.5, 1) == 50.0
    # 默认收缩权重 0.5：零置信度时只走到“当前分与50分中点”。
    assert composite_focus_score(100, 100, 100, 0, 0) == 75.0


def test_composite_weights_are_normalized_and_confidence_shrinks_toward_half() -> None:
    policy = ScoringPolicy(
        goal_relevance_weight=2,
        task_evidence_weight=1,
        context_fit_weight=1,
        inverse_distraction_weight=1,
        confidence_shrink_weight=1,
    )

    assert math.isclose(
        policy.goal_relevance_weight
        + policy.task_evidence_weight
        + policy.context_fit_weight
        + policy.inverse_distraction_weight,
        1.0,
    )
    assert composite_focus_score(100, 100, 100, 0, 0, policy) == 50.0
    assert composite_focus_score(100, 100, 100, 0, 1, policy) == 100.0


def test_neutral_category_remains_uncertain_even_when_policy_changes_numeric_score() -> None:
    policy = ScoringPolicy(
        goal_relevance_weight=0,
        task_evidence_weight=0,
        context_fit_weight=1,
        inverse_distraction_weight=0,
        temporal_consistency_weight=0,
    )
    frame = _frame("neutral", 0.99)

    finalize_frame_scores([frame], policy=policy)

    assert frame.focus_score == 50.0
    assert frame.state == "uncertain"


def test_repeated_finalization_reuses_frozen_model_values() -> None:
    policy = ScoringPolicy(
        goal_relevance_weight=1,
        task_evidence_weight=0,
        context_fit_weight=0,
        inverse_distraction_weight=1,
        temporal_consistency_weight=0,
    )
    frame = _frame("focus", 0.90)
    frame.distraction_score = 0.80

    finalize_frame_scores([frame], policy=policy)
    first_score = frame.focus_score
    finalize_frame_scores([frame], policy=policy)

    assert frame.raw_focus_score == 59.5
    assert frame.raw_distraction_score == 0.80
    assert first_score == 59.5
    assert frame.focus_score == first_score


def test_multidim_temporal_smoothing_uses_previous_three_independent_medians() -> None:
    policy = ScoringPolicy(
        goal_relevance_weight=1,
        task_evidence_weight=0,
        context_fit_weight=0,
        inverse_distraction_weight=0,
        confidence_shrink_weight=0,
        temporal_consistency_weight=0.12,
    )
    frames = []
    for index, goal_score in enumerate((20.0, 40.0, 60.0, 100.0)):
        frame = _frame("neutral", 1.0, index)
        frame.goal_relevance_score = goal_score
        frames.append(frame)

    finalize_frame_scores(frames, policy=policy)

    assert frames[0].focus_score == 20.0
    assert frames[3].raw_focus_score == 100.0
    assert frames[3].score_breakdown["temporal_reference_median"] == 37.6
    assert frames[3].focus_score == 92.5


def test_component_gate_downgrades_category_without_rewriting_numeric_score() -> None:
    frame = _frame("focus", 0.99)
    frame.task_evidence_score = 25.0

    finalize_frame_scores([frame])

    assert frame.raw_category == "neutral"
    assert frame.category_type == "neutral"
    assert frame.state == "uncertain"
    assert frame.focus_score > 70.0


def test_policy_file_loads_and_missing_or_invalid_fields_fall_back(tmp_path) -> None:
    valid_path = tmp_path / "valid-policy.json"
    payload = DEFAULT_SCORING_POLICY.to_dict()
    payload.update(
        {
            "goal_relevance_weight": 2,
            "task_evidence_weight": 1,
            "context_fit_weight": 1,
            "inverse_distraction_weight": 1,
            "focused_confidence_min": 0.7,
        }
    )
    valid_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_scoring_policy(valid_path)

    assert loaded.loaded is True
    assert loaded.error is None
    assert loaded.policy.goal_relevance_weight == 0.4
    assert loaded.policy.focused_confidence_min == 0.7

    missing_path = tmp_path / "missing-field.json"
    payload.pop("stable_support")
    missing_path.write_text(json.dumps(payload), encoding="utf-8")
    missing = load_scoring_policy(missing_path)
    assert missing.policy == DEFAULT_SCORING_POLICY
    assert missing.error is not None
    assert "missing fields" in missing.error

    legacy_path = tmp_path / "legacy-policy.json"
    legacy_path.write_text(
        json.dumps({"focus_score_weight": 1, "category_signal_weight": 0}),
        encoding="utf-8",
    )
    legacy = load_scoring_policy(legacy_path)
    assert legacy.policy == DEFAULT_SCORING_POLICY
    assert "legacy scoring policy fields" in str(legacy.error)

    invalid_path = tmp_path / "invalid-policy.json"
    invalid_path.write_text("{broken", encoding="utf-8")
    invalid = load_scoring_policy(invalid_path)
    assert invalid.policy == DEFAULT_SCORING_POLICY
    assert invalid.error is not None


def test_custom_thresholds_and_stable_window_control_state() -> None:
    policy = ScoringPolicy(
        distracted_confidence_min=0.90,
        high_confidence_min=0.95,
        stable_window=2,
        stable_support=2,
    )
    frames = [_frame("distract", 0.92, 0), _frame("distract", 0.92, 1)]

    finalize_frame_scores(frames, policy=policy)

    assert [frame.state for frame in frames] == ["uncertain", "distracted"]


class _FakeVlm:
    def status(self) -> dict:
        return {"provider": "fake", "configured": True, "model": "fake"}

    def generate_session_summary(self, goal: str, summary: dict) -> str:
        return "ok"


class _PolicyAnalyzer:
    def __init__(self, policy: ScoringPolicy) -> None:
        self.scoring_policy = policy
        self.vlm = _FakeVlm()


def test_streaming_manager_reuses_analyzer_policy_for_high_alerts() -> None:
    policy = ScoringPolicy(
        distracted_confidence_min=0.80,
        high_confidence_min=0.95,
    )
    manager = StreamingSessionManager(_PolicyAnalyzer(policy))
    now = time.time()
    state = SessionState(
        session_id="policy-session",
        goal="学习 Python",
        profile=build_goal_profile("学习 Python"),
        created_at=now,
        updated_at=now,
        duration_seconds=1500,
        monitoring_mode="high",
    )
    try:
        first = _frame("distract", 0.90, 0)
        first.raw_state = "distracted"
        first.raw_confidence = 0.90
        first.raw_category = "distract"
        assert manager._evaluate_alert(state, first) is None

        second = _frame("distract", 0.90, 1)
        second.raw_state = "distracted"
        second.raw_confidence = 0.90
        second.raw_category = "distract"
        assert manager._evaluate_alert(state, second) is not None
        assert manager.scoring_policy is policy
    finally:
        manager._frame_executor.shutdown(wait=True)


def test_focus_analyzer_reports_policy_load_failure(tmp_path) -> None:
    missing_path = tmp_path / "does-not-exist.json"
    analyzer = FocusAnalyzer(replace(DEFAULT_CONFIG, scoring_policy_path=str(missing_path)))

    status = analyzer.scoring_status()

    assert analyzer.scoring_policy == DEFAULT_SCORING_POLICY
    assert status["scoring_policy_source"] == "default"
    assert status["scoring_policy_error"] is not None
    assert status["scoring_policy"] == DEFAULT_SCORING_POLICY.to_dict()


def test_focus_analyzer_batch_finalization_uses_loaded_policy(tmp_path) -> None:
    policy_path = tmp_path / "batch-policy.json"
    payload = DEFAULT_SCORING_POLICY.to_dict()
    payload.update(
        {
            "goal_relevance_weight": 0,
            "task_evidence_weight": 0,
            "context_fit_weight": 1,
            "inverse_distraction_weight": 0,
            "temporal_consistency_weight": 0,
        }
    )
    policy_path.write_text(json.dumps(payload), encoding="utf-8")
    analyzer = FocusAnalyzer(replace(DEFAULT_CONFIG, scoring_policy_path=str(policy_path)))
    neutral = _frame("neutral", 0.99)
    analyzer._prepare_frames = lambda uploads: []
    analyzer._analyze_prepared_frames = lambda profile, prepared: [neutral]

    _, items, _ = analyzer.analyze_objects("学习 Python", [])

    assert analyzer.scoring_policy_source == "file"
    assert items[0].focus_score == 50.0
    assert items[0].state == "uncertain"
