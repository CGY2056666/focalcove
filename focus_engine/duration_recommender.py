from __future__ import annotations

import math
from typing import Any

from .goal_profiles import normalize_goal_input


RELIABLE_COVERAGE = 0.70
MIN_RELIABLE_SESSIONS = 3
HISTORY_LIMIT = 10
RECOMMENDATION_STEP_MINUTES = 5
LEGACY_CAPTURE_INTERVAL_SECONDS = 15.0
CURRENT_SCORE_VERSION = "multidim-v1"
MIN_FRESH_DECISIVE_FRAMES = 3
MIN_DECISIVE_EVIDENCE_RATIO = 0.50


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _coverage(session: dict) -> float:
    value = session.get("coverage_ratio", session.get("valid_coverage", 0.0))
    coverage = _as_float(value)
    if coverage > 1.0:
        coverage /= 100.0
    coverage = max(0.0, min(1.0, coverage))

    # v1 history used successful/submitted frames as ``coverage_ratio`` and
    # therefore treated a single successful frame in a long session as 100%.
    # Approximate its missing capture coverage from the saved duration.
    has_v2_capture_data = (
        _as_int(session.get("coverage_version")) >= 2
        or "expected_observations" in session
        or "capture_coverage_ratio" in session
    )
    if has_v2_capture_data:
        return coverage

    actual_minutes = max(0.0, _as_float(session.get("actual_duration")))
    if actual_minutes <= 0 or "captured_frames" not in session:
        return coverage

    submitted = max(0, _as_int(session.get("captured_frames")))
    expected = max(1, math.ceil(actual_minutes * 60.0 / LEGACY_CAPTURE_INTERVAL_SECONDS))
    capture_coverage = min(1.0, submitted / expected)
    if submitted <= 0:
        return 0.0

    valid_frames = session.get("valid_frames")
    if valid_frames is not None:
        model_success = min(1.0, max(0.0, _as_float(valid_frames) / submitted))
    else:
        summary = session.get("summary") if isinstance(session.get("summary"), dict) else {}
        summary_ratio = summary.get("valid_coverage_ratio")
        model_success = _as_float(summary_ratio, coverage) if summary_ratio is not None else coverage
        if model_success > 1.0:
            model_success /= 100.0
        model_success = max(0.0, min(1.0, model_success))
    return round(capture_coverage * model_success, 6)


def _session_time(session: dict) -> float:
    return _as_float(
        session.get("end_time")
        or session.get("completed_at")
        or session.get("updated_at")
        or 0.0
    )


def _goal_key(goal: str) -> str:
    return normalize_goal_input(goal).casefold()


def _has_enough_session_evidence(session: dict) -> bool:
    if str(session.get("score_version") or "").lower() != CURRENT_SCORE_VERSION:
        return False
    explicit_reliable = session.get("score_reliable")
    if explicit_reliable is False:
        return False
    explicit = session.get("recommendation_eligible")
    if explicit is False:
        return False
    return bool(
        _coverage(session) >= RELIABLE_COVERAGE
        and _as_int(session.get("fresh_decisive_frames")) >= MIN_FRESH_DECISIVE_FRAMES
        and _as_float(session.get("decisive_evidence_ratio")) >= MIN_DECISIVE_EVIDENCE_RATIO
        and _optional_float(session.get("completion_score")) is not None
    )


def _is_focused_observation(observation: dict) -> bool:
    state = str(observation.get("state") or observation.get("status") or "").lower()
    return state in {"focused", "focus", "专注"}


def _longest_timestamped_focus_minutes(session: dict) -> float:
    """Calculate an observed focus run without inventing minute buckets."""

    raw_sequence = session.get("focus_sequence") or session.get("focus_timeline") or []
    observations = [item for item in raw_sequence if isinstance(item, dict)]
    if not observations:
        return max(0.0, _as_float(session.get("max_valid_focus_minutes")))

    normalized: list[tuple[float, dict]] = []
    for item in observations:
        captured_at = _as_float(item.get("captured_at") or item.get("timestamp"), -1.0)
        if captured_at >= 0:
            normalized.append((captured_at, item))
    normalized.sort(key=lambda pair: pair[0])
    if not normalized:
        return 0.0

    end_time = _session_time(session)
    current_seconds = 0.0
    longest_seconds = 0.0
    for index, (captured_at, item) in enumerate(normalized):
        next_at = normalized[index + 1][0] if index + 1 < len(normalized) else end_time
        interval = min(max(0.0, next_at - captured_at), 30.0)
        if _is_focused_observation(item):
            current_seconds += interval
            longest_seconds = max(longest_seconds, current_seconds)
        else:
            current_seconds = 0.0
    return round(longest_seconds / 60.0, 2)


def _weighted_median(values: list[float]) -> float:
    """Recent-first weighted median; newer sessions receive larger weights."""

    if not values:
        return 0.0
    count = len(values)
    weighted = sorted(
        ((max(0.0, value), count - index) for index, value in enumerate(values)),
        key=lambda pair: pair[0],
    )
    half_weight = sum(weight for _, weight in weighted) / 2.0
    cumulative = 0.0
    for value, weight in weighted:
        cumulative += weight
        if cumulative >= half_weight:
            return value
    return weighted[-1][0]


class FocusDurationRecommender:
    """Small, stateless duration recommender for the single-machine prototype."""

    def __init__(self, config):
        self.config = config

    def _heuristic_goal_type(self, goal: str) -> str:
        normalized_goal = normalize_goal_input(goal).lower()
        cognitive_keywords = (
            "学习", "阅读", "复习", "背", "刷题", "考试", "高数", "python",
            "编程", "代码", "debug", "调试", "英语", "课程", "考研", "考证",
            "论文", "算法",
        )
        creative_keywords = (
            "写作", "创作", "设计", "策划", "小说", "文案", "画图", "视频",
            "剪辑", "ppt", "方案", "海报", "脚本", "构思",
        )
        mechanical_keywords = (
            "整理", "录入", "核对", "归档", "汇总", "搬运", "表格", "统计",
            "报销", "清单", "流程", "处理工单", "上传",
        )
        if any(keyword in normalized_goal for keyword in cognitive_keywords):
            return "认知学习类"
        if any(keyword in normalized_goal for keyword in creative_keywords):
            return "创意创作类"
        if any(keyword in normalized_goal for keyword in mechanical_keywords):
            return "机械执行类"
        return "认知学习类"

    def classify_goal(self, goal: str) -> str:
        return self._heuristic_goal_type(goal)

    def _clamp(self, minutes: float) -> int:
        # Recommendations are expressed in five-minute steps. A manually
        # selected one-minute prototype session must not collapse the next
        # recommendation to one minute.
        minimum = max(RECOMMENDATION_STEP_MINUTES, int(self.config.session_min_duration_minutes))
        maximum = int(self.config.session_max_duration_minutes)
        rounded = int(RECOMMENDATION_STEP_MINUTES * round(minutes / RECOMMENDATION_STEP_MINUTES))
        return max(minimum, min(rounded, maximum))

    def _default_minutes(self) -> int:
        return self._clamp(25)

    @staticmethod
    def _dedupe_history(history: list[dict]) -> list[dict]:
        by_id: dict[str, dict] = {}
        anonymous: list[dict] = []
        for entry in history:
            session_id = str(entry.get("session_id") or "")
            if session_id:
                by_id[session_id] = entry
            else:
                anonymous.append(entry)
        return list(by_id.values()) + anonymous

    def _select_history(self, goal: str, goal_type: str, history: list[dict]) -> tuple[list[dict], str]:
        reliable = [
            entry
            for entry in self._dedupe_history(history)
            if _coverage(entry) >= RELIABLE_COVERAGE
            and _has_enough_session_evidence(entry)
        ]
        reliable.sort(key=_session_time, reverse=True)
        normalized_goal = _goal_key(goal)
        same_goal = [
            entry for entry in reliable
            if _goal_key(str(entry.get("goal") or "")) == normalized_goal
        ][:HISTORY_LIMIT]
        if len(same_goal) >= MIN_RELIABLE_SESSIONS:
            return same_goal, "same_goal_history"

        same_type = [entry for entry in reliable if entry.get("goal_type") == goal_type][:HISTORY_LIMIT]
        if len(same_type) >= MIN_RELIABLE_SESSIONS:
            return same_type, "goal_type_history"
        return same_goal or same_type, "default"

    def _capacity(self, selected: list[dict]) -> float:
        return _weighted_median([_longest_timestamped_focus_minutes(entry) for entry in selected])

    def _legacy_choices(self, minutes: int) -> dict:
        maximum = int(self.config.session_max_duration_minutes)
        minimum = int(self.config.session_min_duration_minutes)
        return {
            "base_recommend": minutes,
            "challenge_recommend": min(maximum, self._clamp(minutes + 5)),
            "easy_recommend": max(minimum, self._clamp(minutes - 5)),
            "rest_recommend": max(5, int(5 * round(max(minutes / 5, 1) / 5))),
        }

    @staticmethod
    def _confidence(sample_count: int) -> float:
        if sample_count < MIN_RELIABLE_SESSIONS:
            return 0.30
        if sample_count < 6:
            return 0.65
        return 0.85

    @staticmethod
    def _display_reason(source: str, sample_count: int, reason: str) -> str:
        """Return a short user-facing explanation without leaking tuning terms."""

        if source == "default":
            return "先从 25 分钟开始，完成几轮后会更贴近你的节奏。"
        if "增加" in reason:
            return "这轮完成得不错，下次可以保持或增加 5 分钟。"
        if "减少" in reason:
            return "这轮有些吃力，下次可以减少 5 分钟。"
        if source == "current_plan":
            return "这轮数据不够完整，下次继续保持当前时长。"
        if sample_count > 0:
            return f"参考了最近 {sample_count} 次相似目标。"
        return "下次继续保持当前时长。"

    def _result(self, minutes: int, goal_type: str, selected: list[dict], source: str, reason: str) -> dict:
        display_reason = self._display_reason(source, len(selected), reason)
        result = {
            "minutes": minutes,
            "confidence": self._confidence(len(selected)),
            "sample_count": len(selected),
            "source": source,
            "reason": reason,
            "display_reason": display_reason,
            "goal_type": goal_type,
            "history_count": len(selected),
            "explanation": reason,
        }
        result.update(self._legacy_choices(minutes))
        return result

    def recommend(self, goal: str, username=None, history: list[dict] | None = None) -> dict:
        # ``username`` remains accepted for API compatibility, but this shared
        # instance never retains one user's history.
        if history is None:
            from .history_storage import load_all_history

            history = load_all_history(username)
        normalized_goal = normalize_goal_input(goal)
        goal_type = self.classify_goal(normalized_goal)
        selected, source = self._select_history(normalized_goal, goal_type, list(history or []))
        if len(selected) < MIN_RELIABLE_SESSIONS:
            return self._result(
                self._default_minutes(),
                goal_type,
                selected,
                "default",
                "可靠历史不足 3 次，先使用 25 分钟建立稳定基线。",
            )

        minutes = self._clamp(self._capacity(selected))
        label = "同一目标" if source == "same_goal_history" else "同类型目标"
        return self._result(
            minutes,
            goal_type,
            selected,
            source,
            f"根据最近 {len(selected)} 次可靠的{label}记录，按连续专注时长给出建议。",
        )

    def recommend_next(
        self,
        current_session: dict,
        username=None,
        history: list[dict] | None = None,
    ) -> dict:
        if history is None:
            from .history_storage import load_all_history

            history = load_all_history(username)

        goal = normalize_goal_input(str(current_session.get("goal") or ""))
        goal_type = str(current_session.get("goal_type") or self.classify_goal(goal))
        plan = max(1, _as_int(current_session.get("plan_duration"), self._default_minutes()))
        actual = max(0.0, _as_float(current_session.get("actual_duration")))
        raw_score = _optional_float(current_session.get("completion_score"))
        score = max(0.0, min(100.0, raw_score)) if raw_score is not None else None
        completion_rate = actual / plan if plan else 0.0
        current_coverage = _coverage(current_session)
        current_summary = {
            "plan_duration": plan,
            "actual_duration": round(actual, 1),
            "max_valid_focus_minutes": _longest_timestamped_focus_minutes(current_session),
            "completion_rate": round(completion_rate * 100, 1),
            "completion_score": round(score, 1) if score is not None else None,
            "coverage_ratio": round(current_coverage, 3),
            "score_version": str(current_session.get("score_version") or "legacy-v1"),
            "score_reliable": _has_enough_session_evidence(current_session),
            "decisive_evidence_ratio": round(
                max(0.0, min(1.0, _as_float(current_session.get("decisive_evidence_ratio")))),
                3,
            ),
        }

        selected, selected_source = self._select_history(
            goal,
            goal_type,
            list(history or []) + [current_session],
        )
        current_score_version = str(current_session.get("score_version") or "").lower()
        if len(selected) < MIN_RELIABLE_SESSIONS:
            result = self._result(
                self._default_minutes(),
                goal_type,
                selected,
                "default",
                "可靠新版历史不足 3 次，下一次仍建议 25 分钟。",
            )
        elif current_score_version != CURRENT_SCORE_VERSION:
            result = self._result(
                self._clamp(plan),
                goal_type,
                [],
                "current_plan",
                "旧版评分记录只供回看，保持当前计划，不更新新版个人基线。",
            )
        elif current_coverage < RELIABLE_COVERAGE:
            result = self._result(
                self._clamp(plan),
                goal_type,
                [],
                "current_plan",
                "本次有效评分覆盖率不足 70%，保持当前计划，不更新个人基线。",
            )
        elif score is None:
            result = self._result(
                self._clamp(plan),
                goal_type,
                [],
                "current_plan",
                "本次没有可用的总体画面相关度，保持当前计划，不更新个人基线。",
            )
        elif not _has_enough_session_evidence(current_session):
            result = self._result(
                self._clamp(plan),
                goal_type,
                [],
                "current_plan",
                "本次明确证据占比不足 50% 或非复用明确画面少于 3 张，保持当前计划。",
            )
        else:
            capacity = self._clamp(self._capacity(selected))
            if completion_rate >= 0.90 and score >= 75:
                minutes = self._clamp(min(max(plan, capacity), plan + RECOMMENDATION_STEP_MINUTES))
                minutes = max(plan, minutes)
                reason = "本次完成率和画面任务相关度都很稳定，建议保持或最多增加 5 分钟。"
            elif completion_rate < 0.70 or score < 50:
                desired = min(capacity, plan - RECOMMENDATION_STEP_MINUTES)
                minutes = self._clamp(max(plan - RECOMMENDATION_STEP_MINUTES, desired))
                minutes = min(plan, minutes)
                reason = "本次完成率或画面任务相关度偏低，建议最多减少 5 分钟，先恢复稳定节奏。"
            else:
                minutes = self._clamp(plan)
                reason = "本次表现处于稳定区间，下一次保持当前计划时长。"
            result = self._result(minutes, goal_type, selected, selected_source, reason)

        result["current_summary"] = current_summary
        result["next_recommend"] = self._legacy_choices(result["minutes"])
        result["feedback_text"] = result["display_reason"]
        return result
