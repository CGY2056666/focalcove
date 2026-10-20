from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


SCORE_VERSION = "multidim-v1"


@dataclass(frozen=True)
class ScoringPolicy:
    """多维画面任务相关度策略；组件权重会自动归一化。"""

    score_version: str = SCORE_VERSION
    goal_relevance_weight: float = 0.50
    task_evidence_weight: float = 0.25
    context_fit_weight: float = 0.15
    inverse_distraction_weight: float = 0.10
    confidence_shrink_weight: float = 0.50
    temporal_consistency_weight: float = 0.12
    focused_confidence_min: float = 0.60
    distracted_confidence_min: float = 0.75
    high_confidence_min: float = 0.85
    stable_window: int = 3
    stable_support: int = 2

    def __post_init__(self) -> None:
        if str(self.score_version).strip() != SCORE_VERSION:
            raise ValueError(f"score_version must be {SCORE_VERSION}")
        object.__setattr__(self, "score_version", SCORE_VERSION)

        weight_names = (
            "goal_relevance_weight",
            "task_evidence_weight",
            "context_fit_weight",
            "inverse_distraction_weight",
        )
        weights: list[float] = []
        for name in weight_names:
            value = _finite_number(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
            weights.append(value)
        weight_sum = sum(weights)
        if weight_sum <= 0:
            raise ValueError("score weights must have a positive sum")
        for name, value in zip(weight_names, weights):
            object.__setattr__(self, name, value / weight_sum)

        unit_interval_names = (
            "confidence_shrink_weight",
            "temporal_consistency_weight",
            "focused_confidence_min",
            "distracted_confidence_min",
            "high_confidence_min",
        )
        for name in unit_interval_names:
            value = _finite_number(getattr(self, name), name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)
        if self.high_confidence_min < max(
            self.focused_confidence_min,
            self.distracted_confidence_min,
        ):
            raise ValueError(
                "high_confidence_min must be at least the focused and distracted thresholds"
            )

        stable_window = _positive_int(self.stable_window, "stable_window")
        stable_support = _positive_int(self.stable_support, "stable_support")
        if stable_support > stable_window:
            raise ValueError("stable_support must not exceed stable_window")
        object.__setattr__(self, "stable_window", stable_window)
        object.__setattr__(self, "stable_support", stable_support)

    def to_dict(self) -> dict[str, str | float | int]:
        return asdict(self)


@dataclass(frozen=True)
class ScoringPolicyLoadResult:
    policy: ScoringPolicy
    source: str
    error: str | None = None

    @property
    def loaded(self) -> bool:
        return self.source == "file"


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


DEFAULT_SCORING_POLICY = ScoringPolicy()

_POLICY_FIELDS = frozenset(ScoringPolicy.__dataclass_fields__)
_LEGACY_POLICY_FIELDS = frozenset({"focus_score_weight", "category_signal_weight"})


def scoring_policy_from_mapping(data: Mapping[str, Any]) -> ScoringPolicy:
    legacy = sorted(_LEGACY_POLICY_FIELDS & set(data))
    if legacy:
        raise ValueError(
            "legacy scoring policy fields are incompatible with multidim-v1: "
            + ", ".join(legacy)
        )
    missing = sorted(_POLICY_FIELDS - set(data))
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    unknown = sorted(set(data) - _POLICY_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")
    return ScoringPolicy(**{name: data[name] for name in _POLICY_FIELDS})


def load_scoring_policy(path: str | Path | None) -> ScoringPolicyLoadResult:
    """从 JSON 加载策略；任何错误都安全回退默认策略，并返回可展示原因。"""

    raw_path = str(path or "").strip()
    if not raw_path:
        return ScoringPolicyLoadResult(DEFAULT_SCORING_POLICY, "default")

    policy_path = Path(raw_path).expanduser()
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("policy JSON root must be an object")
        policy = scoring_policy_from_mapping(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        reason = f"评分策略加载失败，已使用 multidim-v1 默认策略：{exc}"
        return ScoringPolicyLoadResult(DEFAULT_SCORING_POLICY, "default", reason)
    return ScoringPolicyLoadResult(policy, "file")


def composite_focus_score(
    goal_relevance_score: float,
    task_evidence_score: float,
    context_fit_score: float,
    distraction_score: float,
    confidence: float,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> float:
    """合成置信度收缩后的 0..100 画面任务相关度。"""

    return score_components(
        goal_relevance_score,
        task_evidence_score,
        context_fit_score,
        distraction_score,
        confidence,
        policy,
    )["confidence_adjusted_score"]


def score_components(
    goal_relevance_score: float,
    task_evidence_score: float,
    context_fit_score: float,
    distraction_score: float,
    confidence: float,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> dict[str, float]:
    """返回基础分、置信度修正分和四项可审计贡献（单位均为分）。"""

    goal_signal = _clamp(_safe_number(goal_relevance_score, 0.0) / 100.0)
    evidence_signal = _clamp(_safe_number(task_evidence_score, 0.0) / 100.0)
    context_signal = _clamp(_safe_number(context_fit_score, 0.0) / 100.0)
    inverse_distraction = 1.0 - _clamp(_safe_number(distraction_score, 0.0))
    contributions = {
        "goal_relevance_contribution": 100.0 * policy.goal_relevance_weight * goal_signal,
        "task_evidence_contribution": 100.0 * policy.task_evidence_weight * evidence_signal,
        "context_fit_contribution": 100.0 * policy.context_fit_weight * context_signal,
        "inverse_distraction_contribution": 100.0
        * policy.inverse_distraction_weight
        * inverse_distraction,
    }
    base_score = sum(contributions.values())
    normalized_confidence = _clamp(_safe_number(confidence, 0.0))
    effective_confidence = (
        1.0
        - policy.confidence_shrink_weight
        + policy.confidence_shrink_weight * normalized_confidence
    )
    adjusted = 50.0 + (base_score - 50.0) * effective_confidence
    return {
        **{name: round(value, 3) for name, value in contributions.items()},
        "base_score": round(_clamp(base_score / 100.0) * 100.0, 3),
        "confidence_adjustment_factor": round(effective_confidence, 3),
        "confidence_adjusted_score": round(_clamp(adjusted / 100.0) * 100.0, 3),
    }


def _safe_number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
