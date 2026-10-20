"""从 app.py 提取的工具函数（通过 current_app.extensions 获取引擎实例）"""
from __future__ import annotations

import math
import logging

from flask import current_app, request, session

from focus_engine.goal_profiles import DEFAULT_GOAL_TEXT, GOAL_EXAMPLES, GOAL_PLACEHOLDER, normalize_goal_input
from focus_engine.scoring import expected_observation_count

logger = logging.getLogger(__name__)
RECENT_HISTORY_LIMIT = 6
DEFAULT_CAPTURE_INTERVAL_SECONDS = 15.0
RELIABLE_COVERAGE_THRESHOLD = 0.70
CURRENT_SCORE_VERSION = "multidim-v1"
LEGACY_SCORE_VERSION = "legacy-v1"
MIN_FRESH_DECISIVE_FRAMES = 3
MIN_DECISIVE_EVIDENCE_RATIO = 0.50


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value) -> float | None:
    """Parse an optional finite number without turning missing data into zero."""

    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def calculate_session_points(
    actual_duration: float,
    avg_focus_score: float,
    coverage_ratio: float = 1.0,
    *,
    score_version: str = CURRENT_SCORE_VERSION,
    score_reliable: bool = True,
) -> int:
    if score_version != CURRENT_SCORE_VERSION or not score_reliable:
        return 0
    coverage = max(0.0, min(1.0, _safe_float(coverage_ratio)))
    if coverage < RELIABLE_COVERAGE_THRESHOLD:
        return 0
    base_points = actual_duration
    focus_multiplier = max(0.0, min(3.0, avg_focus_score / 100 * 3))
    return max(0, math.floor(base_points * focus_multiplier * coverage))


def _history_score_is_reliable(entry: dict) -> bool:
    """Only complete, reliable multidimensional scores enter aggregates."""

    explicitly_eligible = _history_recommendation_eligibility(entry)
    if explicitly_eligible is not True:
        return False
    return (
        _history_score_version(entry) == CURRENT_SCORE_VERSION
        and _effective_history_coverage(entry) >= RELIABLE_COVERAGE_THRESHOLD
        and _optional_float(entry.get("completion_score")) is not None
        and _safe_int(entry.get("fresh_decisive_frames")) >= MIN_FRESH_DECISIVE_FRAMES
        and _safe_float(entry.get("decisive_evidence_ratio")) >= MIN_DECISIVE_EVIDENCE_RATIO
    )


def _history_score_version(entry: dict) -> str:
    value = str(entry.get("score_version") or "").strip().lower()
    return CURRENT_SCORE_VERSION if value == CURRENT_SCORE_VERSION else LEGACY_SCORE_VERSION


def _history_recommendation_eligibility(entry: dict) -> bool | None:
    """Resolve the multidimensional reliability gate; legacy data is display-only."""

    if _history_score_version(entry) != CURRENT_SCORE_VERSION:
        return False

    if entry.get("score_reliable") is False or entry.get("recommendation_eligible") is False:
        return False

    return bool(
        _effective_history_coverage(entry) >= RELIABLE_COVERAGE_THRESHOLD
        and _safe_int(entry.get("fresh_decisive_frames")) >= MIN_FRESH_DECISIVE_FRAMES
        and _safe_float(entry.get("decisive_evidence_ratio")) >= MIN_DECISIVE_EVIDENCE_RATIO
        and _optional_float(entry.get("completion_score")) is not None
    )


def _effective_history_coverage(entry: dict) -> float:
    """Return comparable v2 coverage for new and legacy history entries."""

    saved = _safe_float(entry.get("coverage_ratio"))
    if saved > 1.0:
        saved /= 100.0
    saved = max(0.0, min(1.0, saved))
    if _safe_int(entry.get("coverage_version")) >= 2 or entry.get("expected_observations") is not None:
        capture = entry.get("capture_coverage_ratio")
        success = entry.get("model_success_ratio")
        if capture is not None and success is not None:
            return round(
                max(0.0, min(1.0, _safe_float(capture)))
                * max(0.0, min(1.0, _safe_float(success))),
                6,
            )
        return saved

    # v1 only measured successful/submitted frames. Approximate the missing
    # capture denominator from elapsed minutes so old one-frame sessions do
    # not remain permanently marked as 100% reliable.
    actual_minutes = max(0.0, _safe_float(entry.get("actual_duration")))
    submitted = max(0, _safe_int(entry.get("captured_frames")))
    if actual_minutes <= 0 or submitted <= 0:
        return 0.0 if submitted == 0 else saved
    expected = max(1, math.ceil(actual_minutes * 60 / DEFAULT_CAPTURE_INTERVAL_SECONDS))
    capture = min(1.0, submitted / expected)
    return round(capture * saved, 6)


def build_duration_recommendation(goal: str | None, username=None) -> dict | None:
    normalized_goal = normalize_goal_input(goal) or DEFAULT_GOAL_TEXT
    try:
        from app.services.history_service import load_all

        recommender = current_app.extensions["duration_recommender"]
        history = load_all(username or "")
        return recommender.recommend(normalized_goal, username=username, history=history)
    except Exception as exc:
        logger.warning("failed to build duration recommendation: %s", exc)
        return None


def serialize_history_entry(entry: dict) -> dict:
    next_recommend = entry.get("next_recommend") or {}
    current_summary = entry.get("current_summary") or {}
    summary = entry.get("summary") or {}
    effective_coverage = _effective_history_coverage(entry)
    completion_score = _optional_float(entry.get("completion_score"))
    started_at = _optional_float(entry.get("started_at"))
    end_time = _optional_float(entry.get("end_time"))
    summary_focus_score = _optional_float(
        summary.get("avg_focus_score", entry.get("completion_score"))
    )
    current_completion_score = _optional_float(current_summary.get("completion_score"))
    score_version = _history_score_version(entry)
    score_reliable = _history_score_is_reliable(entry)
    recommendation_eligible = score_reliable
    decisive_evidence_ratio = max(
        0.0,
        min(1.0, _safe_float(entry.get("decisive_evidence_ratio"))),
    )
    avg_goal_relevance_score = _optional_float(
        entry.get("avg_goal_relevance_score", summary.get("avg_goal_relevance_score"))
    )
    avg_task_evidence_score = _optional_float(
        entry.get("avg_task_evidence_score", summary.get("avg_task_evidence_score"))
    )
    avg_context_fit_score = _optional_float(
        entry.get("avg_context_fit_score", summary.get("avg_context_fit_score"))
    )
    avg_distraction_risk_score = _optional_float(
        entry.get("avg_distraction_risk_score", summary.get("avg_distraction_risk_score"))
    )
    capture_interval_seconds = _optional_float(entry.get("capture_interval_seconds"))
    if capture_interval_seconds is not None and capture_interval_seconds <= 0:
        capture_interval_seconds = None
    return {
        "session_id": str(entry.get("session_id", "")),
        "goal": str(entry.get("goal", "")),
        "goal_type": str(entry.get("goal_type", "")),
        "plan_duration": _safe_int(entry.get("plan_duration")),
        "actual_duration": round(max(0.0, _safe_float(entry.get("actual_duration"))), 2),
        "actual_duration_seconds": round(
            max(
                0.0,
                _safe_float(
                    entry.get("actual_duration_seconds"),
                    _safe_float(entry.get("actual_duration")) * 60,
                ),
            ),
            1,
        ),
        "capture_interval_seconds": (
            round(capture_interval_seconds, 3)
            if capture_interval_seconds is not None
            else None
        ),
        "completion_score": round(completion_score, 1) if completion_score is not None else None,
        "score_version": score_version,
        "score_reliable": score_reliable,
        "decisive_evidence_ratio": round(decisive_evidence_ratio, 3),
        "avg_goal_relevance_score": (
            round(avg_goal_relevance_score, 1) if avg_goal_relevance_score is not None else None
        ),
        "avg_task_evidence_score": (
            round(avg_task_evidence_score, 1) if avg_task_evidence_score is not None else None
        ),
        "avg_context_fit_score": (
            round(avg_context_fit_score, 1) if avg_context_fit_score is not None else None
        ),
        "avg_distraction_risk_score": (
            round(avg_distraction_risk_score, 1) if avg_distraction_risk_score is not None else None
        ),
        "focus_ratio": round(_safe_float(entry.get("focus_ratio")), 1),
        "coverage_ratio": round(effective_coverage, 3),
        "capture_coverage_ratio": round(_safe_float(entry.get("capture_coverage_ratio")), 3),
        "model_success_ratio": round(_safe_float(entry.get("model_success_ratio")), 3),
        "expected_observations": _safe_int(entry.get("expected_observations")),
        "coverage_method": str(entry.get("coverage_method", "")),
        "coverage_version": _safe_int(entry.get("coverage_version")),
        "valid_frames": _safe_int(entry.get("valid_frames")),
        "captured_frames": _safe_int(entry.get("captured_frames")),
        "decisive_frames": _safe_int(entry.get("decisive_frames")),
        "fresh_decisive_frames": _safe_int(entry.get("fresh_decisive_frames")),
        "recommendation_eligible": recommendation_eligible,
        "started_at": started_at,
        "end_time": end_time,
        "feedback_text": str(entry.get("feedback_text", "")),
        "earned_points": _safe_int(entry.get("earned_points", 0)),
        "distract_duration_seconds": round(_safe_float(entry.get("distract_duration_seconds")), 1),
        "focus_duration_seconds": round(_safe_float(entry.get("focus_duration_seconds")), 1),
        "uncertain_duration_seconds": round(_safe_float(entry.get("uncertain_duration_seconds")), 1),
        "unscorable_duration_seconds": round(_safe_float(entry.get("unscorable_duration_seconds")), 1),
        "distract_count": _safe_int(entry.get("distract_count", summary.get("distract_count"))),
        "alert_count": _safe_int(entry.get("alert_count")),
        "keywords": [str(value) for value in (entry.get("keywords") or summary.get("keywords") or [])],
        "ai_advice": str(entry.get("ai_advice", "")),
        "summary": {
            "focus_ratio": round(
                _safe_float(summary.get("focus_ratio", entry.get("focus_ratio"))),
                1,
            ),
            "avg_focus_score": (
                round(summary_focus_score, 1)
                if summary_focus_score is not None
                else None
            ),
            "distract_count": _safe_int(
                summary.get("distract_count", entry.get("distract_count"))
            ),
            "total_images": _safe_int(summary.get("total_images", entry.get("captured_frames"))),
            "scored_images": _safe_int(summary.get("scored_images", entry.get("valid_frames"))),
            "valid_coverage_ratio": round(effective_coverage, 3),
            "quality_status": (
                "reliable"
                if score_reliable
                else "low_confidence"
            ),
            "score_version": score_version,
            "score_reliable": score_reliable,
            "decisive_evidence_ratio": round(decisive_evidence_ratio, 3),
            "avg_goal_relevance_score": (
                round(avg_goal_relevance_score, 1)
                if avg_goal_relevance_score is not None
                else None
            ),
            "avg_task_evidence_score": (
                round(avg_task_evidence_score, 1)
                if avg_task_evidence_score is not None
                else None
            ),
            "avg_context_fit_score": (
                round(avg_context_fit_score, 1)
                if avg_context_fit_score is not None
                else None
            ),
            "avg_distraction_risk_score": (
                round(avg_distraction_risk_score, 1)
                if avg_distraction_risk_score is not None
                else None
            ),
        },
        "next_recommend": {
            "base_recommend": _safe_int(next_recommend.get("base_recommend")),
            "challenge_recommend": _safe_int(next_recommend.get("challenge_recommend")),
            "easy_recommend": _safe_int(next_recommend.get("easy_recommend")),
            "rest_recommend": _safe_int(next_recommend.get("rest_recommend")),
        },
        "current_summary": {
            "plan_duration": _safe_int(current_summary.get("plan_duration")),
            "actual_duration": round(_safe_float(current_summary.get("actual_duration")), 2),
            "max_valid_focus_minutes": round(_safe_float(current_summary.get("max_valid_focus_minutes")), 2),
            "completion_rate": round(_safe_float(current_summary.get("completion_rate")), 1),
            "completion_score": (
                round(current_completion_score, 1)
                if current_completion_score is not None
                else None
            ),
            "coverage_ratio": round(_safe_float(current_summary.get("coverage_ratio")), 3),
            "score_version": str(
                current_summary.get("score_version") or score_version
            ),
            "score_reliable": bool(
                current_summary.get("score_reliable", score_reliable)
            ),
            "decisive_evidence_ratio": round(
                _safe_float(
                    current_summary.get(
                        "decisive_evidence_ratio",
                        decisive_evidence_ratio,
                    )
                ),
                3,
            ),
        },
    }


def load_recent_history_snapshot(limit: int = RECENT_HISTORY_LIMIT, username: str | None = None) -> list[dict]:
    try:
        from app.services.history_service import load_recent
        return [serialize_history_entry(entry) for entry in load_recent(limit, username or "")]
    except Exception as exc:
        logger.warning("failed to load recent history: %s", exc)
        return []


def load_all_history_snapshot(username: str | None = None) -> list[dict]:
    try:
        from app.services.history_service import load_all
        return [serialize_history_entry(entry) for entry in load_all(username or "")]
    except Exception as exc:
        logger.warning("failed to load all history: %s", exc)
        return []


def build_history_statistics(entries: list[dict]) -> dict:
    stats = {
        "total_duration": 0,
        "avg_focus_score": 0.0,
        "total_sessions": 0,
        "avg_completion_rate": 0.0,
        "reliable_sessions": 0,
        "low_confidence_sessions": 0,
    }
    if not entries:
        return stats

    total_sessions = len(entries)
    total_duration = sum(entry.get("actual_duration", 0) for entry in entries)
    reliable_entries = [
        entry
        for entry in entries
        if _history_score_is_reliable(entry)
    ]
    total_focus_score = sum(
        _optional_float(entry.get("completion_score")) or 0.0
        for entry in reliable_entries
    )
    total_completion_rate = sum(
        entry.get("current_summary", {}).get("completion_rate", 0) for entry in entries
    )

    stats["total_duration"] = total_duration
    stats["avg_focus_score"] = (
        round(total_focus_score / len(reliable_entries), 1)
        if reliable_entries
        else 0.0
    )
    stats["total_sessions"] = total_sessions
    stats["avg_completion_rate"] = round(total_completion_rate / total_sessions, 1) if total_sessions else 0.0
    stats["reliable_sessions"] = len(reliable_entries)
    stats["low_confidence_sessions"] = total_sessions - len(reliable_entries)
    return stats


def _frame_state(item: dict) -> str:
    explicit = str(item.get("state") or "").lower()
    if explicit in {"focused", "distracted", "uncertain", "unscorable"}:
        return explicit
    if not item.get("image_valid", True) or item.get("review_required"):
        return "unscorable"
    status = str(item.get("status") or "").lower()
    category = str(item.get("category_type") or "").lower()
    if status in {"待复核", "无法分析", "unscorable"}:
        return "unscorable"
    # The model category takes precedence over legacy numeric status labels.
    # In particular, a neutral frame with score 35 must remain uncertain.
    if category in {"neutral", "uncertain"}:
        return "uncertain"
    if category in {"distract", "distracted"}:
        return "distracted"
    if category in {"focus", "focused"}:
        return "focused"
    if status in {"分心", "distracted"}:
        return "distracted"
    if status in {"专注", "focused"}:
        return "focused"
    return "uncertain"


def _build_focus_sequence(items: list[dict], actual_duration_minutes: int | None = None) -> list[dict]:
    """Build timestamped observations; never spread frames into invented minutes."""

    _ = actual_duration_minutes  # retained for compatibility with old callers
    sequence: list[dict] = []
    for item in items or []:
        captured_at = item.get("captured_at")
        if captured_at is None:
            captured_at = item.get("timestamp")
        if captured_at is None:
            continue
        processed_at = item.get("processed_at")
        state = _frame_state(item)
        score_breakdown = item.get("score_breakdown")
        if not isinstance(score_breakdown, dict):
            score_breakdown = {}
        focus_score = _optional_float(item.get("focus_score"))
        raw_focus_score = _optional_float(
            item.get("raw_focus_score", item.get("focus_score"))
        )
        goal_relevance_score = _optional_float(
            item.get("goal_relevance_score", score_breakdown.get("goal_relevance_score"))
        )
        task_evidence_score = _optional_float(
            item.get("task_evidence_score", score_breakdown.get("task_evidence_score"))
        )
        context_fit_score = _optional_float(
            item.get("context_fit_score", score_breakdown.get("context_fit_score"))
        )
        distraction_score = _optional_float(item.get("distraction_score"))
        if distraction_score is not None and distraction_score > 1:
            distraction_score /= 100.0
        raw_distraction_score = _optional_float(
            item.get("raw_distraction_score", item.get("distraction_score"))
        )
        if raw_distraction_score is not None and raw_distraction_score > 1:
            raw_distraction_score /= 100.0
        if state == "unscorable":
            focus_score = None
            goal_relevance_score = None
            task_evidence_score = None
            context_fit_score = None
            distraction_score = None
            raw_distraction_score = None
        source = str(item.get("source") or "").lower()
        scoring_source = str(item.get("scoring_source") or "").lower()
        resolved_source = (
            "reuse"
            if item.get("cache_hit") or "reuse" in {source, scoring_source}
            else (source or scoring_source or "unknown")
        )
        sequence.append(
            {
                "captured_at": _safe_float(captured_at),
                "processed_at": _safe_float(processed_at) if processed_at is not None else None,
                "focus_score": round(focus_score, 1) if focus_score is not None else None,
                "state": state,
                "raw_state": str(item.get("raw_state") or state),
                "raw_confidence": round(
                    _safe_float(
                        item.get(
                            "raw_confidence",
                            item.get("confidence", item.get("score_confidence", 0.0)),
                        )
                    ),
                    3,
                ),
                "raw_focus_score": (
                    round(raw_focus_score, 1)
                    if raw_focus_score is not None
                    else None
                ),
                "raw_distraction_score": (
                    round(raw_distraction_score, 3)
                    if raw_distraction_score is not None
                    else None
                ),
                "confidence": round(
                    _safe_float(item.get("confidence", item.get("score_confidence", 0.0))),
                    3,
                ),
                "source": resolved_source,
                "score_version": (
                    CURRENT_SCORE_VERSION
                    if str(item.get("score_version") or "").lower() == CURRENT_SCORE_VERSION
                    else LEGACY_SCORE_VERSION
                ),
                "goal_relevance_score": (
                    round(goal_relevance_score, 1) if goal_relevance_score is not None else None
                ),
                "task_evidence_score": (
                    round(task_evidence_score, 1) if task_evidence_score is not None else None
                ),
                "context_fit_score": (
                    round(context_fit_score, 1) if context_fit_score is not None else None
                ),
                "distraction_score": (
                    round(max(0.0, min(1.0, distraction_score)), 3)
                    if distraction_score is not None
                    else None
                ),
            }
        )
    sequence.sort(key=lambda observation: observation["captured_at"])
    return sequence


def _timeline_metrics(
    focus_sequence: list[dict],
    end_time: float,
    start_time: float | None = None,
) -> dict:
    longest_focus_seconds = 0.0
    current_focus_seconds = 0.0
    state_seconds = {
        "focused": 0.0,
        "distracted": 0.0,
        "uncertain": 0.0,
        "unscorable": 0.0,
    }
    observed_seconds = 0.0
    weighted_focus_score = 0.0
    focus_score_seconds = 0.0
    component_totals = {
        "goal_relevance_score": 0.0,
        "task_evidence_score": 0.0,
        "context_fit_score": 0.0,
        "distraction_score": 0.0,
    }
    component_seconds = {key: 0.0 for key in component_totals}
    timeline_start = (
        max(0.0, _safe_float(start_time))
        if start_time is not None
        else (_safe_float(focus_sequence[0].get("captured_at")) if focus_sequence else end_time)
    )
    timeline_end = max(timeline_start, _safe_float(end_time))
    cursor = timeline_start
    for index, observation in enumerate(focus_sequence):
        captured_at = _safe_float(observation.get("captured_at"))
        captured_at = min(max(captured_at, timeline_start), timeline_end)
        if captured_at > cursor:
            state_seconds["unscorable"] += captured_at - cursor
            current_focus_seconds = 0.0
        next_at = (
            _safe_float(focus_sequence[index + 1].get("captured_at"))
            if index + 1 < len(focus_sequence)
            else timeline_end
        )
        # A state is held for at most two normal capture periods. Longer gaps
        # are missing observations, not focus or distraction time.
        interval = min(max(0.0, next_at - captured_at), 30.0)
        state = observation.get("state")
        if state in state_seconds:
            state_seconds[state] += interval
        if state != "unscorable":
            observed_seconds += interval
            focus_score = _optional_float(observation.get("focus_score"))
            if focus_score is not None and interval > 0:
                weighted_focus_score += focus_score * interval
                focus_score_seconds += interval
            for field in component_totals:
                component = _optional_float(observation.get(field))
                if component is not None and interval > 0:
                    component_totals[field] += component * interval
                    component_seconds[field] += interval
        if state == "focused":
            current_focus_seconds += interval
            longest_focus_seconds = max(longest_focus_seconds, current_focus_seconds)
        else:
            current_focus_seconds = 0.0
        cursor = max(cursor, captured_at + interval)
    if cursor < timeline_end:
        state_seconds["unscorable"] += timeline_end - cursor
    decisive_seconds = state_seconds["focused"] + state_seconds["distracted"]
    avg_focus_score = (
        round(weighted_focus_score / focus_score_seconds, 1)
        if focus_score_seconds > 0
        else None
    )

    def component_average(field: str, *, scale: float = 1.0) -> float | None:
        seconds = component_seconds[field]
        if seconds <= 0:
            return None
        return round(component_totals[field] / seconds * scale, 1)

    return {
        "max_valid_focus_minutes": round(longest_focus_seconds / 60.0, 2),
        "focus_duration_seconds": round(state_seconds["focused"], 1),
        "distract_duration_seconds": round(state_seconds["distracted"], 1),
        "uncertain_duration_seconds": round(state_seconds["uncertain"], 1),
        "unscorable_duration_seconds": round(state_seconds["unscorable"], 1),
        "observed_seconds": round(observed_seconds, 1),
        "decisive_duration_seconds": round(decisive_seconds, 1),
        "decisive_evidence_ratio": (
            round(decisive_seconds / observed_seconds, 3) if observed_seconds else 0.0
        ),
        "avg_focus_score": avg_focus_score,
        "avg_goal_relevance_score": component_average("goal_relevance_score"),
        "avg_task_evidence_score": component_average("task_evidence_score"),
        "avg_context_fit_score": component_average("context_fit_score"),
        "avg_distraction_risk_score": component_average("distraction_score", scale=100.0),
    }


def _longest_valid_focus_window(focus_sequence: list[dict], end_time: float | None = None) -> float:
    if not focus_sequence:
        return 0.0
    resolved_end = end_time if end_time is not None else _safe_float(focus_sequence[-1].get("captured_at"))
    return _timeline_metrics(focus_sequence, resolved_end)["max_valid_focus_minutes"]


def build_history_entry(payload: dict) -> dict:
    session_data = payload.get("session") or {}
    summary = payload.get("summary") or {}
    items = payload.get("items") or []
    goal = normalize_goal_input(payload.get("goal") or summary.get("goal") or "")
    try:
        recommender = current_app.extensions["duration_recommender"]
        goal_type = recommender.classify_goal(goal or "")
    except Exception:
        goal_type = "认知学习类"

    created_at = _safe_float(session_data.get("created_at"))
    completed_at = session_data.get("completed_at")
    if completed_at is None:
        completed_at = session_data.get("updated_at")
    end_time = _safe_float(completed_at)
    elapsed_seconds = max(
        0.0,
        _safe_float(session_data.get("elapsed_seconds")),
        max(0.0, end_time - created_at),
    )
    planned_seconds = max(60.0, _safe_float(session_data.get("duration_seconds"), 60.0))
    plan_duration = max(1, math.ceil(planned_seconds / 60))
    actual_duration_seconds = min(elapsed_seconds, planned_seconds)
    actual_duration = round(actual_duration_seconds / 60.0, 2)
    focus_sequence = _build_focus_sequence(items, actual_duration)
    timeline_metrics = _timeline_metrics(focus_sequence, end_time, start_time=created_at)

    submitted_frames = max(
        len(items),
        _safe_int(summary.get("total_images")),
        _safe_int(session_data.get("captured_frames")),
    )
    valid_frames = max(
        sum(1 for item in items if _frame_state(item) != "unscorable"),
        _safe_int(summary.get("scored_images")),
    )
    valid_frames = min(valid_frames, submitted_frames)
    capture_interval_seconds = max(
        1.0,
        _safe_float(
            session_data.get("capture_interval_seconds"),
            DEFAULT_CAPTURE_INTERVAL_SECONDS,
        ),
    )
    expected_observations = expected_observation_count(
        elapsed_seconds,
        capture_interval_seconds,
        planned_seconds=_safe_float(session_data.get("duration_seconds")),
    )
    capture_coverage_ratio = (
        min(1.0, submitted_frames / expected_observations)
        if expected_observations
        else 0.0
    )
    model_success_ratio = valid_frames / submitted_frames if submitted_frames else 0.0
    # 同时受“是否按节奏采到画面”和“模型是否成功评分”约束。
    # 这样即便出现额外提交帧，也不会因为 valid/expected 被截到 100%
    # 而掩盖其中的超时或解析失败。
    coverage_ratio = capture_coverage_ratio * model_success_ratio

    frame_score_versions = {
        str(item.get("score_version") or LEGACY_SCORE_VERSION).lower()
        for item in focus_sequence
    }
    score_version = (
        CURRENT_SCORE_VERSION
        if frame_score_versions == {CURRENT_SCORE_VERSION}
        or (
            not frame_score_versions
            and str(summary.get("score_version") or "").lower() == CURRENT_SCORE_VERSION
        )
        else LEGACY_SCORE_VERSION
    )
    avg_focus_score = _optional_float(timeline_metrics.get("avg_focus_score"))
    decisive_frames = sum(
        1 for item in focus_sequence if item.get("state") in {"focused", "distracted"}
    )
    fresh_decisive_frames = sum(
        1
        for item in focus_sequence
        if item.get("state") in {"focused", "distracted"}
        and str(item.get("source") or "").lower() != "reuse"
    )
    decisive_evidence_ratio = max(
        0.0,
        min(1.0, _safe_float(timeline_metrics.get("decisive_evidence_ratio"))),
    )
    score_reliable = bool(
        score_version == CURRENT_SCORE_VERSION
        and coverage_ratio >= RELIABLE_COVERAGE_THRESHOLD
        and avg_focus_score is not None
        and fresh_decisive_frames >= 3
        and decisive_evidence_ratio >= MIN_DECISIVE_EVIDENCE_RATIO
    )
    recommendation_eligible = score_reliable
    earned_points = (
        calculate_session_points(
            actual_duration,
            avg_focus_score if avg_focus_score is not None else 0.0,
            coverage_ratio,
            score_version=score_version,
            score_reliable=score_reliable,
        )
        if score_reliable
        else 0
    )
    total_timeline_seconds = sum(
        _safe_float(timeline_metrics.get(field))
        for field in (
            "focus_duration_seconds",
            "distract_duration_seconds",
            "uncertain_duration_seconds",
            "unscorable_duration_seconds",
        )
    )
    focus_ratio = (
        _safe_float(timeline_metrics.get("focus_duration_seconds")) / total_timeline_seconds * 100
        if total_timeline_seconds > 0
        else 0.0
    )
    saved_summary = dict(summary)
    saved_summary.update(
        {
            "avg_focus_score": round(avg_focus_score, 1) if avg_focus_score is not None else None,
            "score_version": score_version,
            "score_reliable": score_reliable,
            "decisive_evidence_ratio": round(decisive_evidence_ratio, 3),
            "avg_goal_relevance_score": timeline_metrics.get("avg_goal_relevance_score"),
            "avg_task_evidence_score": timeline_metrics.get("avg_task_evidence_score"),
            "avg_context_fit_score": timeline_metrics.get("avg_context_fit_score"),
            "avg_distraction_risk_score": timeline_metrics.get("avg_distraction_risk_score"),
        }
    )

    return {
        "session_id": str(session_data.get("session_id", "")),
        "goal": goal,
        "goal_type": goal_type,
        "plan_duration": plan_duration,
        "actual_duration": actual_duration,
        "actual_duration_seconds": round(actual_duration_seconds, 1),
        "capture_interval_seconds": round(capture_interval_seconds, 3),
        "focus_sequence": focus_sequence,
        "focus_timeline": focus_sequence,
        "completion_score": round(avg_focus_score, 1) if avg_focus_score is not None else None,
        "score_version": score_version,
        "score_reliable": score_reliable,
        "avg_goal_relevance_score": timeline_metrics.get("avg_goal_relevance_score"),
        "avg_task_evidence_score": timeline_metrics.get("avg_task_evidence_score"),
        "avg_context_fit_score": timeline_metrics.get("avg_context_fit_score"),
        "avg_distraction_risk_score": timeline_metrics.get("avg_distraction_risk_score"),
        "focus_ratio": round(focus_ratio, 1),
        "coverage_ratio": round(coverage_ratio, 3),
        "valid_coverage": round(coverage_ratio, 3),
        "capture_coverage_ratio": round(capture_coverage_ratio, 3),
        "model_success_ratio": round(model_success_ratio, 3),
        "expected_observations": expected_observations,
        "coverage_method": "valid_observations_over_expected_v2",
        "coverage_version": 2,
        "valid_frames": valid_frames,
        "captured_frames": submitted_frames,
        "decisive_frames": decisive_frames,
        "fresh_decisive_frames": fresh_decisive_frames,
        "decisive_evidence_ratio": round(decisive_evidence_ratio, 3),
        "recommendation_eligible": recommendation_eligible,
        "started_at": created_at,
        "end_time": end_time,
        "max_valid_focus_minutes": timeline_metrics["max_valid_focus_minutes"],
        "focus_duration_seconds": timeline_metrics["focus_duration_seconds"],
        "distract_duration_seconds": timeline_metrics["distract_duration_seconds"],
        "uncertain_duration_seconds": timeline_metrics["uncertain_duration_seconds"],
        "unscorable_duration_seconds": timeline_metrics["unscorable_duration_seconds"],
        "alert_count": _safe_int(
            summary.get("alert_count", session_data.get("alert_count", payload.get("alert_count", 0)))
        ),
        "earned_points": earned_points,
        "monitoring_mode": str(session_data.get("monitoring_mode") or "medium"),
        "summary": saved_summary,
        "distract_count": _safe_int(summary.get("distract_count")),
        "focus_count": _safe_int(summary.get("focus_count")),
        "drift_count": _safe_int(summary.get("drift_count")),
        "total_images": _safe_int(summary.get("total_images")),
        "keywords": list(summary.get("keywords") or []),
        "ai_advice": str(payload.get("ai_advice") or ""),
    }


def runtime_snapshot(selected_goal: str | None = None, include_adaptive: bool = True, username=None) -> dict:
    analyzer = current_app.extensions["analyzer"]
    ready, engine = analyzer.vision_ready_message()
    scoring = analyzer.scoring_status()
    evaluation_collector = current_app.extensions.get("evaluation_collector")

    from app.services.user_service import get_user
    user_data = get_user(username)

    snapshot_data = {
        "ocr_ready": ready,
        "ocr_engine": engine,
        "llm_ready": bool(scoring["configured"]),
        "llm_provider": str(scoring["provider"]),
        "llm_model": str(scoring["model"]),
        "scoring_policy": dict(scoring.get("scoring_policy") or {}),
        "scoring_policy_source": str(scoring.get("scoring_policy_source") or "default"),
        "scoring_policy_error": scoring.get("scoring_policy_error"),
        "workers": current_app.extensions["config"].max_workers,
        "session_window_size": current_app.extensions["config"].session_window_size,
        "session_capture_mode": "continuous",
        "evaluation_capture_enabled": bool(
            evaluation_collector is not None and evaluation_collector.enabled
        ),
        "session_default_duration_minutes": current_app.extensions["config"].session_default_duration_minutes,
        "session_min_duration_minutes": current_app.extensions["config"].session_min_duration_minutes,
        "session_max_duration_minutes": current_app.extensions["config"].session_max_duration_minutes,
        "goal_placeholder": GOAL_PLACEHOLDER,
        "goal_examples": GOAL_EXAMPLES,
        "default_goal": DEFAULT_GOAL_TEXT,
        "user_points": user_data["total_points"],
        "api_status": {
            "siliconflow": {
                "configured": bool(scoring["configured"]),
                "model": str(scoring["model"]),
                "base_url": str(scoring.get("base_url", "https://api.siliconflow.cn/v1")),
            }
        },
    }
    if include_adaptive:
        normalized_selected_goal = normalize_goal_input(selected_goal)
        snapshot_data["duration_recommendation"] = (
            build_duration_recommendation(normalized_selected_goal, username)
            if normalized_selected_goal
            else None
        )
        snapshot_data["recent_history"] = load_recent_history_snapshot(username=username)
    return snapshot_data


def extract_goal_from_request() -> str:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return normalize_goal_input(payload.get("goal", ""))
    return normalize_goal_input(request.form.get("goal", ""))


def extract_int_from_request(field: str, default: int | None = None) -> int | None:
    raw_value = None
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        raw_value = payload.get(field)
    else:
        raw_value = request.form.get(field)
    if raw_value in (None, ""):
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(field) from None


def normalize_selected_goal(goal: str | None) -> str:
    return normalize_goal_input(goal)


def clear_invalid_session() -> bool:
    running_session_id = session.get("running_session_id")
    if running_session_id:
        session_mgr = current_app.extensions["session_manager"]
        try:
            session_mgr.snapshot(running_session_id)
            return True
        except KeyError:
            session.pop("running_session_id", None)
            return False
    return False
