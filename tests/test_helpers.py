"""工具函数测试"""
from __future__ import annotations

from flask import Flask

from app.helpers import (
    _build_focus_sequence,
    _frame_state,
    _safe_int,
    _timeline_metrics,
    build_history_statistics,
    build_history_entry,
    calculate_session_points,
    normalize_selected_goal,
    runtime_snapshot,
    serialize_history_entry,
)


class TestSafeInt:
    def test_float_string_is_truncated(self):
        assert _safe_int("3.7") == 3

    def test_invalid_value_uses_default(self):
        assert _safe_int("abc", default=9) == 9


def test_focus_sequence_keeps_real_timestamps_and_states():
    sequence = _build_focus_sequence(
        [
            {
                "captured_at": 100,
                "processed_at": 102,
                "status": "专注",
                "focus_score": 86,
                "score_confidence": 0.9,
                "scoring_source": "siliconflow",
            },
            {
                "captured_at": 115,
                "status": "待复核",
                "review_required": True,
            },
        ],
        25,
    )

    assert [item["captured_at"] for item in sequence] == [100.0, 115.0]
    assert [item["state"] for item in sequence] == ["focused", "unscorable"]


def test_focus_sequence_persists_model_cache_hits_as_reuse():
    sequence = _build_focus_sequence(
        [
            {
                "captured_at": 100,
                "state": "focused",
                "focus_score": 90,
                "score_version": "multidim-v1",
                "goal_relevance_score": 100,
                "task_evidence_score": 100,
                "context_fit_score": 100,
                "distraction_score": 0,
                "source": "bailian",
                "scoring_source": "bailian",
                "cache_hit": True,
            }
        ]
    )

    assert sequence[0]["source"] == "reuse"


def test_focus_sequence_keeps_missing_score_as_null_and_accepts_epoch_timestamp():
    sequence = _build_focus_sequence([{"captured_at": 0, "state": "uncertain"}])

    assert sequence[0]["captured_at"] == 0.0
    assert sequence[0]["focus_score"] is None
    assert sequence[0]["raw_focus_score"] is None
    assert sequence[0]["raw_distraction_score"] is None


def test_focus_sequence_persists_raw_and_stable_states():
    sequence = _build_focus_sequence(
        [
            {
                "captured_at": 100,
                "state": "uncertain",
                "raw_state": "distracted",
                "raw_confidence": 0.8,
                "confidence": 0.8,
            }
        ]
    )

    assert sequence[0]["state"] == "uncertain"
    assert sequence[0]["raw_state"] == "distracted"
    assert sequence[0]["raw_confidence"] == 0.8


def test_timeline_metrics_count_distraction_by_seconds():
    metrics = _timeline_metrics(
        [
            {"captured_at": 100, "state": "focused"},
            {"captured_at": 115, "state": "distracted"},
            {"captured_at": 130, "state": "distracted"},
        ],
        end_time=145,
    )

    assert metrics["max_valid_focus_minutes"] == 0.25
    assert metrics["focus_duration_seconds"] == 15.0
    assert metrics["distract_duration_seconds"] == 30.0
    assert metrics["uncertain_duration_seconds"] == 0.0
    assert metrics["unscorable_duration_seconds"] == 0.0


def test_timeline_metrics_marks_unobserved_gaps_as_unscorable_time():
    metrics = _timeline_metrics(
        [
            {"captured_at": 115, "state": "focused"},
            {"captured_at": 175, "state": "focused"},
        ],
        start_time=100,
        end_time=205,
    )

    assert metrics["focus_duration_seconds"] == 60.0
    assert metrics["unscorable_duration_seconds"] == 45.0
    assert metrics["max_valid_focus_minutes"] == 0.5


def test_neutral_category_is_not_reclassified_as_distraction_by_old_score_status():
    assert _frame_state({"category_type": "neutral", "status": "分心", "focus_score": 35}) == "uncertain"


def test_history_entry_records_coverage_and_time_based_counts():
    app = Flask(__name__)
    app.extensions["duration_recommender"] = type(
        "Recommender",
        (),
        {"classify_goal": staticmethod(lambda goal: "认知学习类")},
    )()
    payload = {
        "goal": "学习 Python",
        "session": {
            "session_id": "session-1",
            "created_at": 100,
            "completed_at": 160,
            "elapsed_seconds": 60,
            "duration_seconds": 1500,
            "captured_frames": 4,
            "capture_interval_seconds": 15,
            "monitoring_mode": "medium",
            "alert_count": 1,
        },
        "summary": {"avg_focus_score": 70, "focus_ratio": 66.7, "total_images": 4},
        "items": [
            {"captured_at": 100, "state": "focused", "focus_score": 80, "score_version": "multidim-v1"},
            {"captured_at": 115, "state": "focused", "focus_score": 80, "score_version": "multidim-v1"},
            {"captured_at": 130, "state": "distracted", "focus_score": 20, "score_version": "multidim-v1"},
            {"captured_at": 145, "state": "unscorable", "review_required": True},
        ],
    }

    with app.app_context():
        entry = build_history_entry(payload)

    assert entry["coverage_ratio"] == 0.6
    assert entry["capture_coverage_ratio"] == 0.8
    assert entry["model_success_ratio"] == 0.75
    assert entry["expected_observations"] == 5
    assert entry["coverage_method"] == "valid_observations_over_expected_v2"
    assert entry["coverage_version"] == 2
    assert entry["capture_interval_seconds"] == 15
    assert entry["max_valid_focus_minutes"] == 0.5
    assert entry["focus_duration_seconds"] == 30.0
    assert entry["distract_duration_seconds"] == 15.0
    assert entry["unscorable_duration_seconds"] == 15.0
    assert entry["alert_count"] == 1
    assert entry["recommendation_eligible"] is False


def test_history_entry_time_weights_uncertain_scores_and_marks_weak_evidence_reference_only():
    app = Flask(__name__)
    app.extensions["duration_recommender"] = type(
        "Recommender",
        (),
        {"classify_goal": staticmethod(lambda goal: "认知学习类")},
    )()
    started_at = 1_000
    items = []
    for index in range(10):
        focused = index == 0
        items.append(
            {
                "captured_at": started_at + index * 15,
                "state": "focused" if focused else "uncertain",
                "focus_score": 90 if focused else 50,
                "score_version": "multidim-v1",
                "goal_relevance_score": 100 if focused else 50,
                "task_evidence_score": 80 if focused else 40,
                "context_fit_score": 80 if focused else 50,
                "distraction_score": 0.1 if focused else 0.5,
                "scoring_source": "bailian",
            }
        )
    payload = {
        "goal": "学习 Python",
        "session": {
            "session_id": "uncertain-weighted",
            "created_at": started_at,
            "completed_at": started_at + 150,
            "elapsed_seconds": 150,
            "duration_seconds": 150,
            "capture_interval_seconds": 15,
            "captured_frames": 10,
        },
        # 旧汇总故意给 90，历史入口必须依据真实时间轴重算。
        "summary": {"avg_focus_score": 90, "total_images": 10, "scored_images": 10},
        "items": items,
    }

    with app.app_context():
        entry = build_history_entry(payload)

    assert entry["completion_score"] == 54.0
    assert entry["avg_goal_relevance_score"] == 55.0
    assert entry["avg_task_evidence_score"] == 44.0
    assert entry["avg_context_fit_score"] == 53.0
    assert entry["avg_distraction_risk_score"] == 46.0
    assert entry["decisive_evidence_ratio"] == 0.1
    assert entry["fresh_decisive_frames"] == 1
    assert entry["score_reliable"] is False
    assert entry["earned_points"] == 0


def _build_entry_for_coverage(*, submitted: int, valid: int, elapsed_seconds: int = 1500) -> dict:
    app = Flask(__name__)
    app.extensions["duration_recommender"] = type(
        "Recommender",
        (),
        {"classify_goal": staticmethod(lambda goal: "认知学习类")},
    )()
    started_at = 1_000_000_000
    items = [
        {
            "captured_at": started_at + index * 15,
            "state": "focused" if index < valid else "unscorable",
            "focus_score": 100 if index < valid else 0,
            "score_version": "multidim-v1",
            "goal_relevance_score": 100 if index < valid else None,
            "task_evidence_score": 100 if index < valid else None,
            "context_fit_score": 100 if index < valid else None,
            "distraction_score": 0 if index < valid else None,
            "review_required": index >= valid,
        }
        for index in range(submitted)
    ]
    payload = {
        "goal": "学习 Python",
        "session": {
            "session_id": "coverage-session",
            "created_at": started_at,
            "completed_at": started_at + elapsed_seconds,
            "elapsed_seconds": elapsed_seconds,
            "duration_seconds": 1500,
            "capture_interval_seconds": 15,
            "captured_frames": submitted,
        },
        "summary": {
            "avg_focus_score": 100,
            "focus_ratio": 100,
            "total_images": submitted,
            "scored_images": valid,
        },
        "items": items,
    }
    with app.app_context():
        return build_history_entry(payload)


def test_25_minute_session_with_one_frame_is_not_reliable_or_rewarded():
    entry = _build_entry_for_coverage(submitted=1, valid=1)

    assert entry["expected_observations"] == 100
    assert entry["capture_coverage_ratio"] == 0.01
    assert entry["model_success_ratio"] == 1.0
    assert entry["coverage_ratio"] == 0.01
    assert entry["earned_points"] == 0


def test_coverage_boundary_is_reliable_and_scales_points():
    entry = _build_entry_for_coverage(submitted=100, valid=70)

    assert entry["capture_coverage_ratio"] == 1.0
    assert entry["model_success_ratio"] == 0.7
    assert entry["coverage_ratio"] == 0.7
    assert entry["earned_points"] == 52


def test_extra_submitted_frame_does_not_hide_model_failure():
    entry = _build_entry_for_coverage(submitted=4, valid=3, elapsed_seconds=45)

    assert entry["expected_observations"] == 4
    assert entry["capture_coverage_ratio"] == 1.0
    assert entry["model_success_ratio"] == 0.75
    assert entry["coverage_ratio"] == 0.75


def test_points_are_zero_below_reliable_coverage_threshold():
    assert calculate_session_points(25, 100, 0.699) == 0
    assert calculate_session_points(25, 100, 0.70) == 52
    assert calculate_session_points(25, 100, 1.0, score_version="legacy-v1") == 0
    assert calculate_session_points(25, 100, 1.0, score_reliable=False) == 0


def test_one_second_session_is_not_rounded_up_or_used_as_reliable_evidence():
    app = Flask(__name__)
    app.extensions["duration_recommender"] = type(
        "Recommender",
        (),
        {"classify_goal": staticmethod(lambda goal: "认知学习类")},
    )()
    payload = {
        "goal": "学习 Python",
        "session": {
            "session_id": "one-second",
            "created_at": 100,
            "completed_at": 101,
            "elapsed_seconds": 1,
            "duration_seconds": 1500,
            "capture_interval_seconds": 15,
            "captured_frames": 1,
        },
        "summary": {
            "avg_focus_score": 100,
            "focus_ratio": 100,
            "total_images": 1,
            "scored_images": 1,
        },
        "items": [
            {
                "captured_at": 100,
                "state": "focused",
                "focus_score": 100,
                "score_version": "multidim-v1",
                "goal_relevance_score": 100,
                "task_evidence_score": 100,
                "context_fit_score": 100,
                "distraction_score": 0,
                "scoring_source": "siliconflow",
            }
        ],
    }

    with app.app_context():
        entry = build_history_entry(payload)

    assert entry["actual_duration_seconds"] == 1.0
    assert entry["actual_duration"] == 0.02
    assert entry["coverage_ratio"] == 1.0
    assert entry["recommendation_eligible"] is False
    assert entry["earned_points"] == 0


def test_reused_decisions_do_not_satisfy_independent_evidence_requirement():
    entry = _build_entry_for_coverage(submitted=100, valid=100)
    entry["recommendation_eligible"] = False
    entry["fresh_decisive_frames"] = 0

    serialized = serialize_history_entry(entry)

    assert serialized["recommendation_eligible"] is False
    assert serialized["summary"]["quality_status"] == "low_confidence"


def test_legacy_history_coverage_is_recomputed_for_read_views():
    serialized = serialize_history_entry(
        {
            "actual_duration": 25,
            "captured_frames": 1,
            "coverage_ratio": 1.0,
            "completion_score": 100,
        }
    )

    assert serialized["coverage_ratio"] == 0.01
    assert serialized["summary"]["quality_status"] == "low_confidence"
    assert serialized["summary"]["valid_coverage_ratio"] == 0.01
    assert serialized["score_version"] == "legacy-v1"
    assert serialized["score_reliable"] is False


def test_short_legacy_history_is_marked_ineligible_even_if_old_coverage_was_full():
    serialized = serialize_history_entry(
        {
            "actual_duration": 1,
            "captured_frames": 8,
            "valid_frames": 8,
            "coverage_ratio": 1.0,
            "completion_score": 100,
        }
    )

    assert serialized["recommendation_eligible"] is False
    assert serialized["summary"]["quality_status"] == "low_confidence"


def test_history_serialization_preserves_missing_scores_and_epoch_timestamp():
    serialized = serialize_history_entry(
        {
            "actual_duration": 1,
            "captured_frames": 4,
            "valid_frames": 4,
            "coverage_ratio": 1.0,
            "coverage_version": 2,
            "capture_interval_seconds": 20,
            "started_at": 0,
            "end_time": 60,
        }
    )

    assert serialized["completion_score"] is None
    assert serialized["summary"]["avg_focus_score"] is None
    assert serialized["summary"]["quality_status"] == "low_confidence"
    assert serialized["current_summary"]["completion_score"] is None
    assert serialized["started_at"] == 0.0
    assert serialized["end_time"] == 60.0
    assert serialized["capture_interval_seconds"] == 20


def test_new_all_unscorable_session_is_not_mislabeled_as_legacy():
    app = Flask(__name__)
    app.extensions["duration_recommender"] = type(
        "Recommender",
        (),
        {"classify_goal": staticmethod(lambda goal: "认知学习类")},
    )()
    payload = {
        "goal": "学习 Python",
        "session": {
            "session_id": "unscorable-new",
            "created_at": 100,
            "completed_at": 115,
            "elapsed_seconds": 15,
            "duration_seconds": 1500,
            "captured_frames": 1,
            "capture_interval_seconds": 15,
        },
        "summary": {"score_version": "multidim-v1", "total_images": 1},
        "items": [
            {
                "captured_at": 100,
                "state": "unscorable",
                "review_required": True,
                "score_version": "multidim-v1",
            }
        ],
    }

    with app.app_context():
        entry = build_history_entry(payload)

    assert entry["score_version"] == "multidim-v1"
    assert entry["completion_score"] is None
    assert entry["score_reliable"] is False


def test_history_score_average_excludes_low_confidence_sessions():
    stats = build_history_statistics(
        [
            {"actual_duration": 25, "completion_score": 90, "coverage_ratio": 0.8, "coverage_version": 2, "score_version": "multidim-v1", "score_reliable": True, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.5},
            {"actual_duration": 25, "completion_score": 10, "coverage_ratio": 0.2, "coverage_version": 2, "score_version": "multidim-v1", "score_reliable": False, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.5},
        ]
    )

    assert stats["avg_focus_score"] == 90
    assert stats["reliable_sessions"] == 1
    assert stats["low_confidence_sessions"] == 1


def test_history_score_average_excludes_reliable_sessions_with_missing_score():
    stats = build_history_statistics(
        [
            {"actual_duration": 25, "completion_score": 90, "coverage_ratio": 0.8, "coverage_version": 2, "score_version": "multidim-v1", "score_reliable": True, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.5},
            {"actual_duration": 25, "completion_score": None, "coverage_ratio": 0.9, "coverage_version": 2, "score_version": "multidim-v1", "score_reliable": False, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.5},
        ]
    )

    assert stats["avg_focus_score"] == 90
    assert stats["reliable_sessions"] == 1
    assert stats["low_confidence_sessions"] == 1


def test_history_score_average_excludes_explicitly_ineligible_short_session():
    stats = build_history_statistics(
        [
            {
                "actual_duration": 0.02,
                "completion_score": 100,
                "coverage_ratio": 1.0,
                "coverage_version": 2,
                "recommendation_eligible": False,
            }
        ]
    )

    assert stats["reliable_sessions"] == 0
    assert stats["low_confidence_sessions"] == 1


def test_selected_goal_stays_empty_until_user_selects_one():
    assert normalize_selected_goal(None) == ""
    assert normalize_selected_goal("   ") == ""


def test_runtime_snapshot_exposes_effective_evaluation_capture_state(app):
    with app.app_context():
        snapshot = runtime_snapshot(include_adaptive=False, username="runtime-user")

    # TESTING disables automatic screenshot collection even when local config enables it.
    assert snapshot["evaluation_capture_enabled"] is False


def test_runtime_snapshot_does_not_recommend_for_an_unselected_goal(app, monkeypatch):
    from app import helpers as helpers_module

    calls = []
    monkeypatch.setattr(
        helpers_module,
        "build_duration_recommendation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with app.app_context():
        snapshot = runtime_snapshot(selected_goal=None, username="runtime-user")

    assert snapshot["duration_recommendation"] is None
    assert calls == []


def test_datetime_filter_treats_missing_epoch_as_unknown(app):
    formatter = app.jinja_env.filters["datetimeformat"]

    assert formatter(0) == "--"
    assert formatter(None) == "--"
