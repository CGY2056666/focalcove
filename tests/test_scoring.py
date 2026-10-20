"""评分引擎测试"""
from __future__ import annotations

from focus_engine.goal_profiles import build_goal_profile
from focus_engine.models import FrameAnalysis
from focus_engine.ocr_cleanup import clean_ocr_text, score_ocr_quality
from focus_engine.scoring import (
    _build_decision_reason,
    build_summary,
    expected_observation_count,
    finalize_frame_scores,
)


class TestOcrCleanup:
    def test_clean_empty(self):
        assert clean_ocr_text("") == ""

    def test_clean_short_lines_removed(self):
        result = clean_ocr_text("a\nb\nhello world")
        # "a" (len<2) removed, "b" (len<2) removed, "hello world" kept
        assert "hello world" in result

    def test_clean_replacements(self):
        result = clean_ocr_text("defination of terms")
        assert "definition" in result.lower()

    def test_score_quality_empty(self):
        assert score_ocr_quality("") == 0.0

    def test_score_quality_meaningful(self):
        score = score_ocr_quality("Python programming language basics")
        assert 0.0 <= score <= 1.0


class TestObservationCount:
    def test_expected_observation_count_starts_immediately_and_caps_at_plan(self):
        assert expected_observation_count(0) == 1
        assert expected_observation_count(19.9) == 1
        assert expected_observation_count(20) == 2
        assert expected_observation_count(999, planned_seconds=60) == 3


class TestDecisionReason:
    def test_positive_frame_omits_conflicting_negative_rule_and_normalizes_punctuation(self):
        item = FrameAnalysis(
            index=0,
            filename="capture-001.jpg",
            image_valid=True,
            base_decision_reason="截图显示的是 VS Code 编辑器界面，正在编写 Python 代码，与目标高度一致。",
            structure_score=0.8,
            category_label="编程开发环境",
            category_type="focus",
            window_consistency_score=0.9,
            distraction_score=0.1,
            status="专注",
            negative_rule="截图内容与目标属于完全不同的领域（如编程目标下出现购物网站、短视频、游戏界面）",
        )

        reason = _build_decision_reason(item)

        assert "完全不同的领域" not in reason
        assert "一致。，" not in reason
        assert reason == (
            "截图显示的是 VS Code 编辑器界面，正在编写 Python 代码，与目标高度一致，"
            "页面结构与目标场景高度一致，当前场景为“编程开发环境”，前后截图保持连续一致"
        )

    def test_distract_frame_keeps_negative_rule(self):
        item = FrameAnalysis(
            index=0,
            filename="capture-001.jpg",
            image_valid=True,
            base_decision_reason="截图内容与当前目标无关。",
            category_label="娱乐网站",
            category_type="distract",
            distraction_score=0.9,
            status="分心",
            negative_rule="出现短视频娱乐内容",
        )

        reason = _build_decision_reason(item)

        assert "出现短视频娱乐内容" in reason


def _model_frame(category: str, confidence: float, index: int) -> FrameAnalysis:
    if category == "focus":
        focus_score, distraction_score = 82.0, 0.1
    elif category == "distract":
        focus_score, distraction_score = 18.0, 0.85
    else:
        focus_score, distraction_score = 35.0, 0.2
    return FrameAnalysis(
        index=index,
        filename=f"frame-{index}.jpg",
        image_valid=True,
        category_type=category,
        category_label="测试场景",
        score_confidence=confidence,
        focus_score=focus_score,
        focus_probability=focus_score / 100,
        base_relevance_score=focus_score / 100,
        relevance_score=focus_score / 100,
        distraction_score=distraction_score,
        scoring_source="siliconflow",
    )


class TestStableState:
    def test_low_confidence_semantic_categories_remain_uncertain(self):
        focused = _model_frame("focus", 0.59, 0)
        distracted = _model_frame("distract", 0.74, 1)

        finalize_frame_scores([focused, distracted])

        assert (focused.raw_category, focused.raw_state, focused.state) == (
            "focus",
            "uncertain",
            "uncertain",
        )
        assert (distracted.raw_category, distracted.raw_state, distracted.state) == (
            "distract",
            "uncertain",
            "uncertain",
        )

    def test_high_confidence_raw_states_are_immediate(self):
        focused = _model_frame("focus", 0.90, 0)
        distracted = _model_frame("distract", 0.90, 0)

        finalize_frame_scores([focused])
        finalize_frame_scores([distracted])

        assert (focused.raw_state, focused.state) == ("focused", "focused")
        assert (distracted.raw_state, distracted.state) == ("distracted", "distracted")

    def test_ordinary_distract_requires_two_of_three_raw_observations(self):
        items = [
            _model_frame("distract", 0.80, 0),
            _model_frame("neutral", 0.90, 1),
            _model_frame("distract", 0.80, 2),
        ]

        finalize_frame_scores(items)

        assert [item.raw_state for item in items] == ["distracted", "uncertain", "distracted"]
        assert [item.state for item in items] == ["uncertain", "uncertain", "distracted"]

    def test_ordinary_focus_requires_two_of_three_and_uncertain_is_preserved(self):
        items = [
            _model_frame("focus", 0.70, 0),
            _model_frame("neutral", 0.95, 1),
            _model_frame("focus", 0.70, 2),
            _model_frame("neutral", 0.95, 3),
        ]

        finalize_frame_scores(items)

        assert [item.state for item in items] == ["uncertain", "uncertain", "focused", "uncertain"]
        assert items[2].raw_confidence == 0.70
        assert items[2].raw_category == "focus"

    def test_unscorable_frames_break_two_of_three_state_support(self):
        first = _model_frame("distract", 0.80, 0)
        failed_one = _model_frame("neutral", 0.0, 1)
        failed_one.review_required = True
        failed_two = _model_frame("neutral", 0.0, 2)
        failed_two.review_required = True
        latest = _model_frame("distract", 0.80, 3)

        finalize_frame_scores([first, failed_one, failed_two, latest])

        assert [item.raw_state for item in (first, failed_one, failed_two, latest)] == [
            "distracted",
            "unscorable",
            "unscorable",
            "distracted",
        ]
        assert latest.state == "uncertain"

    def test_first_frame_is_not_pulled_by_an_invented_consistency_value(self):
        item = _model_frame("focus", 0.70, 0)
        item.captured_at = 100.0

        finalize_frame_scores([item])

        assert item.window_consistency_score == 0.0
        assert item.focus_score == 82.0
        assert item.score_breakdown["temporal_evidence_count"] == 0.0
        assert "前后截图切换较频繁" not in item.decision_reason

    def test_ordinary_state_support_expires_after_sixty_seconds(self):
        first = _model_frame("distract", 0.80, 0)
        first.captured_at = 100.0
        second = _model_frame("distract", 0.80, 1)
        second.captured_at = 161.0

        finalize_frame_scores([first, second])

        assert [item.state for item in (first, second)] == ["uncertain", "uncertain"]

    def test_reused_frame_keeps_state_without_becoming_a_second_vote(self):
        first = _model_frame("distract", 0.80, 0)
        first.filename = "first.jpg"
        first.captured_at = 100.0
        reused = _model_frame("distract", 0.80, 1)
        reused.filename = "reuse.jpg"
        reused.captured_at = 115.0
        reused.source = "reuse"
        reused.scoring_source = "reuse"
        reused.duplicate_of = "first.jpg"
        third = _model_frame("distract", 0.80, 2)
        third.captured_at = 130.0

        finalize_frame_scores([first, reused, third])

        assert [item.state for item in (first, reused, third)] == [
            "uncertain",
            "uncertain",
            "distracted",
        ]
        assert reused.score_breakdown["reused_evidence"] == 1.0


def test_six_field_model_frames_do_not_trigger_obsolete_subscore_advice():
    profile = build_goal_profile("学习 Python")
    focused = _model_frame("focus", 0.90, 0)
    focused.captured_at = 100.0
    finalize_frame_scores([focused])

    summary = build_summary(
        profile,
        [focused],
        processing_ms=10,
        start_time=100.0,
        end_time=115.0,
    )

    advice = "".join(summary["suggestions"])
    assert "关键词" not in advice
    assert "页面结构" not in advice
    assert summary["top_distractor"] == "无明显高频偏离场景"


def test_uncertain_frame_is_not_reported_as_top_distractor():
    profile = build_goal_profile("学习 Python")
    uncertain = _model_frame("neutral", 0.90, 0)
    uncertain.captured_at = 100.0
    finalize_frame_scores([uncertain])

    summary = build_summary(
        profile,
        [uncertain],
        processing_ms=10,
        start_time=100.0,
        end_time=115.0,
    )

    assert summary["top_distractor"] == "无明显高频偏离场景"
    assert "关系不够明确" in "".join(summary["suggestions"])


class TestTimeBasedSummary:
    def test_summary_uses_timeline_and_includes_uncertain_in_average(self):
        focused = _model_frame("focus", 0.90, 0)
        focused.captured_at = 100.0
        uncertain = _model_frame("neutral", 0.95, 1)
        uncertain.captured_at = 110.0
        distracted = _model_frame("distract", 0.90, 2)
        distracted.captured_at = 130.0
        finalize_frame_scores([focused, uncertain, distracted])

        summary = build_summary(
            build_goal_profile("学习 Python"),
            [focused, uncertain, distracted],
            processing_ms=1,
            start_time=90.0,
            end_time=150.0,
        )

        assert summary["focus_duration_seconds"] == 10.0
        assert summary["uncertain_duration_seconds"] == 20.0
        assert summary["distract_duration_seconds"] == 20.0
        assert summary["unscorable_duration_seconds"] == 10.0
        assert summary["focus_ratio"] == 16.7
        assert summary["scored_focus_ratio"] == 33.3
        expected_time_weighted = round(
            (
                focused.focus_score * 10
                + uncertain.focus_score * 20
                + distracted.focus_score * 20
            )
            / 50,
            1,
        )
        assert summary["avg_focus_score"] == expected_time_weighted

    def test_all_uncertain_summary_has_reference_average_but_is_not_reliable(self):
        item = _model_frame("neutral", 0.95, 0)
        item.captured_at = 100.0
        finalize_frame_scores([item])

        summary = build_summary(
            build_goal_profile("学习 Python"),
            [item],
            processing_ms=1,
            start_time=100.0,
            end_time=115.0,
        )

        assert summary["avg_focus_score"] == item.focus_score
        assert summary["uncertain_duration_seconds"] == 15.0
        assert summary["decisive_evidence_ratio"] == 0.0
        assert summary["score_reliable"] is False

    def test_all_unscorable_new_frames_keep_multidim_version_without_a_score(self):
        item = FrameAnalysis(
            index=0,
            filename="broken.jpg",
            image_valid=False,
            captured_at=100.0,
            review_required=True,
        )
        finalize_frame_scores([item])

        summary = build_summary(
            build_goal_profile("学习 Python"),
            [item],
            processing_ms=1,
            start_time=100.0,
            end_time=115.0,
        )

        assert summary["score_version"] == "multidim-v1"
        assert summary["avg_focus_score"] is None
        assert summary["score_reliable"] is False
