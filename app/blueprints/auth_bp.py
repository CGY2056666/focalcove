"""Browser authentication routes backed by the shared AuthService."""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for


auth_bp = Blueprint("auth", __name__, url_prefix="")


def _auth_rate_limited() -> bool:
    limiter = current_app.extensions.get("browser_auth_rate_limiter")
    if limiter is None:
        return False
    return not limiter.is_allowed(request.remote_addr or "unknown")


@auth_bp.get("/login")
def login_page():
    if session.get("username"):
        return redirect(url_for("pages.home"))
    return render_template("login.html")


@auth_bp.post("/login")
def login():
    if _auth_rate_limited():
        return render_template("login.html", error="尝试过于频繁，请稍后再试"), 429
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if not username or not password:
        return render_template("login.html", error="请输入用户名和密码")

    if not current_app.extensions["auth_service"].authenticate(username, password):
        return render_template("login.html", error="用户名或密码错误")

    session["username"] = username
    session.permanent = True
    return redirect(url_for("pages.home"))


@auth_bp.get("/register")
def register_page():
    if session.get("username"):
        return redirect(url_for("pages.home"))
    return render_template("register.html")


@auth_bp.post("/register")
def register():
    if _auth_rate_limited():
        return render_template("register.html", error="尝试过于频繁，请稍后再试"), 429
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not username or not password or not confirm_password:
        return render_template("register.html", error="请填写所有必填字段")
    if password != confirm_password:
        return render_template("register.html", error="两次输入的密码不一致")

    try:
        current_app.extensions["auth_service"].register(username, password)
    except ValueError as exc:
        message = "用户名已存在" if str(exc) == "username_exists" else str(exc)
        return render_template("register.html", error=message)

    session["username"] = username
    session.permanent = True
    return render_template("register.html", success="注册成功！")


@auth_bp.get("/logout")
def logout():
    username = session.get("username") or ""
    running_session_id = session.get("running_session_id")
    if username and running_session_id:
        try:
            current_app.extensions["focus_session_service"].reset(
                running_session_id,
                username=username,
            )
        except (KeyError, PermissionError):
            pass
    session.pop("username", None)
    session.pop("running_session_id", None)
    return redirect(url_for("auth.login_page"))
