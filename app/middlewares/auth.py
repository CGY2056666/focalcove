"""认证装饰器和 before_request 钩子"""
from __future__ import annotations

from functools import wraps

from flask import redirect, request, session, url_for, jsonify


def login_required(view_func):
    """装饰器：要求登录，页面路由重定向，API 路由返回 JSON 错误"""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "请先登录"}), 401
            return redirect(url_for("auth.login_page"))
        return view_func(*args, **kwargs)

    return wrapper


def require_no_session(view_func):
    """装饰器：如果已有运行中会话则重定向到专注页"""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        running_id = session.get("running_session_id")
        if running_id:
            from flask import current_app

            session_mgr = current_app.extensions["session_manager"]
            try:
                session_mgr.snapshot(running_id)
                return redirect(url_for("pages.focus_page"))
            except KeyError:
                session.pop("running_session_id", None)
        return view_func(*args, **kwargs)

    return wrapper
