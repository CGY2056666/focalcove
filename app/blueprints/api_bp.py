"""API 路由：/api/*, /health"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request, session

from app.helpers import (
    build_duration_recommendation,
    extract_goal_from_request,
    extract_int_from_request,
    load_recent_history_snapshot,
    normalize_selected_goal,
    serialize_history_entry,
)
from app.middlewares.validation import validate_session_id
from app.middlewares.auth import login_required
from app.services.den_service import (
    DenOperationError,
    exchange_furniture,
    save_den_config,
)
from app.services.history_service import load_all, load_recent
from app.services.user_service import mutate_user

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="")

@api_bp.get("/api/duration/recommend")
@login_required
def duration_recommend():
    goal = normalize_selected_goal(request.args.get("goal"))
    username = session.get("username")
    recommendation = build_duration_recommendation(goal, username)
    if recommendation is None:
        return jsonify({"error": "recommendation_unavailable"}), 503
    return jsonify({"goal": goal, "recommendation": recommendation})


@api_bp.get("/api/mode/recommend")
@login_required
def mode_recommend():
    goal = normalize_selected_goal(request.args.get("goal"))
    username = session.get("username")
    history = load_recent(20, username or "")

    duration_recommendation = build_duration_recommendation(goal, username)
    if not duration_recommendation:
        return jsonify({
            "recommended_mode": "regular",
            "reason": "首次使用，推荐从常规专注开始",
            "suggested_config": {"mode": "regular", "duration": 25, "monitoring": "medium"},
        })

    base_recommend = duration_recommendation.get("base_recommend", 25)
    total_sessions = len(history) if history else 0
    serialized_history = [serialize_history_entry(item) for item in history]
    reliable_history = [
        item
        for item in serialized_history
        if item.get("score_version") == "multidim-v1"
        and item.get("score_reliable") is True
        and item.get("coverage_ratio", 0) >= 0.70
        and item.get("completion_score") is not None
    ]
    avg_focus_score = 0
    if reliable_history:
        avg_focus_score = sum(item.get("completion_score", 0) for item in reliable_history) / len(reliable_history)

    # 提醒档位不根据连续相关度分数自动改变，避免权重调优间接改变提醒行为。
    # 原型保持固定的中档默认，用户仍可在开始会话时自行选择低/中/高档。
    recommended_mode = "regular"
    suggested_monitoring = "medium"
    mode_reason = (
        "已有数据较完整的记录；提醒档位保持中等默认，可在开始前自行调整"
        if reliable_history
        else "历史数据还不够完整，先使用中等提醒继续记录"
    )

    return jsonify({
        "recommended_mode": recommended_mode,
        "reason": mode_reason,
        "suggested_config": {
            "mode": recommended_mode,
            "duration": base_recommend,
            "monitoring": suggested_monitoring,
        },
        "stats": {
            "avg_focus_score": round(avg_focus_score, 1),
            "total_sessions": total_sessions,
            "reliable_sessions": len(reliable_history),
            "base_recommend": base_recommend,
        },
    })


@api_bp.get("/api/history/recent")
@login_required
def recent_history():
    try:
        limit = max(1, int(request.args.get("limit", 6)))
    except (TypeError, ValueError):
        limit = 6
    username = session.get("username")
    return jsonify({"items": load_recent_history_snapshot(limit, username)})


@api_bp.get("/api/history/all")
@login_required
def all_history():
    try:
        username = session.get("username")
        history = [serialize_history_entry(entry) for entry in load_all(username or "")]
        return jsonify({"items": history})
    except Exception as exc:
        logger.warning("failed to load all history: %s", exc)
        return jsonify({"error": "history_unavailable"}), 503


@api_bp.post("/api/shop/exchange")
def exchange_item():
    try:
        username = session.get("username")
        if not username:
            return jsonify({"error": "请先登录"}), 401

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "无效的商品"}), 400
        item_id = payload.get("item_id")

        try:
            state = exchange_furniture(username, item_id)
        except DenOperationError as exc:
            messages = {
                "invalid_item": "无效的商品",
                "insufficient_points": "积分不足",
                "already_owned": "该道具已解锁",
            }
            return jsonify({"error": messages.get(str(exc), "兑换失败")}), 400

        return jsonify({
            "success": True,
            "item_id": item_id,
            "remaining_points": state["points"],
        })
    except Exception:
        logger.exception("failed to exchange shop item")
        return jsonify({"error": "兑换失败"}), 500


@api_bp.post("/api/den/update")
def update_den():
    try:
        username = session.get("username")
        if not username:
            return jsonify({"error": "请先登录"}), 401

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "小窝配置无效"}), 400
        state = save_den_config(
            username,
            payload.get("den_config", {}),
        )
        return jsonify({"success": True, "den_config": state["config"]})
    except Exception:
        logger.exception("failed to update den configuration")
        return jsonify({"error": "更新失败"}), 500


@api_bp.post("/api/session/start")
@login_required
def start_session():
    from flask import current_app

    goal = extract_goal_from_request()
    if not goal:
        return jsonify({"error": "missing_goal"}), 400

    payload_data = request.get_json(silent=True) or {}
    monitoring_mode = payload_data.get("monitoring_mode", "medium")
    try:
        duration_minutes = extract_int_from_request("duration_minutes")
    except ValueError as exc:
        return jsonify({"error": f"invalid_{exc.args[0]}"}), 400

    session_service = current_app.extensions["focus_session_service"]
    try:
        payload = session_service.start(
            goal,
            username=session.get("username") or "",
            duration_minutes=duration_minutes,
            monitoring_mode=monitoring_mode,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        if str(exc) == "active_session_exists":
            return jsonify({"error": "active_session_exists"}), 409
        raise

    session["running_session_id"] = payload["session"]["session_id"]
    session.permanent = True

    return jsonify(payload)


@api_bp.post("/api/session/<session_id>/frame")
@login_required
def push_frame(session_id: str):
    from flask import current_app

    try:
        validate_session_id(session_id)
    except ValueError:
        return jsonify({"error": "invalid_session_id"}), 400

    file = request.files.get("screenshot")
    if not file or not file.filename:
        return jsonify({"error": "missing_screenshot"}), 400

    analyzer = current_app.extensions["analyzer"]
    if not analyzer.allowed_file(file.filename):
        return jsonify({"error": "unsupported_file_type"}), 400

    raw_captured_at = request.form.get("captured_at")
    try:
        captured_at = float(raw_captured_at) if raw_captured_at not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_captured_at"}), 400
    frame_id = (request.form.get("frame_id") or "").strip() or None

    session_service = current_app.extensions["focus_session_service"]
    try:
        payload = session_service.add_frame(
            session_id,
            file.filename,
            file.read(),
            frame_id=frame_id,
            captured_at=captured_at,
            username=session.get("username") or "",
        )
    except KeyError:
        return jsonify({"error": "session_not_found"}), 404
    except RuntimeError:
        return jsonify({"error": "session_not_running"}), 409
    except PermissionError:
        return jsonify({"error": "session_forbidden"}), 403
    return jsonify(payload)


@api_bp.get("/api/session/<session_id>")
@login_required
def session_snapshot(session_id: str):
    from flask import current_app

    try:
        validate_session_id(session_id)
    except ValueError:
        return jsonify({"error": "invalid_session_id"}), 400

    session_service = current_app.extensions["focus_session_service"]
    try:
        payload = session_service.snapshot(session_id, username=session.get("username") or "")
    except KeyError:
        return jsonify({"error": "session_not_found"}), 404
    except PermissionError:
        return jsonify({"error": "session_forbidden"}), 403
    return jsonify(payload)


@api_bp.post("/api/session/<session_id>/complete")
@login_required
def complete_session(session_id: str):
    from flask import current_app

    try:
        validate_session_id(session_id)
    except ValueError:
        session.pop("running_session_id", None)
        return jsonify({"error": "invalid_session_id"}), 400

    session_service = current_app.extensions["focus_session_service"]
    try:
        payload = session_service.complete(
            session_id,
            username=session.get("username") or "",
        )
    except KeyError:
        session.pop("running_session_id", None)
        return jsonify({"error": "session_not_found"}), 404
    except PermissionError:
        return jsonify({"error": "session_forbidden"}), 403

    session.pop("running_session_id", None)
    return jsonify(payload)


@api_bp.post("/api/session/reset")
@login_required
def reset_session():
    from flask import current_app

    running_session_id = session.pop("running_session_id", None)
    try:
        current_app.extensions["focus_session_service"].reset(
            running_session_id,
            username=session.get("username") or "",
        )
    except (KeyError, PermissionError):
        pass
    return jsonify({"success": True, "message": "会话已清除，现在可以访问其他页面"})


@api_bp.post("/api/user/permission")
@login_required
def update_user_permission():
    try:
        username = session.get("username") or ""
        payload = request.get_json(silent=True) or {}
        granted = bool(payload.get("monitoring_permission", False))
        mutate_user(
            username,
            lambda user_data: user_data.__setitem__("monitoring_permission", granted),
        )
        return jsonify({"success": True, "monitoring_permission": granted})
    except Exception:
        logger.exception("failed to save user permission")
        return jsonify({"error": "保存权限失败"}), 500


@api_bp.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "focus-compass",
            "api_version": "v1",
            "app_version": current_app.config.get("APP_VERSION", "dev"),
        }
    )
