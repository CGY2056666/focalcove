from __future__ import annotations

import math
import re
from statistics import median
from typing import Any
from collections import Counter

from .models import FrameAnalysis, GoalProfile
from .ocr_cleanup import clean_ocr_text, score_ocr_quality, OCR_REPLACEMENTS  # noqa: F401  # re-export
from .scoring_policy import (
    DEFAULT_SCORING_POLICY,
    SCORE_VERSION,
    ScoringPolicy,
    score_components,
)
from .utils import clamp, normalize_text, dedupe_terms

# VLM 路径平滑权重
VLM_SMOOTHING_SELF_WEIGHT = 0.88
VLM_SMOOTHING_CONSISTENCY_WEIGHT = 0.12

_REASON_TRAILING_PUNCTUATION = re.compile(r"[，,。.!！?？；;：:]+$")

# 窗口一致性权重
CONSISTENCY_FOCUS_RATIO_WEIGHT = 0.34
CONSISTENCY_CATEGORY_WEIGHT = 0.24
CONSISTENCY_KEYWORD_WEIGHT = 0.22
CONSISTENCY_RELEVANCE_WEIGHT = 0.20
CONSISTENCY_FOCUS_BONUS = 0.06
WINDOW_CONSISTENCY_HISTORY = 3
TEMPORAL_EVIDENCE_MAX_AGE_SECONDS = 60.0

# 回退评分
FALLBACK_OCR_QUALITY = 0.0

# 统一四态判定。数值分数只用于趋势，不再反向覆盖模型的语义类别。
FOCUSED_CONFIDENCE_MIN = DEFAULT_SCORING_POLICY.focused_confidence_min
DISTRACTED_CONFIDENCE_MIN = DEFAULT_SCORING_POLICY.distracted_confidence_min
HIGH_CONFIDENCE_STATE_MIN = DEFAULT_SCORING_POLICY.high_confidence_min
STABLE_STATE_WINDOW = DEFAULT_SCORING_POLICY.stable_window
STABLE_STATE_SUPPORT = DEFAULT_SCORING_POLICY.stable_support
VALID_STATES = {"focused", "uncertain", "distracted", "unscorable"}
STATE_TO_STATUS = {
    "focused": "专注",
    "uncertain": "轻微偏离",
    "distracted": "分心",
    "unscorable": "待复核",
}


def _is_reused_observation(item: FrameAnalysis) -> bool:
    """复用帧延长已有状态的持续时间，但不构成一条新模型证据。"""
    return (
        bool(item.cache_hit)
        or bool(item.duplicate_of)
        or item.source == "reuse"
        or item.scoring_source == "reuse"
    )


def _prior_independent_observations(
    items: list[FrameAnalysis],
    index: int,
    *,
    max_age_seconds: float = TEMPORAL_EVIDENCE_MAX_AGE_SECONDS,
) -> list[FrameAnalysis]:
    current = items[index]
    observations: list[FrameAnalysis] = []
    for observation in items[:index]:
        if _is_reused_observation(observation):
            continue
        if current.captured_at > 0 and observation.captured_at > 0:
            age = current.captured_at - observation.captured_at
            if age < 0 or age > max_age_seconds:
                continue
        observations.append(observation)
    return observations


def _reuse_source(items: list[FrameAnalysis], index: int) -> FrameAnalysis | None:
    item = items[index]
    if not _is_reused_observation(item):
        return None
    if item.duplicate_of:
        for candidate in reversed(items[:index]):
            if candidate.filename == item.duplicate_of:
                return candidate
    return items[index - 1] if index > 0 else None


def window_consistency(
    items: list[FrameAnalysis],
    index: int,
    radius: int = WINDOW_CONSISTENCY_HISTORY,
) -> float:
    # 对外保留旧字段名，但含义已改为最近独立画面分数中位数（0..1）。
    neighbors = [
        observation
        for observation in _prior_independent_observations(items, index)[-radius:]
        if observation.image_valid
        and not observation.review_required
        and observation.state != "unscorable"
        and math.isfinite(float(observation.focus_score))
    ]
    if not neighbors:
        return 0.0
    return round(clamp(median(neighbor.focus_score for neighbor in neighbors) / 100.0), 3)


def _build_decision_reason(item: FrameAnalysis) -> str:
    reasons: list[str] = []
    if item.base_decision_reason:
        reasons.append(item.base_decision_reason)
    elif item.positive_rule:
        reasons.append(item.positive_rule)
    elif item.strong_hit_score >= 0.72:
        reasons.append("命中了高置信度目标关键词")
    elif item.keyword_hit_score >= 0.38:
        reasons.append("命中了多组相关关键词")
    elif item.semantic_match_score >= 0.38:
        reasons.append("OCR 文本与目标语义接近")
    else:
        reasons.append("直接文本证据偏弱")

    if item.structure_score >= 0.55:
        reasons.append("页面结构与目标场景高度一致")

    if item.category_label:
        reasons.append(f"当前场景为“{item.category_label}”")

    has_temporal_evidence = (
        "temporal_evidence_count" not in item.score_breakdown
        or int(item.score_breakdown.get("temporal_evidence_count", 0)) > 0
    )
    if has_temporal_evidence and item.window_consistency_score >= 0.72:
        reasons.append("前后截图保持连续一致")
    elif has_temporal_evidence and item.window_consistency_score < 0.40 and not item.review_required:
        reasons.append("前后截图切换较频繁")

    should_include_negative_rule = (
        item.category_type == "distract"
        or item.status == "分心"
        or item.distraction_score >= 0.60
    )
    if item.negative_rule and should_include_negative_rule:
        reasons.append(item.negative_rule)
    elif item.distraction_score >= 0.80:
        reasons.append("与当前目标偏离较明显")

    return _join_decision_reasons(reasons)


def _join_decision_reasons(reasons: list[str]) -> str:
    cleaned = [
        _REASON_TRAILING_PUNCTUATION.sub("", reason.strip())
        for reason in dedupe_terms(reasons)
    ]
    return "，".join(reason for reason in cleaned if reason)


def _scored_items(items: list[FrameAnalysis]) -> list[FrameAnalysis]:
    return [
        item
        for item in items
        if item.image_valid
        and not item.review_required
        and item.state in {"focused", "uncertain", "distracted"}
    ]


def expected_observation_count(
    elapsed_seconds: float,
    interval_seconds: float = 20,
    planned_seconds: float | None = None,
) -> int:
    """首帧即时采集时，截至当前时刻理论上应出现的观测数。"""
    interval = float(interval_seconds)
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval_seconds must be positive and finite")
    elapsed = float(elapsed_seconds)
    if not math.isfinite(elapsed):
        elapsed = 0.0
    count = math.floor(max(0.0, elapsed) / interval) + 1
    if planned_seconds is not None:
        planned = float(planned_seconds)
        if not math.isfinite(planned):
            planned = 0.0
        maximum = math.ceil(max(0.0, planned) / interval)
        count = min(count, maximum)
    return max(0, count)


def _record_raw_observation(
    item: FrameAnalysis,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> None:
    if item.raw_state in VALID_STATES and item.raw_category:
        return
    item.raw_category = str(item.category_type or "neutral").strip().lower()
    item.raw_confidence = round(clamp(item.score_confidence), 3)
    if not item.image_valid or item.review_required:
        item.raw_state = "unscorable"
        return

    has_components = all(
        value is not None
        for value in (
            item.goal_relevance_score,
            item.task_evidence_score,
            item.context_fit_score,
            item.distraction_score,
        )
    )
    if has_components:
        if item.raw_category == "focus" and not (
            float(item.goal_relevance_score) >= 75.0
            and float(item.task_evidence_score) >= 50.0
            and float(item.distraction_score) <= 0.25
        ):
            item.raw_category = "neutral"
        elif item.raw_category == "distract" and not (
            float(item.distraction_score) >= 0.75
            and float(item.goal_relevance_score) <= 25.0
        ):
            item.raw_category = "neutral"
        item.category_type = item.raw_category

    if item.raw_category == "focus" and item.raw_confidence >= policy.focused_confidence_min:
        item.raw_state = "focused"
    elif item.raw_category == "distract" and item.raw_confidence >= policy.distracted_confidence_min:
        item.raw_state = "distracted"
    else:
        item.raw_state = "uncertain"


def stable_frame_state(
    items: list[FrameAnalysis],
    index: int,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> str:
    """根据最近三个独立原始观测生成因果稳定态。"""
    item = items[index]
    if _is_reused_observation(item):
        source = _reuse_source(items, index)
        if source is not None and source.state in VALID_STATES:
            return source.state
        if item.state in VALID_STATES:
            return item.state
    if item.raw_state == "unscorable":
        return "unscorable"
    if item.raw_state == "uncertain":
        return "uncertain"

    # 先截取时间窗，再统计同类票。unscorable 虽然不会投票，但必须占据
    # 窗口位置；否则一次模型失败会被过滤掉，让更早的旧票跨失败继续生效。
    recent = (
        _prior_independent_observations(items, index) + [item]
    )[-policy.stable_window:]

    if item.raw_state == "distracted":
        if item.raw_confidence >= policy.high_confidence_min:
            return "distracted"
        if item.raw_confidence < policy.distracted_confidence_min:
            return "uncertain"
        support = sum(
            observation.raw_state == "distracted"
            and observation.raw_confidence >= policy.distracted_confidence_min
            for observation in recent
        )
        return "distracted" if support >= policy.stable_support else "uncertain"

    if item.raw_confidence >= policy.high_confidence_min:
        return "focused"
    if item.raw_confidence < policy.focused_confidence_min:
        return "uncertain"
    support = sum(
        observation.raw_state == "focused"
        and observation.raw_confidence >= policy.focused_confidence_min
        for observation in recent
    )
    return "focused" if support >= policy.stable_support else "uncertain"


def classify_frame_state(
    item: FrameAnalysis,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> str:
    """向后兼容的单帧入口；普通置信度需要更多帧支持。"""
    _record_raw_observation(item, policy)
    return stable_frame_state([item], 0, policy)


def _has_multidim_components(item: FrameAnalysis) -> bool:
    return all(
        value is not None
        for value in (
            item.goal_relevance_score,
            item.task_evidence_score,
            item.context_fit_score,
            item.distraction_score,
        )
    )


def _finalize_multidim_frame(
    items: list[FrameAnalysis],
    index: int,
    policy: ScoringPolicy,
) -> None:
    item = items[index]
    assert item.goal_relevance_score is not None
    assert item.task_evidence_score is not None
    assert item.context_fit_score is not None
    assert item.distraction_score is not None

    calculated = score_components(
        item.goal_relevance_score,
        item.task_evidence_score,
        item.context_fit_score,
        item.distraction_score,
        item.score_confidence,
        policy,
    )
    if item.raw_focus_score is None:
        item.raw_focus_score = calculated["confidence_adjusted_score"]
    if item.raw_distraction_score is None:
        item.raw_distraction_score = round(float(item.distraction_score), 3)

    prior_scores = [
        float(observation.focus_score)
        for observation in _prior_independent_observations(items, index)[
            -WINDOW_CONSISTENCY_HISTORY:
        ]
        if observation.image_valid
        and not observation.review_required
        and observation.state != "unscorable"
        and observation.score_version == SCORE_VERSION
        and math.isfinite(float(observation.focus_score))
    ]
    reference_median = median(prior_scores) if prior_scores else None
    item.window_consistency_score = (
        round(clamp(reference_median / 100.0), 3)
        if reference_median is not None
        else 0.0
    )
    if reference_median is None:
        smoothed_score = float(item.raw_focus_score)
    else:
        temporal_weight = policy.temporal_consistency_weight
        smoothed_score = (
            (1.0 - temporal_weight) * float(item.raw_focus_score)
            + temporal_weight * reference_median
        )

    item.score_version = SCORE_VERSION
    item.relevance_score = round(clamp(float(item.goal_relevance_score) / 100.0), 3)
    item.base_relevance_score = item.relevance_score
    item.focus_score = round(max(0.0, min(smoothed_score, 100.0)), 1)
    item.focus_probability = round(item.focus_score / 100.0, 3)
    _record_raw_observation(item, policy)
    item.state = stable_frame_state(items, index, policy)
    item.status = STATE_TO_STATUS[item.state]
    item.score_breakdown.update(
        {
            "score_version": SCORE_VERSION,
            **calculated,
            "temporal_reference_median": (
                round(reference_median, 3) if reference_median is not None else None
            ),
            "temporal_smoothed_score": round(item.focus_score, 3),
            "window_consistency_score": round(item.window_consistency_score, 3),
            "temporal_evidence_count": float(len(prior_scores)),
            "raw_focus_score": round(float(item.raw_focus_score), 3),
            "raw_distraction_score": round(float(item.raw_distraction_score), 3),
            "temporal_consistency_weight": round(
                policy.temporal_consistency_weight,
                3,
            ),
            "focus_probability": round(item.focus_probability, 3),
        }
    )
    item.decision_reason = _build_decision_reason(item)


def finalize_frame_scores(
    items: list[FrameAnalysis],
    *,
    start_index: int = 0,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> list[FrameAnalysis]:
    if not items:
        return items

    start_index = max(0, min(start_index, len(items)))
    for index in range(start_index, len(items)):
        item = items[index]
        reuse_source = _reuse_source(items, index)
        if reuse_source is not None:
            # 静止画面只是同一证据在时间上的延续，沿用源帧最终结果，不重新平滑或投票。
            item.raw_focus_score = reuse_source.raw_focus_score
            item.raw_distraction_score = reuse_source.raw_distraction_score
            item.raw_state = reuse_source.raw_state
            item.raw_confidence = reuse_source.raw_confidence
            item.raw_category = reuse_source.raw_category
            item.score_version = reuse_source.score_version
            item.goal_relevance_score = reuse_source.goal_relevance_score
            item.task_evidence_score = reuse_source.task_evidence_score
            item.context_fit_score = reuse_source.context_fit_score
            item.distraction_score = reuse_source.distraction_score
            item.window_consistency_score = reuse_source.window_consistency_score
            item.relevance_score = reuse_source.relevance_score
            item.focus_probability = reuse_source.focus_probability
            item.focus_score = reuse_source.focus_score
            item.state = reuse_source.state
            item.status = reuse_source.status
            item.decision_reason = reuse_source.decision_reason
            item.score_breakdown = dict(reuse_source.score_breakdown)
            item.score_breakdown["reused_evidence"] = 1.0
            continue
        if not item.image_valid or item.review_required:
            item.score_version = SCORE_VERSION
            item.goal_relevance_score = None
            item.task_evidence_score = None
            item.context_fit_score = None
            item.distraction_score = None
            item.raw_distraction_score = None
            item.raw_focus_score = None
            item.raw_category = str(item.category_type or "neutral").strip().lower()
            item.raw_confidence = round(clamp(item.score_confidence), 3)
            item.raw_state = "unscorable"
            item.window_consistency_score = 0.0
            item.focus_score = 0.0
            item.focus_probability = 0.0
            item.state = "unscorable"
            item.status = "无法分析" if not item.image_valid else STATE_TO_STATUS[item.state]
            if not item.decision_reason:
                item.decision_reason = (
                    item.fallback_reason
                    or "视觉模型评分失败，请检查 API Key 与网络后重试。"
                )
            item.score_breakdown.update(
                {
                    "score_version": SCORE_VERSION,
                    "base_score": None,
                    "confidence_adjusted_score": None,
                    "temporal_reference_median": None,
                    "temporal_smoothed_score": None,
                    "temporal_evidence_count": 0.0,
                    "reused_evidence": 0.0,
                }
            )
            continue
        if _has_multidim_components(item):
            _finalize_multidim_frame(items, index, policy)
            continue

        # 只为现有测试替身和旧批处理对象保留展示兼容；实际 multidim-v1
        # 模型响应若缺少组件会在 VLM 校验阶段进入 unscorable。
        item.score_version = "legacy-v1"
        # 冻结原始数值，避免重复 finalize 或静态帧复用时再次处理上次结果。
        if item.raw_focus_score is None:
            raw_focus_score = float(item.focus_score)
            item.raw_focus_score = round(raw_focus_score, 3) if math.isfinite(raw_focus_score) else 0.0
        if item.raw_distraction_score is None:
            raw_distraction_score = float(item.distraction_score)
            item.raw_distraction_score = (
                round(raw_distraction_score, 3) if math.isfinite(raw_distraction_score) else 0.0
            )
        temporal_evidence_count = len(
            [
                observation
                for observation in _prior_independent_observations(items, index)[
                    -WINDOW_CONSISTENCY_HISTORY:
                ]
                if observation.image_valid and observation.state != "unscorable"
            ]
        )
        item.window_consistency_score = window_consistency(items, index)
        composite_before_temporal_score = float(item.raw_focus_score)

        if item.scoring_source in {"deepseek", "siliconflow", "bailian", "reuse"}:
            item.relevance_score = round(clamp(item.base_relevance_score or item.relevance_score), 3)
            raw_focus_probability = clamp(float(item.raw_focus_score) / 100.0)
            composite_before_temporal_score = raw_focus_probability * 100.0
            if item.score_confidence < 0.35 or temporal_evidence_count == 0:
                smoothed_probability = raw_focus_probability
            else:
                temporal_weight = policy.temporal_consistency_weight
                smoothed_probability = clamp(
                    (1.0 - temporal_weight) * raw_focus_probability
                    + temporal_weight * item.window_consistency_score
                )
            item.focus_probability = round(smoothed_probability, 3)
            item.focus_score = round(item.focus_probability * 100, 1)
            # 真正被判为 distract 的帧强制封顶，防止平滑后越界
            if item.category_type == "distract" and item.distraction_score >= 0.60:
                item.focus_score = min(item.focus_score, 30.0)
                item.focus_probability = min(item.focus_probability, 0.30)
        else:
            base_relevance = item.base_relevance_score or item.relevance_score
            if temporal_evidence_count:
                relevance = (
                    0.76 * base_relevance
                    + 0.17 * item.window_consistency_score
                    + 0.07 * (1 - item.distraction_score)
                )
            else:
                # 无历史时只归一化当前帧已有信号，不把“缺少历史”当成负面证据。
                relevance = (
                    0.76 * base_relevance + 0.07 * (1 - item.distraction_score)
                ) / 0.83

            neighbors = [
                neighbor
                for neighbor in _prior_independent_observations(items, index)[
                    -WINDOW_CONSISTENCY_HISTORY:
                ]
                if neighbor.image_valid and not neighbor.review_required
            ]
            focused_neighbors = [
                neighbor
                for neighbor in neighbors
                if neighbor.category_type == "focus"
                and (neighbor.base_relevance_score or neighbor.relevance_score) >= 0.64
            ]
            strong_negative_override = item.category_type == "distract" and item.distraction_score >= 0.85

            if neighbors and not strong_negative_override:
                focused_neighbor_ratio = len(focused_neighbors) / len(neighbors)
                if focused_neighbor_ratio >= 0.67 and item.category_type != "distract":
                    floor = 0.64 if max(item.strong_hit_score, item.structure_score, item.app_context_score) >= 0.40 else 0.60
                    if relevance < floor:
                        relevance = floor
                        if not item.positive_rule:
                            item.positive_rule = "连续多帧保持同类专注场景"

            item.relevance_score = round(clamp(relevance), 3)
            item.focus_probability = round(
                clamp(
                    0.58 * item.relevance_score
                    + 0.24 * item.app_context_score
                    + 0.12 * item.strong_hit_score
                    + 0.06 * (1 - item.distraction_score)
                ),
                3,
            )
            item.focus_score = round(clamp(item.focus_probability) * 100, 1)

            composite_score = item.focus_score
            composite_before_temporal_score = composite_score
            item.focus_score = round(composite_score, 1)
            item.focus_probability = round(composite_score / 100.0, 3)

        _record_raw_observation(item, policy)
        item.state = stable_frame_state(items, index, policy)
        item.status = STATE_TO_STATUS[item.state]

        item.score_breakdown.update(
            {
                "window_consistency_score": round(item.window_consistency_score, 3),
                "temporal_evidence_count": float(temporal_evidence_count),
                "final_relevance_score": round(item.relevance_score, 3),
                "focus_probability": round(item.focus_probability, 3),
                "raw_focus_score": round(float(item.raw_focus_score), 3),
                "raw_distraction_score": round(float(item.raw_distraction_score), 3),
                "composite_focus_score": round(composite_before_temporal_score, 3),
                "temporal_consistency_weight": round(policy.temporal_consistency_weight, 3),
            }
        )
        item.decision_reason = _build_decision_reason(item)

    return items


def fallback_scoring(profile: GoalProfile, frame: Any) -> dict[str, Any]:
    """模型不可用时返回待复核，不制造没有截图证据的本地分数。"""
    return {
        "score_version": SCORE_VERSION,
        "ocr_text": "",
        "ocr_quality": FALLBACK_OCR_QUALITY,
        "category_type": "neutral",
        "category_label": "待复核场景",
        "semantic_match_score": 0.0,
        "keyword_hit_score": 0.0,
        "strong_hit_score": 0.0,
        "coverage_score": 0.0,
        "structure_score": 0.0,
        "app_context_score": 0.0,
        "relevance_score": 0.0,
        "goal_relevance_score": None,
        "task_evidence_score": None,
        "context_fit_score": None,
        "distraction_score": None,
        "focus_score": 0.0,
        "focus_probability": 0.0,
        "confidence": 0.0,
        "status": "待复核",
        "matched_keywords": [],
        "strong_hits": [],
        "scene_hits": [],
        "support_hits": [],
        "negative_hits": [],
        "matched_context_patterns": [],
        "positive_rule": "",
        "negative_rule": "",
        "reason": "视觉模型暂时不可用，本帧未参与评分。",
        "fallback_reason": "视觉模型调用失败，本帧待复核。",
        "review_required": True,
        "score_breakdown": {
            "score_version": SCORE_VERSION,
            "goal_relevance_level": None,
            "task_evidence_level": None,
            "context_fit_level": None,
            "distraction_level": None,
            "semantic_score": 0.0,
            "strong_hit_score": 0.0,
            "coverage_score": 0.0,
            "keyword_hit_score": 0.0,
            "structure_score": 0.0,
            "app_context_score": 0.0,
            "ocr_quality_score": FALLBACK_OCR_QUALITY,
            "base_relevance_score": 0.0,
            "distraction_score": None,
            "confidence": 0.0,
            "llm_scored": 0.0,
        },
    }


def _estimated_state_seconds(
    items: list[FrameAnalysis],
    default_interval: float = 15.0,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict[str, float]:
    timed = sorted(
        (item for item in items if item.captured_at > 0),
        key=lambda item: item.captured_at,
    )
    if not timed:
        totals = {state: 0.0 for state in VALID_STATES}
        if start_time is not None and end_time is not None:
            totals["unscorable"] = max(0.0, float(end_time) - float(start_time))
        return totals

    gaps = [
        timed[index].captured_at - timed[index - 1].captured_at
        for index in range(1, len(timed))
        if 0 < timed[index].captured_at - timed[index - 1].captured_at <= 60
    ]
    inferred_interval = median(gaps) if gaps else default_interval
    timeline_start = float(start_time) if start_time is not None else timed[0].captured_at
    timeline_end = (
        float(end_time)
        if end_time is not None
        else timed[-1].captured_at + inferred_interval
    )
    timeline_end = max(timeline_start, timeline_end)
    totals = {state: 0.0 for state in VALID_STATES}
    cursor = timeline_start
    for index, item in enumerate(timed):
        item_start = min(max(float(item.captured_at), timeline_start), timeline_end)
        if item_start > cursor:
            totals["unscorable"] += item_start - cursor
        if index + 1 < len(timed):
            item_end = min(float(timed[index + 1].captured_at), timeline_end)
        else:
            item_end = timeline_end
        represented_end = min(max(item_end, item_start), item_start + 30.0)
        state = item.state if item.image_valid and item.state in VALID_STATES else "unscorable"
        totals[state] += max(0.0, represented_end - item_start)
        cursor = max(cursor, represented_end)
    if cursor < timeline_end:
        totals["unscorable"] += timeline_end - cursor
    return totals


def _estimated_item_seconds(
    items: list[FrameAnalysis],
    default_interval: float = 15.0,
    start_time: float | None = None,
    end_time: float | None = None,
) -> list[tuple[FrameAnalysis, float]]:
    """按与状态时长相同的因果时间轴估算每个观测代表的秒数。"""

    timed = sorted(
        (item for item in items if item.captured_at > 0),
        key=lambda item: item.captured_at,
    )
    if not timed:
        return [(item, 1.0) for item in items]

    gaps = [
        timed[index].captured_at - timed[index - 1].captured_at
        for index in range(1, len(timed))
        if 0 < timed[index].captured_at - timed[index - 1].captured_at <= 60
    ]
    inferred_interval = median(gaps) if gaps else default_interval
    timeline_start = float(start_time) if start_time is not None else timed[0].captured_at
    timeline_end = (
        float(end_time)
        if end_time is not None
        else timed[-1].captured_at + inferred_interval
    )
    timeline_end = max(timeline_start, timeline_end)
    represented: list[tuple[FrameAnalysis, float]] = []
    for index, item in enumerate(timed):
        item_start = min(max(float(item.captured_at), timeline_start), timeline_end)
        if index + 1 < len(timed):
            item_end = min(float(timed[index + 1].captured_at), timeline_end)
        else:
            item_end = timeline_end
        represented_end = min(max(item_end, item_start), item_start + 30.0)
        represented.append((item, max(0.0, represented_end - item_start)))
    return represented


def _weighted_average(
    weighted_items: list[tuple[FrameAnalysis, float]],
    attribute: str,
    *,
    digits: int = 1,
) -> float | None:
    values = [
        (float(value), seconds)
        for item, seconds in weighted_items
        if seconds > 0
        and (value := getattr(item, attribute, None)) is not None
        and math.isfinite(float(value))
    ]
    total_seconds = sum(seconds for _, seconds in values)
    if total_seconds <= 0:
        return None
    return round(
        sum(value * seconds for value, seconds in values) / total_seconds,
        digits,
    )


def summary_suggestions(profile: GoalProfile, items: list[FrameAnalysis]) -> list[str]:
    image_items = [item for item in items if item.image_valid]
    scored_items = _scored_items(items)
    if not image_items:
        return ["请先上传清晰截图，以便系统提取有效文本和场景证据。"]
    if not scored_items:
        return ["截图已收到，但视觉模型评分暂不可用，请检查 API Key、模型名称与配额后重试。"]

    suggestions: list[str] = []
    distracted_items = [item for item in scored_items if item.state == "distracted"]
    uncertain_items = [item for item in scored_items if item.state == "uncertain"]

    # The six-field VLM contract deliberately removed OCR/keyword/structure
    # sub-scores. Suggestions must therefore use actual states, not zeros in
    # compatibility fields that would make every session look poorly framed.
    if distracted_items:
        suggestions.append("可以回看那些与当前目标偏离较明显的截图，判断这类页面是否需要单独安排到别的时段处理。")
    if uncertain_items:
        suggestions.append(
            f"部分画面与“{profile.raw_goal}”的关系不够明确；下次可把目标写得更具体，并让共享范围保留当前任务的标题或主要内容。"
        )
    if not suggestions:
        suggestions.append("当前任务线索比较稳定，可以继续沿用这组学习环境和截图方式。")
    return suggestions


def build_summary(
    profile: GoalProfile,
    items: list[FrameAnalysis],
    processing_ms: int,
    start_time: float | None = None,
    end_time: float | None = None,
    default_interval: float = 15.0,
) -> dict:
    image_items = [item for item in items if item.image_valid]
    scored_items = _scored_items(items)
    review_count = sum(item.review_required for item in image_items)
    focus_count = sum(item.status == "专注" for item in scored_items)
    drift_count = sum(item.status == "轻微偏离" for item in scored_items)
    distract_count = sum(item.status == "分心" for item in scored_items)
    uncertain_count = sum(item.state == "uncertain" for item in scored_items)
    cache_hits = sum(item.cache_hit for item in image_items)
    fallback_count = sum(item.used_fallback for item in image_items)
    unique_hashes = len({item.thumbnail_hash for item in image_items if item.thumbnail_hash})
    coverage_ratio = len(scored_items) / max(len(items), 1)
    state_seconds = _estimated_state_seconds(
        items,
        default_interval=default_interval,
        start_time=start_time,
        end_time=end_time,
    )
    timeline_seconds = sum(state_seconds.values())
    decisive_seconds = state_seconds["focused"] + state_seconds["distracted"]
    scorable_seconds = decisive_seconds + state_seconds["uncertain"]
    decisive_evidence_ratio = (
        decisive_seconds / scorable_seconds if scorable_seconds else 0.0
    )
    independent_decisive_count = sum(
        item.state in {"focused", "distracted"} and not _is_reused_observation(item)
        for item in scored_items
    )
    weighted_scored = [
        (item, seconds)
        for item, seconds in _estimated_item_seconds(
            items,
            default_interval=default_interval,
            start_time=start_time,
            end_time=end_time,
        )
        if item in scored_items
    ]
    avg_focus_score = _weighted_average(weighted_scored, "focus_score")
    avg_goal_relevance_score = _weighted_average(
        weighted_scored,
        "goal_relevance_score",
    )
    avg_task_evidence_score = _weighted_average(
        weighted_scored,
        "task_evidence_score",
    )
    avg_context_fit_score = _weighted_average(weighted_scored, "context_fit_score")
    avg_distraction_score = _weighted_average(
        weighted_scored,
        "distraction_score",
        digits=3,
    )
    frame_score_versions = {
        str(item.score_version or "legacy-v1").lower() for item in items
    }
    summary_score_version = (
        SCORE_VERSION
        if not frame_score_versions or frame_score_versions == {SCORE_VERSION}
        else "legacy-v1"
    )
    score_reliable = (
        coverage_ratio >= 0.70
        and independent_decisive_count >= 3
        and decisive_evidence_ratio >= 0.50
        and bool(scored_items)
        and summary_score_version == SCORE_VERSION
    )
    if coverage_ratio < 0.70:
        quality_status = "low_confidence"
        reliability_reason = "有效评分覆盖率不足70%"
    elif independent_decisive_count < 3:
        quality_status = "insufficient_evidence"
        reliability_reason = "非复用的明确状态画面少于3个"
    elif decisive_evidence_ratio < 0.50:
        quality_status = "insufficient_evidence"
        reliability_reason = "明确证据时间占可评分时间不足50%"
    elif summary_score_version != SCORE_VERSION:
        quality_status = "legacy_only"
        reliability_reason = "包含旧版评分，不能用于新版积分或推荐"
    else:
        quality_status = "reliable"
        reliability_reason = "覆盖率与明确证据均达到要求"

    top_context = Counter(item.category_label for item in scored_items).most_common(1)
    top_distractor = Counter(
        item.category_label
        for item in scored_items
        if item.state == "distracted"
    ).most_common(1)

    return {
        "goal": profile.raw_goal,
        "goal_id": profile.goal_type,
        "goal_label": profile.raw_goal,
        "goal_type": profile.goal_type,
        "keywords": profile.keywords[:10],
        "total_images": len(items),
        "valid_images": len(image_items),
        "scored_images": len(scored_items),
        "review_count": review_count,
        "focus_count": focus_count,
        "drift_count": drift_count,
        "distract_count": distract_count,
        "uncertain_count": uncertain_count,
        "unscorable_count": len(items) - len(scored_items),
        "valid_coverage_ratio": round(coverage_ratio, 3),
        "valid_coverage_percent": round(coverage_ratio * 100, 1),
        "score_version": summary_score_version,
        "quality_status": quality_status,
        "score_reliable": score_reliable,
        "score_reference_only": bool(scored_items) and not score_reliable,
        "score_reliability_reason": reliability_reason,
        "decisive_evidence_ratio": round(decisive_evidence_ratio, 3),
        "decisive_evidence_percent": round(decisive_evidence_ratio * 100, 1),
        "independent_decisive_count": independent_decisive_count,
        "distract_duration_seconds": round(state_seconds["distracted"], 1),
        "distracted_duration_seconds": round(state_seconds["distracted"], 1),
        "focus_duration_seconds": round(state_seconds["focused"], 1),
        "focused_duration_seconds": round(state_seconds["focused"], 1),
        "uncertain_duration_seconds": round(state_seconds["uncertain"], 1),
        "unscorable_duration_seconds": round(state_seconds["unscorable"], 1),
        "state_duration_seconds": {
            state: round(seconds, 1) for state, seconds in state_seconds.items()
        },
        "timeline_duration_seconds": round(timeline_seconds, 1),
        # 总体占比使用真实时间轴；待复核、缺失及不确定时间都留在分母中。
        "focus_ratio": round((state_seconds["focused"] / timeline_seconds) * 100, 1) if timeline_seconds else 0.0,
        "scored_focus_ratio": round((state_seconds["focused"] / decisive_seconds) * 100, 1) if decisive_seconds else 0.0,
        "avg_focus_score": avg_focus_score,
        "avg_goal_relevance_score": avg_goal_relevance_score,
        "avg_task_evidence_score": avg_task_evidence_score,
        "avg_context_fit_score": avg_context_fit_score,
        "avg_distraction_score": avg_distraction_score,
        "avg_relevance_score": (
            round(avg_goal_relevance_score / 100.0, 3)
            if avg_goal_relevance_score is not None
            else 0.0
        ),
        "avg_ocr_quality": round(sum(item.ocr_quality_score for item in scored_items) / max(len(scored_items), 1), 3),
        "avg_keyword_score": round(sum(item.keyword_hit_score for item in scored_items) / max(len(scored_items), 1), 3),
        "avg_semantic_score": round(sum(item.semantic_match_score for item in scored_items) / max(len(scored_items), 1), 3),
        "avg_strong_hit_score": round(sum(item.strong_hit_score for item in scored_items) / max(len(scored_items), 1), 3),
        "avg_coverage_score": round(sum(item.coverage_score for item in scored_items) / max(len(scored_items), 1), 3),
        "avg_structure_score": round(sum(item.structure_score for item in scored_items) / max(len(scored_items), 1), 3),
        "top_context": top_context[0][0] if top_context else ("待复核" if review_count else "暂无明显场景"),
        "top_distractor": top_distractor[0][0] if top_distractor else ("待复核" if review_count and not scored_items else "无明显高频偏离场景"),
        "cache_hits": cache_hits,
        "fallback_count": fallback_count,
        "unique_hashes": unique_hashes,
        "processing_ms": processing_ms,
        "throughput_images_per_sec": round(len(scored_items) / max(processing_ms / 1000, 0.001), 2),
        "suggestions": summary_suggestions(profile, items),
    }
