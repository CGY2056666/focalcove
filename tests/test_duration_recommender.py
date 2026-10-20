from __future__ import annotations

from types import SimpleNamespace

from focus_engine.duration_recommender import (
    FocusDurationRecommender,
    _longest_timestamped_focus_minutes,
)


CONFIG = SimpleNamespace(
    session_default_duration_minutes=25,
    session_min_duration_minutes=5,
    session_max_duration_minutes=180,
)


def _session(
    session_id: str,
    *,
    goal: str = "学习 Python",
    goal_type: str = "认知学习类",
    coverage: float = 1.0,
    focus_minutes: float = 30,
    end_time: float = 1,
) -> dict:
    return {
        "session_id": session_id,
        "goal": goal,
        "goal_type": goal_type,
        "coverage_ratio": coverage,
        "max_valid_focus_minutes": focus_minutes,
        "end_time": end_time,
        "completion_score": 80,
        "score_version": "multidim-v1",
        "score_reliable": True,
        "fresh_decisive_frames": 3,
        "decisive_evidence_ratio": 1.0,
    }


def test_cold_start_stays_at_25_until_three_reliable_sessions():
    recommender = FocusDurationRecommender(CONFIG)
    history = [_session("a"), _session("b"), _session("ignored", coverage=0.69)]

    result = recommender.recommend("学习 Python", history=history)

    assert result["minutes"] == 25
    assert result["sample_count"] == 2
    assert result["source"] == "default"
    assert result["display_reason"] == "先从 25 分钟开始，完成几轮后会更贴近你的节奏。"


def test_exactly_seventy_percent_coverage_is_reliable_for_recommendation():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        _session(str(index), coverage=0.70, focus_minutes=35, end_time=index)
        for index in range(3)
    ]

    result = recommender.recommend("学习 Python", history=history)

    assert result["sample_count"] == 3
    assert result["source"] == "same_goal_history"
    assert result["minutes"] == 35


def test_legacy_full_coverage_is_recomputed_from_duration_and_captured_frames():
    recommender = FocusDurationRecommender(CONFIG)
    legacy_history = [
        {
            **_session(str(index), coverage=1.0, focus_minutes=35, end_time=index),
            "actual_duration": 25,
            "captured_frames": 1,
            "score_version": "legacy-v1",
            "score_reliable": False,
        }
        for index in range(3)
    ]

    result = recommender.recommend("学习 Python", history=legacy_history)

    assert result["sample_count"] == 0
    assert result["source"] == "default"
    assert result["minutes"] == 25


def test_short_legacy_sessions_do_not_form_a_recommendation_baseline():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        {
            **_session(str(index), coverage=1.0, focus_minutes=1, end_time=index),
            "actual_duration": 1,
            "captured_frames": 8,
            "valid_frames": 8,
            "score_version": "legacy-v1",
            "score_reliable": False,
        }
        for index in range(3)
    ]

    result = recommender.recommend("学习 Python", history=history)

    assert result["minutes"] == 25
    assert result["sample_count"] == 0


def test_same_goal_history_is_preferred_and_limited_to_ten():
    recommender = FocusDurationRecommender(CONFIG)
    same_goal = [
        _session(str(index), focus_minutes=40, end_time=index)
        for index in range(12)
    ]
    same_type = [_session("other", goal="复习英语", focus_minutes=10, end_time=20)]

    result = recommender.recommend("学习 Python", history=same_goal + same_type)

    assert result["minutes"] == 40
    assert result["sample_count"] == 10
    assert result["source"] == "same_goal_history"
    assert result["display_reason"] == "参考了最近 10 次相似目标。"


def test_goal_type_history_is_used_when_exact_goal_is_insufficient():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        _session("a", goal="学习 Python", focus_minutes=35),
        _session("b", goal="复习英语", focus_minutes=35),
        _session("c", goal="阅读论文", focus_minutes=35),
    ]

    result = recommender.recommend("学习 Python", history=history)

    assert result["minutes"] == 35
    assert result["source"] == "goal_type_history"


def test_excellent_session_never_shortens_and_adds_at_most_five_minutes():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        _session("a", focus_minutes=35, end_time=1),
        _session("b", focus_minutes=35, end_time=2),
    ]
    current = {
        **_session("current", focus_minutes=30, end_time=3),
        "plan_duration": 25,
        "actual_duration": 25,
        "completion_score": 88,
    }

    result = recommender.recommend_next(current, history=history)

    assert result["minutes"] == 30
    assert result["minutes"] >= current["plan_duration"]
    assert result["minutes"] - current["plan_duration"] <= 5
    assert result["display_reason"] == "这轮完成得不错，下次可以保持或增加 5 分钟。"
    assert result["feedback_text"] == result["display_reason"]


def test_poor_session_reduces_by_no_more_than_five_minutes():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        _session("a", focus_minutes=30, end_time=1),
        _session("b", focus_minutes=30, end_time=2),
    ]
    current = {
        **_session("current", focus_minutes=10, end_time=3),
        "plan_duration": 25,
        "actual_duration": 12,
        "completion_score": 45,
    }

    result = recommender.recommend_next(current, history=history)

    assert result["minutes"] == 20
    assert current["plan_duration"] - result["minutes"] <= 5
    assert result["display_reason"] == "这轮有些吃力，下次可以减少 5 分钟。"


def test_low_coverage_session_uses_cold_start_default_before_three_reliable_sessions():
    recommender = FocusDurationRecommender(CONFIG)
    current = {
        **_session("current", coverage=0.5, end_time=3),
        "plan_duration": 30,
        "actual_duration": 30,
        "completion_score": 95,
    }

    result = recommender.recommend_next(current, history=[])

    assert result["minutes"] == 25
    assert result["source"] == "default"


def test_missing_current_score_uses_cold_start_default_before_three_reliable_sessions():
    recommender = FocusDurationRecommender(CONFIG)
    current = {
        **_session("current", coverage=1.0, end_time=3),
        "plan_duration": 30,
        "actual_duration": 30,
        "completion_score": None,
    }

    result = recommender.recommend_next(current, history=[])

    assert result["minutes"] == 25
    assert result["source"] == "default"
    assert result["current_summary"]["completion_score"] is None


def test_legacy_current_session_cannot_bypass_three_new_session_cold_start():
    recommender = FocusDurationRecommender(CONFIG)
    current = {
        **_session("current", end_time=3),
        "score_version": "legacy-v1",
        "score_reliable": False,
        "plan_duration": 60,
        "actual_duration": 60,
    }

    result = recommender.recommend_next(
        current,
        history=[_session("only-new-history", end_time=2)],
    )

    assert result["minutes"] == 25
    assert result["sample_count"] == 1
    assert result["source"] == "default"
    assert "不足 3 次" in result["reason"]


def test_explicitly_ineligible_short_session_cannot_update_duration_baseline():
    recommender = FocusDurationRecommender(CONFIG)
    history = [_session("a"), _session("b"), _session("c")]
    current = {
        **_session("current", coverage=1.0, end_time=4),
        "plan_duration": 25,
        "actual_duration": 0.02,
        "completion_score": 100,
        "recommendation_eligible": False,
    }

    result = recommender.recommend_next(current, history=history)

    assert result["minutes"] == 25
    assert result["source"] == "current_plan"


def test_ineligible_history_is_excluded_even_when_coverage_is_full():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        {**_session(str(index), focus_minutes=45), "recommendation_eligible": False}
        for index in range(3)
    ]

    result = recommender.recommend("学习 Python", history=history)

    assert result["minutes"] == 25
    assert result["sample_count"] == 0


def test_legacy_scores_never_enter_the_new_recommendation_baseline():
    recommender = FocusDurationRecommender(CONFIG)
    history = [
        {
            **_session(str(index), focus_minutes=60),
            "score_version": "legacy-v1",
            "score_reliable": True,
            "recommendation_eligible": True,
        }
        for index in range(3)
    ]

    result = recommender.recommend("学习 Python", history=history)

    assert result["minutes"] == 25
    assert result["sample_count"] == 0
    assert result["source"] == "default"


def test_recommendation_never_falls_below_one_five_minute_step():
    config = SimpleNamespace(
        session_default_duration_minutes=25,
        session_min_duration_minutes=1,
        session_max_duration_minutes=180,
    )
    recommender = FocusDurationRecommender(config)

    assert recommender._clamp(1) == 5


def test_timestamped_focus_run_uses_real_intervals():
    session = {
        "end_time": 145,
        "focus_sequence": [
            {"captured_at": 100, "state": "focused"},
            {"captured_at": 115, "state": "focused"},
            {"captured_at": 130, "state": "distracted"},
        ],
    }

    assert _longest_timestamped_focus_minutes(session) == 0.5


def test_explicit_history_does_not_leak_between_users():
    recommender = FocusDurationRecommender(CONFIG)
    long_history = [_session(str(i), focus_minutes=45, end_time=i) for i in range(3)]

    first = recommender.recommend("学习 Python", history=long_history)
    second = recommender.recommend("学习 Python", history=[])

    assert first["minutes"] == 45
    assert second["minutes"] == 25
