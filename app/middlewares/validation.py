"""输入校验函数"""
from __future__ import annotations

import re

_USERNAME_RE = re.compile(r"^[\w一-鿿_-]{1,32}$")
_SESSION_ID_RE = re.compile(r"^[a-fA-F0-9]{8,64}$")


def validate_username(username: str | None) -> str:
    if not username or not username.strip():
        raise ValueError("用户名不能为空")
    username = username.strip()
    if ".." in username or "/" in username or "\\" in username:
        raise ValueError("用户名包含非法字符")
    if not _USERNAME_RE.match(username):
        raise ValueError("用户名须为 1–32 个中文、字母、数字、下划线或连字符")
    return username


def validate_password(password: str | None) -> str:
    if not password:
        raise ValueError("密码不能为空")
    if len(password) < 8:
        raise ValueError("密码至少需要8个字符")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("密码需要包含字母和数字")
    return password


def validate_session_id(session_id: str | None) -> str:
    if not session_id or not _SESSION_ID_RE.match(session_id):
        raise ValueError("无效的会话 ID")
    return session_id


def validate_int_range(value, minimum: int, maximum: int, name: str = "参数") -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}必须是整数")
    if num < minimum or num > maximum:
        raise ValueError(f"{name}超出范围 ({minimum}-{maximum})")
    return num


def sanitize_goal(goal: str | None) -> str:
    if not goal:
        return ""
    return goal.strip()[:160]
