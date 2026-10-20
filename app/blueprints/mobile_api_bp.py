"""Versioned JSON API consumed by the native Android client."""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request

from app.helpers import (
    build_duration_recommendation,
    normalize_selected_goal,
    serialize_history_entry,
)
from app.middlewares.validation import validate_session_id
from app.services.den_service import (
    DenOperationError,
    exchange_furniture,
    get_den_state,
    save_den_config,
)
from app.services.history_service import load_recent
from app.services.user_service import get_user


mobile_api_bp = Blueprint("mobile_api", __name__, url_prefix="/api/v1")

def capture_policy() -> dict[str, int | bool]:
    """Return the effective mobile capture contract advertised by this process."""
    return {
        "first_immediate": True,
        "interval_seconds": int(current_app.config["MOBILE_CAPTURE_INTERVAL_SECONDS"]),
        "max_edge_pixels": int(current_app.config["MOBILE_CAPTURE_MAX_EDGE_PIXELS"]),
        "jpeg_quality": int(current_app.config["MOBILE_CAPTURE_JPEG_QUALITY"]),
        "request_timeout_seconds": int(
            current_app.config["MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS"]
        ),
    }


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _serialize_alert(event: dict | None, latest_status: str) -> dict | None:
    if not isinstance(event, dict) or not event.get("event_id"):
        return None
    return {
        "event_id": str(event["event_id"]),
        "title": "专注提醒",
        "message": str(event.get("reason") or "检测到可能分心，请回到当前目标。"),
        "status": latest_status,
    }


def serialize_live(payload: dict, *, include_policy: bool = False) -> dict:
    session_data = payload.get("session") or {}
    latest = payload.get("latest_item") or {}
    latest_status = str(latest.get("state") or "pending_review")
    summary = payload.get("summary") or {}
    rolling_summary = str(
        payload.get("ai_advice")
        or summary.get("score_reliability_reason")
        or summary.get("reliability_reason")
        or ""
    )
    result = {
        "session_id": str(session_data.get("session_id") or ""),
        "goal": str(payload.get("goal") or ""),
        "duration_minutes": max(1, int(_number(session_data.get("duration_seconds"), 60) / 60)),
        "started_at": _number(session_data.get("created_at")),
        "remaining_seconds": max(0, int(_number(session_data.get("remaining_seconds")))),
        "status": str(session_data.get("status") or "running"),
        "latest_frame": (
            {
                "frame_id": str(latest.get("frame_id") or ""),
                "status": latest_status,
                "score": latest.get("focus_score"),
                "explanation": str(
                    latest.get("decision_reason")
                    or latest.get("warning")
                    or latest.get("status")
                    or ""
                ),
                "captured_at": _number(latest.get("captured_at")),
            }
            if latest
            else None
        ),
        "rolling_summary": rolling_summary,
        "alert_event": _serialize_alert(payload.get("alert_event"), latest_status),
    }
    if include_policy:
        result["capture_policy"] = capture_policy()
    recommendation = payload.get("duration_recommendation")
    if recommendation is not None:
        result["duration_recommendation"] = recommendation
    return result


def _report_from_history(entry: dict) -> dict:
    coverage = _number(entry.get("coverage_ratio"))
    return {
        "focus_score": entry.get("completion_score"),
        "focused_seconds": _number(entry.get("focus_duration_seconds")),
        "distracted_seconds": _number(entry.get("distract_duration_seconds")),
        "effective_coverage": coverage,
        "coverage_ratio": coverage,
        "reliable": bool(entry.get("score_reliable")),
        "summary": str(entry.get("ai_advice") or entry.get("feedback_text") or ""),
    }


def serialize_completed(payload: dict, *, already_completed: bool) -> dict:
    entry = payload.get("history_entry") or {}
    session_data = payload.get("session") or {}
    session_id = str(entry.get("session_id") or session_data.get("session_id") or "")
    return {
        "session_id": session_id,
        "already_completed": already_completed,
        "points_earned": int(_number(entry.get("earned_points"))),
        "report": _report_from_history(entry),
    }


def serialize_mobile_history(entry: dict) -> dict:
    item = serialize_history_entry(entry)
    coverage = _number(item.get("coverage_ratio"))
    completed_at = item.get("end_time")
    if completed_at is None:
        completed_at = entry.get("completed_at", entry.get("ended_at"))
    return {
        "session_id": str(item.get("session_id") or ""),
        "goal": str(item.get("goal") or ""),
        "started_at": item.get("started_at"),
        "completed_at": completed_at,
        "ended_at": completed_at,
        "duration_minutes": int(item.get("plan_duration") or 0),
        "focus_score": item.get("completion_score"),
        "points_earned": int(item.get("earned_points") or 0),
        "focused_seconds": _number(item.get("focus_duration_seconds")),
        "distracted_seconds": _number(item.get("distract_duration_seconds")),
        "effective_coverage": coverage,
        "coverage_ratio": coverage,
        "reliable": bool(item.get("score_reliable")),
        "summary": str(item.get("ai_advice") or item.get("feedback_text") or ""),
    }


def api_error(code: str, message: str, status: int, *, retryable: bool = False):
    return jsonify(
        {"error": {"code": code, "message": message, "retryable": retryable}}
    ), status


def _auth_rate_limit_error():
    remote_ip = request.remote_addr or "unknown"
    limiter = current_app.extensions["mobile_auth_rate_limiter"]
    if limiter.is_allowed(f"mobile-auth:{remote_ip}"):
        return None
    return api_error(
        "rate_limited",
        "认证请求过于频繁，请稍后再试",
        429,
        retryable=True,
    )


def _frame_rate_limit_error(session_id: str):
    limiter = current_app.extensions["mobile_frame_rate_limiter"]
    key = f"mobile-frame:{g.mobile_username}:{session_id}"
    if limiter.is_allowed(key):
        return None
    return api_error(
        "rate_limited",
        "截图上传过于频繁，请等待下一个采集点",
        429,
        retryable=True,
    )


def _bearer_token() -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token.strip()


def mobile_auth_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        token = _bearer_token()
        username = current_app.extensions["mobile_token_store"].resolve(token)
        if not username:
            return api_error("invalid_token", "登录已失效，请重新登录", 401)
        g.mobile_username = username
        g.mobile_token = token
        return view_func(*args, **kwargs)

    return wrapper


def _token_response(username: str):
    issued = current_app.extensions["mobile_token_store"].issue(username)
    return jsonify(
        {
            "access_token": issued["token"],
            "token_type": "Bearer",
            "username": username,
            "expires_at": issued["expires_at"],
        }
    )


@mobile_api_bp.post("/auth/register")
def register():
    limited = _auth_rate_limit_error()
    if limited is not None:
        return limited
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return api_error("missing_credentials", "请输入用户名和密码", 400)
    try:
        current_app.extensions["auth_service"].register(username, password)
    except ValueError as exc:
        if str(exc) == "username_exists":
            return api_error("username_exists", "用户名已存在", 409)
        return api_error("invalid_credentials", str(exc), 400)
    return _token_response(username), 201


@mobile_api_bp.post("/auth/login")
def login():
    limited = _auth_rate_limit_error()
    if limited is not None:
        return limited
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not current_app.extensions["auth_service"].authenticate(username, password):
        return api_error("invalid_credentials", "用户名或密码错误", 401)
    return _token_response(username)


@mobile_api_bp.post("/auth/logout")
@mobile_auth_required
def logout():
    current_app.extensions["mobile_token_store"].revoke(g.mobile_token)
    return jsonify({"success": True})


@mobile_api_bp.get("/bootstrap")
@mobile_auth_required
def bootstrap():
    goal = normalize_selected_goal(request.args.get("goal"))
    username = g.mobile_username
    user_data = get_user(username)
    recommendation = build_duration_recommendation(goal, username)
    suggested_minutes = int((recommendation or {}).get("base_recommend") or 25)
    return jsonify(
        {
            "username": username,
            "points": int(user_data.get("total_points", 0) or 0),
            "total_points": int(user_data.get("total_points", 0) or 0),
            "suggested_duration_minutes": suggested_minutes,
            "duration_recommendation": recommendation,
            "recent_history": [
                serialize_mobile_history(item) for item in load_recent(6, username)
            ],
            "capture_policy": capture_policy(),
        }
    )


@mobile_api_bp.get("/den")
@mobile_auth_required
def den_state():
    return jsonify(get_den_state(g.mobile_username))


@mobile_api_bp.put("/den")
@mobile_auth_required
def update_den_state():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("den_config"), dict):
        return api_error("invalid_den_config", "小窝配置无效", 400)
    return jsonify(save_den_config(g.mobile_username, payload["den_config"]))


@mobile_api_bp.post("/shop/exchanges")
@mobile_auth_required
def exchange_den_item():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("invalid_item", "家具不存在或暂不可兑换", 400)
    item_id = payload.get("item_id")
    try:
        state = exchange_furniture(g.mobile_username, item_id)
        already_owned = False
    except DenOperationError as exc:
        code = str(exc)
        if code == "already_owned":
            state = get_den_state(g.mobile_username)
            already_owned = True
        elif code == "insufficient_points":
            return api_error(code, "积分不足", 409)
        else:
            return api_error("invalid_item", "家具不存在或暂不可兑换", 400)
    return jsonify({
        **state,
        "item_id": item_id,
        "already_owned": already_owned,
    })


@mobile_api_bp.get("/focus-sessions/current")
@mobile_auth_required
def current_session():
    try:
        payload = current_app.extensions["focus_session_service"].current(g.mobile_username)
    except KeyError:
        return api_error("session_not_found", "没有可恢复的进行中会话", 404)
    return jsonify(serialize_live(payload, include_policy=True))


@mobile_api_bp.post("/focus-sessions")
@mobile_auth_required
def start_session():
    payload = request.get_json(silent=True) or {}
    goal = str(payload.get("goal") or "").strip()
    if not goal:
        return api_error("missing_goal", "请输入本次专注目标", 400)
    try:
        duration_minutes = int(payload.get("duration_minutes", 25))
    except (TypeError, ValueError):
        return api_error("invalid_duration", "专注时长无效", 400)
    monitoring_mode = str(payload.get("monitoring_mode") or "medium")
    try:
        result = current_app.extensions["focus_session_service"].start(
            goal,
            username=g.mobile_username,
            duration_minutes=duration_minutes,
            monitoring_mode=monitoring_mode,
        )
    except ValueError as exc:
        return api_error(str(exc), "专注参数无效", 400)
    except RuntimeError as exc:
        if str(exc) == "active_session_exists":
            return api_error("active_session_exists", "已有进行中的专注会话", 409)
        raise
    return jsonify(serialize_live(result, include_policy=True)), 201


def _validate_owned_session_id(session_id: str):
    try:
        validate_session_id(session_id)
    except ValueError:
        return api_error("invalid_session_id", "会话编号无效", 400)
    return None


@mobile_api_bp.post("/focus-sessions/<session_id>/frames")
@mobile_auth_required
def push_frame(session_id: str):
    invalid = _validate_owned_session_id(session_id)
    if invalid:
        return invalid
    session_service = current_app.extensions['focus_session_service']
    try:
        session_service.assert_owner(session_id, username=g.mobile_username)
    except KeyError:
        return api_error('session_not_found', '会话不存在或已中断', 404)
    except PermissionError:
        return api_error('session_forbidden', '无权访问该会话', 403)
    limited = _frame_rate_limit_error(session_id)
    if limited is not None:
        return limited
    screenshot = request.files.get("screenshot")
    if not screenshot or not screenshot.filename:
        return api_error("missing_screenshot", "缺少截图", 400)
    analyzer = current_app.extensions["analyzer"]
    if not analyzer.allowed_file(screenshot.filename):
        return api_error("unsupported_file_type", "截图格式不支持", 400)
    raw_captured_at = request.form.get("captured_at")
    try:
        captured_at = float(raw_captured_at) if raw_captured_at not in (None, "") else None
    except (TypeError, ValueError):
        return api_error("invalid_captured_at", "截图时间无效", 400)
    frame_id = (request.form.get("frame_id") or "").strip() or None
    try:
        result = current_app.extensions["focus_session_service"].add_frame(
            session_id,
            screenshot.filename,
            screenshot.read(),
            frame_id=frame_id,
            captured_at=captured_at,
            username=g.mobile_username,
        )
    except KeyError:
        return api_error("session_not_found", "会话不存在或已中断", 404)
    except PermissionError:
        return api_error("session_forbidden", "无权访问该会话", 403)
    except RuntimeError:
        return api_error("session_not_running", "会话已结束", 409)
    return jsonify(serialize_live(result))


@mobile_api_bp.get("/focus-sessions/<session_id>")
@mobile_auth_required
def session_snapshot(session_id: str):
    invalid = _validate_owned_session_id(session_id)
    if invalid:
        return invalid
    try:
        result = current_app.extensions["focus_session_service"].snapshot(
            session_id, username=g.mobile_username
        )
    except KeyError:
        return api_error("session_not_found", "会话不存在或已中断", 404)
    except PermissionError:
        return api_error("session_forbidden", "无权访问该会话", 403)
    return jsonify(serialize_live(result))


@mobile_api_bp.post("/focus-sessions/<session_id>/complete")
@mobile_auth_required
def complete_session(session_id: str):
    invalid = _validate_owned_session_id(session_id)
    if invalid:
        return invalid
    try:
        result, already_completed = current_app.extensions["focus_session_service"].complete_with_status(
            session_id, username=g.mobile_username
        )
    except KeyError:
        return api_error("session_not_found", "会话不存在或已中断", 404)
    except PermissionError:
        return api_error("session_forbidden", "无权访问该会话", 403)
    return jsonify(serialize_completed(result, already_completed=already_completed))


@mobile_api_bp.delete("/focus-sessions/<session_id>")
@mobile_auth_required
def discard_session(session_id: str):
    invalid = _validate_owned_session_id(session_id)
    if invalid:
        return invalid
    try:
        current_app.extensions["focus_session_service"].reset(
            session_id, username=g.mobile_username
        )
    except KeyError:
        return api_error("session_not_found", "会话不存在或已中断", 404)
    except PermissionError:
        return api_error("session_forbidden", "无权访问该会话", 403)
    return jsonify({"success": True})


@mobile_api_bp.get("/history")
@mobile_auth_required
def history():
    try:
        limit = min(50, max(1, int(request.args.get("limit", 50))))
    except (TypeError, ValueError):
        return api_error("invalid_limit", "历史数量无效", 400)
    try:
        items = [serialize_mobile_history(item) for item in load_recent(limit, g.mobile_username)]
    except OSError:
        return api_error("history_unavailable", "历史记录暂不可用", 503, retryable=True)
    return jsonify({"items": items})
