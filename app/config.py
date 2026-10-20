"""Flask 配置类"""
from __future__ import annotations

import os
from pathlib import Path

BASEDIR = Path(__file__).resolve().parent.parent


class AppConfig:
    SECRET_KEY = os.environ.get("FOCUS_APP_SECRET", "focus-app-dev-secret")
    FOCUS_ENV = os.environ.get("FOCUS_ENV", "development").strip().lower()

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 原型只接收压缩后的单张截图
    PERMANENT_SESSION_LIFETIME = 3600 * 24  # 24 小时

    # Session 安全
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = FOCUS_ENV == "production"
    REQUIRE_HTTPS = FOCUS_ENV == "production"
    FOCUS_TRUST_PROXY_HEADERS = os.environ.get(
        "FOCUS_TRUST_PROXY_HEADERS", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}

    BROWSER_AUTH_RATE_LIMIT = int(os.environ.get("BROWSER_AUTH_RATE_LIMIT", 10))
    BROWSER_AUTH_RATE_WINDOW_SECONDS = int(
        os.environ.get("BROWSER_AUTH_RATE_WINDOW_SECONDS", 15 * 60)
    )
    MOBILE_AUTH_RATE_LIMIT = int(os.environ.get("MOBILE_AUTH_RATE_LIMIT", 20))
    MOBILE_AUTH_RATE_WINDOW_SECONDS = int(
        os.environ.get("MOBILE_AUTH_RATE_WINDOW_SECONDS", 60)
    )
    MOBILE_FRAME_RATE_LIMIT = int(os.environ.get("MOBILE_FRAME_RATE_LIMIT", 6))
    MOBILE_FRAME_RATE_WINDOW_SECONDS = int(
        os.environ.get("MOBILE_FRAME_RATE_WINDOW_SECONDS", 60)
    )
    MOBILE_CAPTURE_INTERVAL_SECONDS = int(
        os.environ.get("MOBILE_CAPTURE_INTERVAL_SECONDS", 20)
    )
    MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS = int(
        os.environ.get("MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS", 18)
    )
    MOBILE_CAPTURE_MAX_EDGE_PIXELS = int(
        os.environ.get("MOBILE_CAPTURE_MAX_EDGE_PIXELS", 1024)
    )
    MOBILE_CAPTURE_JPEG_QUALITY = int(
        os.environ.get("MOBILE_CAPTURE_JPEG_QUALITY", 72)
    )

    # 原型阶段统一使用 JSON 文件，测试可覆盖这些路径实现完全隔离。
    USERS_JSON_PATH = os.environ.get("USERS_JSON_PATH", str(BASEDIR / "users.json"))
    USER_DATA_JSON_DIR = os.environ.get("USER_DATA_JSON_DIR", str(BASEDIR / "user_data"))
    USER_HISTORY_JSON_DIR = os.environ.get(
        "USER_HISTORY_JSON_DIR", str(BASEDIR / "user_history")
    )
    MOBILE_SESSIONS_JSON_PATH = os.environ.get(
        "MOBILE_SESSIONS_JSON_PATH", str(BASEDIR / "mobile_sessions.json")
    )
    MOBILE_TOKEN_TTL_SECONDS = int(os.environ.get("MOBILE_TOKEN_TTL_SECONDS", 30 * 24 * 3600))
