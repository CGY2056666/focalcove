from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from focus_engine.config import DEFAULT_CONFIG
from focus_engine.goal_profiles import build_goal_profile
from focus_engine.models import FrameAnalysis
from focus_engine.scoring import finalize_frame_scores
from focus_engine.siliconflow_vlm import SiliconFlowVlmScorer


def _valid_payload(**overrides):
    payload = {
        "category_type": "neutral",
        "category_label": "通用工具界面",
        "goal_relevance": 2,
        "task_evidence": 1,
        "context_fit": 2,
        "distraction_level": 1,
        "confidence": 0.45,
        "reason": "截图证据不足，暂时无法确认与目标的关系",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def scorer():
    return SiliconFlowVlmScorer(DEFAULT_CONFIG)


def test_missing_required_fields_become_review_required(scorer):
    result = scorer._normalize_response({}, 0.0, "")

    assert result["review_required"] is True
    assert result["status"] == "待复核"
    assert "缺少必填字段" in result["reason"]

    frame = FrameAnalysis(
        index=0,
        filename="invalid.jpg",
        image_valid=True,
        review_required=result["review_required"],
        category_type=result["category_type"],
        score_confidence=result["confidence"],
    )
    finalize_frame_scores([frame])
    assert frame.raw_state == "unscorable"
    assert frame.state == "unscorable"


@pytest.mark.parametrize(
    "field,value",
    [
        ("goal_relevance", "4"),
        ("goal_relevance", math.nan),
        ("task_evidence", 4.5),
        ("context_fit", 5),
        ("distraction_level", math.inf),
        ("confidence", 1.1),
        ("category_type", "other"),
        ("reason", ""),
    ],
)
def test_invalid_types_ranges_and_enums_become_review_required(scorer, field, value):
    result = scorer._normalize_response(_valid_payload(**{field: value}), 0.0, "")

    assert result["review_required"] is True
    assert result["focus_score"] == 0.0


@pytest.mark.parametrize(
    "payload",
    [
        _valid_payload(category_type="focus", goal_relevance=2, task_evidence=4),
        _valid_payload(category_type="focus", goal_relevance=4, task_evidence=1),
        _valid_payload(category_type="distract", goal_relevance=2, distraction_level=4),
        _valid_payload(category_type="distract", goal_relevance=0, distraction_level=2),
    ],
)
def test_component_conflicts_are_scorable_but_downgraded_to_neutral(scorer, payload):
    result = scorer._normalize_response(payload, 0.0, "")

    assert result["review_required"] is False
    assert result["category_type"] == "neutral"
    assert result["status"] == "轻微偏离"
    assert "已降为证据不足" in result["reason"]


def test_complete_consistent_payload_remains_scorable(scorer):
    result = scorer._normalize_response(
        _valid_payload(
            category_type="focus",
            category_label="代码编辑器",
            goal_relevance=4,
            task_evidence=4,
            context_fit=4,
            distraction_level=0,
            confidence=0.9,
            reason="截图显示正在编辑与目标相关的 Python 代码",
        ),
        0.0,
        "",
    )

    assert result["review_required"] is False
    assert result["category_type"] == "focus"
    assert result["confidence"] == 0.9
    assert result["goal_relevance_score"] == 100.0
    assert result["task_evidence_score"] == 100.0
    assert result["context_fit_score"] == 100.0
    assert result["distraction_score"] == 0.0
    assert result["focus_score"] == 97.5


def test_focus_home_timer_without_work_evidence_is_not_focused(scorer):
    result = scorer._normalize_response(
        _valid_payload(
            category_type="focus",
            category_label="专注任务执行中",
            goal_relevance=4,
            task_evidence=3,
            context_fit=4,
            distraction_level=0,
            confidence=0.95,
            reason="画面只显示当前目标文字，专注工具正在运行并显示倒计时39:58",
        ),
        0.0,
        "",
        build_goal_profile("完成自己的研究任务"),
    )

    assert result["category_type"] == "neutral"
    assert result["task_evidence_score"] == 25.0
    assert result["score_breakdown"]["focus_home_guard_applied"] == 1.0
    assert result["score_breakdown"]["model_task_evidence_level"] == 3.0
    assert "专注小窝自身页面未出现实际开发证据" in result["reason"]


def test_focus_home_development_with_visible_code_evidence_can_be_focused(scorer):
    result = scorer._normalize_response(
        _valid_payload(
            category_type="focus",
            category_label="代码编辑器",
            goal_relevance=4,
            task_evidence=3,
            context_fit=4,
            distraction_level=0,
            confidence=0.95,
            reason="截图显示正在编辑专注小窝的 Flask 源码，并运行 pytest 测试结果",
        ),
        0.0,
        "",
        build_goal_profile("测试专注小窝后端"),
    )

    assert result["category_type"] == "focus"
    assert result["task_evidence_score"] == 75.0
    assert result["score_breakdown"]["focus_home_guard_applied"] == 0.0


def test_model_does_not_supply_total_and_service_calculates_it(scorer):
    result = scorer._normalize_response(
        _valid_payload(
            category_type="neutral",
            goal_relevance=2,
            task_evidence=2,
            context_fit=2,
            distraction_level=2,
            confidence=1.0,
        ),
        0.0,
        "",
    )

    assert result["review_required"] is False
    assert result["focus_score"] == 50.0
    assert result["focus_probability"] == 0.5
    assert result["score_breakdown"]["base_score"] == 50.0


def test_legacy_extra_fields_are_ignored_and_compatibility_fields_stay_empty(scorer):
    payload = _valid_payload(
        semantic_match_score=0.99,
        keyword_hit_score=0.98,
        strong_hit_score=0.97,
        coverage_score=0.96,
        structure_score=0.95,
        app_context_score=0.94,
        relevance_score=0.93,
        ocr_text="不得进入结果的 OCR",
        ocr_quality=1.0,
        matched_keywords=["伪证据"],
        strong_hits=["伪强证据"],
        positive_rule="伪规则",
        status="分心",
    )

    result = scorer._normalize_response(payload, 0.88, "调用方传入的旧 OCR")

    assert result["review_required"] is False
    assert result["status"] == "轻微偏离"
    assert result["ocr_text"] == ""
    assert result["ocr_quality"] == 0.0
    assert result["semantic_match_score"] == 0.0
    assert result["keyword_hit_score"] == 0.0
    assert result["strong_hit_score"] == 0.0
    assert result["coverage_score"] == 0.0
    assert result["structure_score"] == 0.0
    assert result["app_context_score"] == 0.0
    assert result["relevance_score"] == 0.5
    assert result["matched_keywords"] == []
    assert result["strong_hits"] == []
    assert result["positive_rule"] == ""


def test_prompt_declares_multidim_contract_and_no_model_total(scorer):
    system_prompt, _ = scorer._build_text_prompt(build_goal_profile("学习 Python"), "screen.jpg")

    assert "0-4 整数维度" in system_prompt
    assert "不要计算或输出总分" in system_prompt
    assert "专注小窝自身页面仅显示目标文字时" in system_prompt


def test_unscorable_result_keeps_all_components_null(scorer):
    result = scorer._normalize_response({}, 0.0, "")

    assert result["goal_relevance_score"] is None
    assert result["task_evidence_score"] is None
    assert result["context_fit_score"] is None
    assert result["distraction_score"] is None


def test_analyze_propagates_invalid_json_as_review_without_caching(monkeypatch):
    scorer = SiliconFlowVlmScorer(replace(DEFAULT_CONFIG, siliconflow_api_key="test-key"))
    monkeypatch.setattr(scorer, "_request_completion", lambda *args, **kwargs: {"category_type": "focus"})

    result = scorer.analyze(
        build_goal_profile("学习 Python"),
        "screen.jpg",
        np.zeros((32, 32, 3), dtype=np.uint8),
        "hash",
    )

    assert result["review_required"] is True
    assert result["score_breakdown"]["llm_scored"] == 0.0
    assert len(scorer.cache._data) == 0


def test_bypass_cache_forces_a_fresh_model_request(monkeypatch):
    scorer = SiliconFlowVlmScorer(replace(DEFAULT_CONFIG, siliconflow_api_key="test-key"))
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(1)
        return _valid_payload()

    monkeypatch.setattr(scorer, "_request_completion", fake_request)
    profile = build_goal_profile("学习 Python")
    image = np.zeros((32, 32, 3), dtype=np.uint8)

    first = scorer.analyze(profile, "screen.jpg", image, "hash")
    cached = scorer.analyze(profile, "screen.jpg", image, "hash")
    refreshed = scorer.analyze(
        profile,
        "screen.jpg",
        image,
        "hash",
        bypass_cache=True,
    )

    assert first["cache_hit"] is False
    assert cached["cache_hit"] is True
    assert refreshed["cache_hit"] is False
    assert len(calls) == 2


def test_session_summary_handles_missing_average_without_claiming_human_attention(scorer):
    text = scorer.generate_session_summary(
        "学习 Python",
        {
            "focus_ratio": 0,
            "avg_focus_score": None,
            "top_context": "通用工具",
            "top_distractor": "无",
            "focus_count": 0,
            "distract_count": 0,
        },
    )

    assert "没有足够明确的画面" in text
    assert "这不等于你本人没有专注" in text
    assert "平均专注得分" not in text
