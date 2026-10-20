"""页面路由：/, /focus, /report, /analysis, /den, /shop, /about, /rules, /profile, /success"""
from __future__ import annotations

import ipaddress
import math
import mimetypes
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.helpers import (
    clear_invalid_session,
    load_all_history_snapshot,
    load_recent_history_snapshot,
    normalize_selected_goal,
    runtime_snapshot,
)
from app.services.user_service import get_user
from app.services.shop_catalog import list_den_items, list_shop_items
from focus_engine.scoring import expected_observation_count

pages_bp = Blueprint("pages", __name__, url_prefix="")

EVALUATION_LABELS = {"focused", "uncertain", "distracted", "unscorable"}
EVALUATION_SCORING_RUBRIC_VERSION = "multidim-v1"
_IMAGE_METHOD_NAMES = ("get_image", "open_image", "read_image", "image_for_sample")


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _coverage_ratio(item: Mapping[str, Any]) -> float:
    value = _safe_number(item.get("coverage_ratio"))
    if 1 < value <= 100:
        value /= 100
    return max(0.0, min(1.0, value))


def _duration_label(seconds: float) -> str:
    rounded_seconds = max(0, int(round(_safe_number(seconds))))
    minutes, remainder = divmod(rounded_seconds, 60)
    if minutes and remainder:
        return f"{minutes} 分 {remainder} 秒"
    if minutes:
        return f"{minutes} 分钟"
    return f"{remainder} 秒"


def _history_timestamp(item: Mapping[str, Any]) -> float | None:
    timestamp = _optional_number(item.get("end_time"))
    return max(0.0, timestamp) if timestamp is not None else None


def _build_report_view(report: Mapping[str, Any] | None) -> dict[str, Any]:
    item = report if isinstance(report, Mapping) else {}
    has_report = bool(item)
    plan_minutes = max(0.0, _safe_number(item.get("plan_duration")))
    stored_actual_minutes = max(0.0, _safe_number(item.get("actual_duration")))
    raw_started_at = _optional_number(item.get("started_at"))
    started_at = max(0.0, raw_started_at) if raw_started_at is not None else None
    ended_at = _history_timestamp(item)
    has_precise_timing = bool(
        started_at is not None
        and ended_at is not None
        and ended_at >= started_at
    )
    elapsed_seconds = ended_at - started_at if has_precise_timing else stored_actual_minutes * 60
    actual_minutes = (
        min(elapsed_seconds / 60, plan_minutes)
        if has_precise_timing and plan_minutes
        else stored_actual_minutes
    )
    current_summary = item.get("current_summary")
    if not isinstance(current_summary, Mapping):
        current_summary = {}
    stored_completion = _safe_number(current_summary.get("completion_rate"), -1.0)
    if has_precise_timing and plan_minutes:
        completion_rate = elapsed_seconds / (plan_minutes * 60) * 100
    elif stored_completion > 0:
        completion_rate = stored_completion
    else:
        completion_rate = actual_minutes / plan_minutes * 100 if plan_minutes else 0.0
    completion_rate = max(0.0, min(100.0, completion_rate))
    coverage = _coverage_ratio(item)
    coverage_reliable = coverage >= 0.70
    relevance_score = _optional_number(item.get("completion_score"))
    score_available = relevance_score is not None
    score_version = (
        "multidim-v1"
        if str(item.get("score_version") or "").lower() == "multidim-v1"
        else "legacy-v1"
    )
    legacy_score = score_version != "multidim-v1"
    decisive_evidence_ratio = max(
        0.0,
        min(1.0, _safe_number(item.get("decisive_evidence_ratio"))),
    )
    fresh_decisive_frames = max(0, int(_safe_number(item.get("fresh_decisive_frames"))))
    evidence_sufficient = bool(
        fresh_decisive_frames >= 3 and decisive_evidence_ratio >= 0.50
    )
    reliable = bool(
        not legacy_score
        and item.get("score_reliable") is True
        and coverage_reliable
        and score_available
        and evidence_sufficient
    )
    reference_score_visible = bool(
        not legacy_score and coverage_reliable and score_available
    )
    score_displayable = bool(score_available and (legacy_score or coverage_reliable))
    completed = bool(plan_minutes and completion_rate >= 100)
    focus_ratio = max(0.0, min(100.0, _safe_number(item.get("focus_ratio"))))
    stored_focus_seconds = _optional_number(item.get("focus_duration_seconds"))
    focus_seconds = (
        max(0.0, stored_focus_seconds)
        if stored_focus_seconds is not None
        else actual_minutes * 60 * focus_ratio / 100
    )
    distract_seconds = max(0.0, _safe_number(item.get("distract_duration_seconds")))
    uncertain_seconds = max(0.0, _safe_number(item.get("uncertain_duration_seconds")))
    unscorable_seconds = max(0.0, _safe_number(item.get("unscorable_duration_seconds")))

    if not has_report:
        title = "还没有可展示的专注记录"
        subtitle = "完成一轮专注后，这里会显示本轮记录。"
    elif legacy_score:
        title = "这是一条旧版评分记录"
        subtitle = "保留原始结果供回看，不与新版多维评分趋势或推荐混合计算。"
    elif not coverage_reliable:
        title = "记录已保存，但可用分析数据不足"
        subtitle = "画面分析覆盖不足 70%，相关度和估算时长只作参考。"
    elif not score_available:
        title = "记录已保存，但缺少可用评分"
        subtitle = "本轮采集覆盖充足，但历史记录中没有总体画面相关度。"
    elif not evidence_sufficient:
        title = "记录已保存，但有效证据不足"
        subtitle = "本轮明确判断较少，结果只作参考，不更新时长建议。"
    elif completed:
        title = "这一轮已按计划完成"
        subtitle = "记录已保存。下面的数据来自本轮屏幕画面的模型估计。"
    else:
        title = "这一轮已结束"
        subtitle = "本轮提前结束，记录已保存。下面的数据来自已采集画面的模型估计。"

    captured_frames = max(0, int(_safe_number(item.get("captured_frames"))))
    valid_frames = max(0, int(_safe_number(item.get("valid_frames"))))
    saved_expected = _optional_number(item.get("expected_observations"))
    saved_capture_interval = _optional_number(item.get("capture_interval_seconds"))
    capture_interval_recorded = bool(
        saved_capture_interval is not None and saved_capture_interval > 0
    )
    capture_interval_seconds = (
        float(saved_capture_interval) if capture_interval_recorded else 20.0
    )
    if saved_expected is not None and saved_expected > 0:
        expected_observations = max(0, int(saved_expected))
    else:
        expected_observations = expected_observation_count(
            max(0.0, elapsed_seconds),
            capture_interval_seconds,
            planned_seconds=plan_minutes * 60 if plan_minutes else None,
        )

    return {
        "has_report": has_report,
        "reliable": reliable,
        "score_version": score_version,
        "legacy_score": legacy_score,
        "reference_score_visible": reference_score_visible,
        "score_displayable": score_displayable,
        "coverage_reliable": coverage_reliable,
        "score_available": score_available,
        "evidence_sufficient": evidence_sufficient,
        "completed": completed,
        "title": title,
        "subtitle": subtitle,
        "goal": str(item.get("goal") or "未设置目标"),
        "goal_type": str(item.get("goal_type") or "未分类"),
        "actual_minutes": round(actual_minutes, 1),
        "plan_minutes": round(plan_minutes, 1),
        "actual_plan_value": f"{round(actual_minutes, 1):g} / {round(plan_minutes, 1):g}",
        "completion_rate": round(completion_rate, 1),
        "coverage_percent": round(coverage * 100, 1),
        "decisive_evidence_percent": round(decisive_evidence_ratio * 100, 1),
        "fresh_decisive_frames": fresh_decisive_frames,
        "relevance_score": round(relevance_score, 1) if relevance_score is not None else None,
        "avg_goal_relevance_score": _optional_number(item.get("avg_goal_relevance_score")),
        "avg_task_evidence_score": _optional_number(item.get("avg_task_evidence_score")),
        "avg_context_fit_score": _optional_number(item.get("avg_context_fit_score")),
        "avg_distraction_risk_score": _optional_number(item.get("avg_distraction_risk_score")),
        "focus_duration_label": _duration_label(focus_seconds),
        "distract_duration_label": _duration_label(distract_seconds),
        "uncertain_duration_label": _duration_label(uncertain_seconds),
        "unscorable_duration_label": _duration_label(unscorable_seconds),
        "distract_count": max(0, int(_safe_number(item.get("distract_count")))),
        "alert_count": max(0, int(_safe_number(item.get("alert_count")))),
        "earned_points": max(0, int(_safe_number(item.get("earned_points")))),
        "captured_frames": captured_frames,
        "valid_frames": valid_frames,
        "expected_observations": expected_observations,
        "capture_interval_seconds": capture_interval_seconds,
        "capture_interval_recorded": capture_interval_recorded,
        "end_time": ended_at,
    }


def _local_history_datetime(item: Mapping[str, Any]) -> datetime | None:
    timestamp = _history_timestamp(item)
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp)
    except (OSError, OverflowError, ValueError):
        return None


def _build_analysis_view(
    history_items: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    local_today = today or datetime.now().date()
    first_day = local_today - timedelta(days=13)
    minutes_by_day = {
        first_day + timedelta(days=offset): 0.0
        for offset in range(14)
    }
    goal_minutes: dict[str, float] = {}

    newest_first = sorted(
        history_items,
        key=lambda item: (
            _history_timestamp(item)
            if _history_timestamp(item) is not None
            else float("-inf")
        ),
        reverse=True,
    )
    for item in newest_first:
        actual_minutes = max(0.0, _safe_number(item.get("actual_duration")))
        local_datetime = _local_history_datetime(item)
        if local_datetime is not None and local_datetime.date() in minutes_by_day:
            minutes_by_day[local_datetime.date()] += actual_minutes
        goal_type = str(item.get("goal_type") or "未分类")
        goal_minutes[goal_type] = goal_minutes.get(goal_type, 0.0) + actual_minutes

    daily_rows = [
        {
            "date": day.isoformat(),
            "label": day.strftime("%m-%d"),
            "minutes": round(minutes_by_day[day], 1),
        }
        for day in sorted(minutes_by_day)
    ]
    active_days = [row for row in daily_rows if row["minutes"] > 0]
    if active_days:
        peak_day = max(active_days, key=lambda row: row["minutes"])
        daily_summary = (
            f"最近 14 天共记录 {sum(row['minutes'] for row in daily_rows):g} 分钟，"
            f"其中 {peak_day['label']} 最多，为 {peak_day['minutes']:g} 分钟。"
        )
    else:
        daily_summary = "最近 14 天还没有专注时长记录。"

    reliable_newest = [
        item
        for item in newest_first
        if str(item.get("score_version") or "").lower() == "multidim-v1"
        and item.get("score_reliable") is True
        and _coverage_ratio(item) >= 0.70
        and _optional_number(item.get("completion_score")) is not None
    ][:10]
    relevance_rows: list[dict[str, Any]] = []
    for item in reversed(reliable_newest):
        local_datetime = _local_history_datetime(item)
        relevance_rows.append(
            {
                "label": local_datetime.strftime("%m-%d %H:%M") if local_datetime else "时间未知",
                "score": round(
                    max(0.0, min(100.0, _optional_number(item.get("completion_score")) or 0.0)),
                    1,
                ),
                "goal": str(item.get("goal") or "未命名目标"),
            }
        )
    if len(relevance_rows) == 1:
        relevance_summary = (
            f"目前只有 1 次数据较完整的记录，画面相关度为 {relevance_rows[0]['score']:g} 分，"
            "暂不判断变化趋势。"
        )
    elif relevance_rows:
        scores = [row["score"] for row in relevance_rows]
        relevance_summary = (
            f"最近 {len(scores)} 次数据较完整的记录平均 {sum(scores) / len(scores):.1f} 分，"
            f"范围为 {min(scores):g}–{max(scores):g} 分。"
        )
    else:
        relevance_summary = "还没有满足数据完整性要求的新版记录。"

    goal_rows = [
        {"goal_type": goal_type, "minutes": round(minutes, 1)}
        for goal_type, minutes in sorted(
            goal_minutes.items(),
            key=lambda pair: (-pair[1], pair[0]),
        )
        if minutes > 0
    ]
    if goal_rows:
        top_goal = goal_rows[0]
        goal_summary = (
            f"累计时长最多的是“{top_goal['goal_type']}”，共 {top_goal['minutes']:g} 分钟。"
        )
    else:
        goal_summary = "还没有可按目标类型汇总的时长记录。"

    return {
        "daily": daily_rows,
        "daily_has_data": bool(active_days),
        "daily_summary": daily_summary,
        "relevance": relevance_rows,
        "relevance_summary": relevance_summary,
        "goals": goal_rows,
        "goal_summary": goal_summary,
    }


def _login_redirect():
    return redirect(url_for("auth.login_page"))


def _evaluation_collector():
    """Return the opt-in local collector, hiding all review routes otherwise."""
    try:
        is_loopback = ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        abort(404)

    collector = current_app.extensions.get("evaluation_collector")
    if collector is None:
        abort(404)

    enabled = getattr(collector, "enabled", False)
    if callable(enabled):
        enabled = enabled()
    if not bool(enabled):
        # 停止自动采集后仍允许本机把已有待审队列处理完；空队列继续隐藏入口。
        list_pending = getattr(collector, "list_pending", None)
        if not callable(list_pending):
            abort(404)
        try:
            has_pending = bool(list_pending())
        except (FileNotFoundError, OSError, ValueError):
            has_pending = False
        if not has_pending:
            abort(404)
    return collector


def _sample_field(sample: Any, *names: str, default: Any = None) -> Any:
    containers = [sample]
    if isinstance(sample, Mapping):
        for nested_name in ("metadata", "raw", "postprocessed"):
            nested = sample.get(nested_name)
            if isinstance(nested, Mapping):
                containers.append(nested)

    for container in containers:
        for name in names:
            if isinstance(container, Mapping):
                value = container.get(name)
            else:
                value = getattr(container, name, None)
            if value not in (None, ""):
                return value
    return default


def _review_sample_payload(sample: Any) -> dict[str, Any] | None:
    sample_id = str(_sample_field(sample, "sample_id", "id", default="")).strip()
    if not sample_id or len(sample_id) > 256 or "\x00" in sample_id:
        return None

    return {
        "sample_id": sample_id,
        "goal": str(_sample_field(sample, "goal", "focus_goal", default="未提供目标")),
        "image_url": url_for("pages.evaluation_review_image", sample_id=sample_id),
        "label_url": url_for("pages.evaluation_review_label", sample_id=sample_id),
        "discard_url": url_for("pages.evaluation_review_discard", sample_id=sample_id),
    }


def _pending_review_samples(collector: Any) -> list[dict[str, Any]]:
    try:
        pending = collector.list_pending()
    except (FileNotFoundError, OSError):
        pending = []
    if pending is None:
        return []
    samples: list[dict[str, Any]] = []
    for item in pending:
        payload = _review_sample_payload(item)
        if payload is not None:
            samples.append(payload)
    return samples


def _image_mimetype(data: bytes, explicit: str | None = None) -> str:
    if explicit and explicit.startswith("image/"):
        return explicit
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _collector_image(collector: Any, sample_id: str):
    method = next(
        (getattr(collector, name) for name in _IMAGE_METHOD_NAMES if callable(getattr(collector, name, None))),
        None,
    )
    if method is None:
        abort(404)
    try:
        result = method(sample_id)
    except (KeyError, FileNotFoundError, ValueError):
        abort(404)
    if result is None:
        abort(404)

    mimetype: str | None = None
    payload = result
    if isinstance(result, Mapping):
        mimetype = str(result.get("mimetype") or result.get("content_type") or "") or None
        payload = result.get("data", result.get("content", result.get("path")))
    elif isinstance(result, tuple) and len(result) == 2:
        payload, mimetype = result
        mimetype = str(mimetype or "") or None

    if isinstance(payload, (bytes, bytearray, memoryview)):
        image_bytes = bytes(payload)
        resolved_type = _image_mimetype(image_bytes, mimetype)
        if not resolved_type.startswith("image/"):
            abort(404)
        return send_file(
            BytesIO(image_bytes),
            mimetype=resolved_type,
            download_name="review-image",
            max_age=0,
        )

    if isinstance(payload, (str, Path)):
        image_path = Path(payload)
        if not image_path.is_file():
            abort(404)
        resolved_type = mimetype or mimetypes.guess_type(image_path.name)[0] or ""
        if not resolved_type.startswith("image/"):
            abort(404)
        return send_file(image_path, mimetype=resolved_type, max_age=0)

    if hasattr(payload, "read"):
        if not mimetype or not mimetype.startswith("image/"):
            abort(404)
        return send_file(payload, mimetype=mimetype, max_age=0)
    abort(404)


@pages_bp.get("/")
def home():
    if not session.get("username"):
        return _login_redirect()

    if request.args.get("reset") == "true":
        session.pop("running_session_id", None)
        selected_goal = normalize_selected_goal(request.args.get("selected_goal"))
        return render_template(
            "home.html",
            runtime=runtime_snapshot(selected_goal, username=session.get("username")),
            selected_goal=selected_goal,
            is_running=False,
        )

    running_session_id = session.get("running_session_id")
    if running_session_id:
        try:
            from flask import current_app
            session_mgr = current_app.extensions["session_manager"]
            session_mgr.snapshot(running_session_id)
            return redirect(url_for("pages.focus_page"))
        except KeyError:
            session.pop("running_session_id", None)

    selected_goal = normalize_selected_goal(request.args.get("selected_goal"))
    return render_template(
        "home.html",
        runtime=runtime_snapshot(selected_goal, username=session.get("username")),
        selected_goal=selected_goal,
        is_running=False,
    )


@pages_bp.get("/focus")
def focus_page():
    if not session.get("username"):
        return _login_redirect()

    running_session_id = session.get("running_session_id")
    if not running_session_id:
        return redirect(url_for("pages.home"))

    try:
        from flask import current_app
        session_mgr = current_app.extensions["session_manager"]
        session_mgr.snapshot(running_session_id)
    except KeyError:
        session.pop("running_session_id", None)
        return redirect(url_for("pages.home"))

    username = session.get("username")
    user_data = get_user(username)

    return render_template(
        "focus.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        session_id=running_session_id,
        is_running=True,
        has_permission=user_data.get("monitoring_permission", False),
    )


@pages_bp.get("/report")
def report_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    user_data = get_user(username)
    history_items = load_all_history_snapshot(username)
    latest_report = history_items[0] if history_items else {}
    return render_template(
        "report.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        user_data=user_data,
        report=latest_report,
        report_view=_build_report_view(latest_report),
        is_finished=True,
    )


@pages_bp.get("/analysis")
def analysis_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    user_data = get_user(username)
    history_items = load_all_history_snapshot(username)
    from app.helpers import build_history_statistics
    history_stats = build_history_statistics(history_items)
    return render_template(
        "analysis.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        user_data=user_data,
        has_permission=user_data.get("monitoring_permission", False),
        history=history_items,
        history_stats=history_stats,
        analysis_data=_build_analysis_view(history_items),
    )


@pages_bp.get("/den")
def den_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    user_data = get_user(username)
    return render_template(
        "den.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        user_data=user_data,
        den_items=list_den_items(),
    )


@pages_bp.get("/shop")
def shop_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    user_data = get_user(username)
    shop_items = list_shop_items()
    return render_template(
        "shop.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        user_data=user_data,
        shop_items=shop_items,
    )


@pages_bp.get("/about")
def about_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    return render_template(
        "about.html", runtime=runtime_snapshot(include_adaptive=False, username=username)
    )


@pages_bp.get("/rules")
def rules_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    return render_template(
        "rules.html", runtime=runtime_snapshot(include_adaptive=False, username=username)
    )


@pages_bp.get("/profile")
def profile_page():
    if not session.get("username"):
        return _login_redirect()

    if clear_invalid_session():
        return redirect(url_for("pages.focus_page"))

    username = session.get("username")
    history = load_recent_history_snapshot(20, username)
    user_data = get_user(username)
    return render_template(
        "profile.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        history=history,
        user_data=user_data,
    )


@pages_bp.get("/success")
def success_page():
    if not session.get("username"):
        return _login_redirect()

    session.pop("running_session_id", None)
    return redirect(url_for("pages.report_page"))


@pages_bp.get("/evaluation/review")
def evaluation_review_page():
    if not session.get("username"):
        return _login_redirect()

    collector = _evaluation_collector()
    samples = _pending_review_samples(collector)
    username = session.get("username")
    return render_template(
        "evaluation_review.html",
        runtime=runtime_snapshot(include_adaptive=False, username=username),
        samples=samples,
        pending_count=len(samples),
    )


@pages_bp.get("/evaluation/review/image/<path:sample_id>")
def evaluation_review_image(sample_id: str):
    if not session.get("username"):
        abort(404)
    if not sample_id or len(sample_id) > 256 or "\x00" in sample_id:
        abort(404)

    response = _collector_image(_evaluation_collector(), sample_id)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@pages_bp.post("/evaluation/review/<path:sample_id>/label")
def evaluation_review_label(sample_id: str):
    if not session.get("username"):
        abort(404)
    collector = _evaluation_collector()
    raw_payload = request.get_json(silent=True)
    payload = raw_payload if isinstance(raw_payload, Mapping) else {}
    label = str(payload.get("label") or "").strip().lower()
    if label not in EVALUATION_LABELS:
        return jsonify({"error": "invalid_label", "allowed_labels": sorted(EVALUATION_LABELS)}), 400
    raw_annotation = payload.get("annotation")
    annotation = dict(raw_annotation) if isinstance(raw_annotation, Mapping) else None
    if label != "unscorable" and annotation is None:
        return jsonify({"error": "incomplete_human_annotation"}), 400
    if label == "unscorable" and annotation is None:
        annotation = {"scoring_rubric_version": EVALUATION_SCORING_RUBRIC_VERSION}
    if not sample_id or len(sample_id) > 256 or "\x00" in sample_id:
        abort(404)

    try:
        result = collector.label_sample(sample_id, label, annotation=annotation)
    except (KeyError, FileNotFoundError):
        return jsonify({"error": "sample_not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": "label_rejected", "message": str(exc)}), 400
    except (OSError, RuntimeError):
        current_app.logger.exception("failed to label evaluation sample %s", sample_id)
        return jsonify({"error": "label_failed"}), 500
    if result is False:
        return jsonify({"error": "sample_not_found"}), 404

    pending = _pending_review_samples(collector)
    return jsonify(
        {
            "success": True,
            "sample_id": sample_id,
            "label": label,
            "pending_count": len(pending),
        }
    )


@pages_bp.post("/evaluation/review/<path:sample_id>/discard")
def evaluation_review_discard(sample_id: str):
    if not session.get("username"):
        abort(404)
    collector = _evaluation_collector()
    if not sample_id or len(sample_id) > 256 or "\x00" in sample_id:
        abort(404)

    discard = getattr(collector, "discard_sample", None)
    if not callable(discard):
        return jsonify({"error": "discard_not_supported"}), 501
    try:
        result = discard(sample_id)
    except (KeyError, FileNotFoundError):
        return jsonify({"error": "sample_not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": "discard_rejected", "message": str(exc)}), 400
    except (OSError, RuntimeError):
        current_app.logger.exception("failed to discard evaluation sample %s", sample_id)
        return jsonify({"error": "discard_failed"}), 500
    if result is False:
        return jsonify({"error": "sample_not_found"}), 404

    pending = _pending_review_samples(collector)
    return jsonify(
        {
            "success": True,
            "sample_id": sample_id,
            "discarded": True,
            "pending_count": len(pending),
        }
    )
