"""应用工厂"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

# 在导入任何其他模块前加载 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.config import AppConfig
from app.logging_config import configure_logging


def _validate_production_runtime_paths(app: Flask) -> None:
    """Refuse bundled development JSON locations in production."""
    if app.config.get("FOCUS_ENV") != "production":
        return
    root = Path(__file__).resolve().parent.parent
    defaults = {
        "USERS_JSON_PATH": root / "users.json",
        "USER_DATA_JSON_DIR": root / "user_data",
        "USER_HISTORY_JSON_DIR": root / "user_history",
        "MOBILE_SESSIONS_JSON_PATH": root / "mobile_sessions.json",
    }
    unsafe = []
    for key, default in defaults.items():
        raw = str(app.config.get(key) or "").strip()
        if not raw:
            unsafe.append(key)
            continue
        configured = Path(raw).expanduser().resolve()
        if configured == default.resolve():
            unsafe.append(key)
    if unsafe:
        raise RuntimeError(
            "Production runtime paths must use dedicated persistent locations: "
            + ", ".join(sorted(unsafe))
        )


def _validate_mobile_capture_config(app: Flask) -> None:
    bounds = {
        "MOBILE_CAPTURE_INTERVAL_SECONDS": (5, 300),
        "MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS": (1, 60),
        "MOBILE_CAPTURE_MAX_EDGE_PIXELS": (320, 4096),
        "MOBILE_CAPTURE_JPEG_QUALITY": (30, 95),
    }
    invalid = []
    for key, (minimum, maximum) in bounds.items():
        value = int(app.config[key])
        if value < minimum or value > maximum:
            invalid.append(f"{key}={value}")
    if (
        int(app.config["MOBILE_CAPTURE_REQUEST_TIMEOUT_SECONDS"])
        >= int(app.config["MOBILE_CAPTURE_INTERVAL_SECONDS"])
    ):
        invalid.append("request timeout must be shorter than capture interval")
    if invalid:
        raise RuntimeError("Invalid mobile capture configuration: " + ", ".join(invalid))


def create_app(config_class=AppConfig):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(config_class)
    _validate_mobile_capture_config(app)

    if app.config.get("FOCUS_ENV") == "production":
        secret = str(app.config.get("SECRET_KEY") or "").strip()
        rejected_secrets = {
            "focus-app-dev-secret",
            "replace_with_at_least_32_random_bytes",
            "placeholder",
            "changeme",
            "change-me",
        }
        normalized_secret = secret.lower()
        if (
            len(secret) < 32
            or normalized_secret in rejected_secrets
            or "placeholder" in normalized_secret
            or normalized_secret.startswith("replace_")
        ):
            raise RuntimeError(
                "Production requires FOCUS_APP_SECRET with at least 32 non-placeholder characters"
            )
        _validate_production_runtime_paths(app)

    if (
        app.config.get("FOCUS_ENV") == "production"
        and app.config.get("FOCUS_TRUST_PROXY_HEADERS")
    ):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)

    def is_mobile_api_request() -> bool:
        return request.path == "/api/v1" or request.path.startswith("/api/v1/")

    @app.before_request
    def require_https():
        if (
            app.config.get("REQUIRE_HTTPS")
            and request.path != "/health"
            and not request.is_secure
        ):
            if is_mobile_api_request():
                return jsonify(
                    {
                        "error": {
                            "code": "https_required",
                            "message": "此接口仅允许 HTTPS",
                            "retryable": False,
                        }
                    }
                ), 400
            return "HTTPS required", 400

    @app.after_request
    def secure_response_headers(response):
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if is_mobile_api_request():
            # Authentication responses may contain a bearer token. Neither those
            # responses nor session snapshots should be retained by intermediaries.
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.errorhandler(HTTPException)
    def mobile_http_error(error):
        if not is_mobile_api_request():
            return error
        code_by_status = {
            404: "endpoint_not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
        }
        message_by_status = {
            404: "接口不存在",
            405: "请求方法不允许",
            413: "请求内容过大",
        }
        status = int(error.code or 500)
        return jsonify(
            {
                "error": {
                    "code": code_by_status.get(status, "http_error"),
                    "message": message_by_status.get(status, str(error.description)),
                    "retryable": False,
                }
            }
        ), status

    @app.errorhandler(Exception)
    def mobile_unhandled_error(error):
        if not is_mobile_api_request():
            raise error
        if app.config.get("TESTING"):
            raise error
        app.logger.exception("Unhandled mobile API error")
        return jsonify(
            {
                "error": {
                    "code": "internal_error",
                    "message": "服务器内部错误",
                    "retryable": True,
                }
            }
        ), 500

    app.config.setdefault("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)
    app.config["PERMANENT_SESSION_LIFETIME"] = 3600 * 24

    # Session 安全
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", False)

    # 日志
    configure_logging(app)

    # Jinja 过滤器
    @app.template_filter("datetimeformat")
    def datetimeformat(value: Any) -> str:
        try:
            timestamp = int(float(value))
            if timestamp <= 0:
                return "--"
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            return "--"

    # 初始化引擎并挂载到 app.extensions
    from focus_engine import DEFAULT_CONFIG, FocusAnalyzer, StreamingSessionManager
    from focus_engine.duration_recommender import FocusDurationRecommender
    from app.services.evaluation_sample_collector import EvaluationSampleCollector
    from app.services.focus_session_service import FocusSessionService
    from app.services.auth_service import AuthService, MobileTokenStore
    from app.middlewares.ratelimit import RateLimiter

    analyzer = FocusAnalyzer(DEFAULT_CONFIG)
    session_manager = StreamingSessionManager(analyzer, DEFAULT_CONFIG)
    duration_recommender = FocusDurationRecommender(DEFAULT_CONFIG)
    scorer_status = analyzer.scoring_status()
    evaluation_collector = EvaluationSampleCollector(
        DEFAULT_CONFIG.focus_eval_capture_dir,
        enabled=DEFAULT_CONFIG.focus_eval_capture_enabled,
        provider=str(scorer_status.get("provider") or DEFAULT_CONFIG.vision_provider),
        model=str(scorer_status.get("model") or ""),
        enabled_check=lambda: not bool(app.config.get("TESTING", False)),
        duplicate_distance_threshold=DEFAULT_CONFIG.duplicate_distance_threshold,
    )
    focus_session_service = FocusSessionService(
        session_manager,
        duration_recommender,
        evaluation_collector=evaluation_collector,
    )
    auth_service = AuthService(
        app.config["USERS_JSON_PATH"],
        app.config["USER_DATA_JSON_DIR"],
    )
    mobile_token_store = MobileTokenStore(
        app.config["MOBILE_SESSIONS_JSON_PATH"],
        ttl_seconds=app.config["MOBILE_TOKEN_TTL_SECONDS"],
    )
    mobile_auth_rate_limiter = RateLimiter(
        app.config["MOBILE_AUTH_RATE_LIMIT"],
        app.config["MOBILE_AUTH_RATE_WINDOW_SECONDS"],
    )
    mobile_frame_rate_limiter = RateLimiter(
        app.config["MOBILE_FRAME_RATE_LIMIT"],
        app.config["MOBILE_FRAME_RATE_WINDOW_SECONDS"],
    )
    browser_auth_rate_limiter = RateLimiter(
        app.config["BROWSER_AUTH_RATE_LIMIT"],
        app.config["BROWSER_AUTH_RATE_WINDOW_SECONDS"],
    )

    app.extensions["config"] = DEFAULT_CONFIG
    app.extensions["analyzer"] = analyzer
    app.extensions["session_manager"] = session_manager
    app.extensions["duration_recommender"] = duration_recommender
    app.extensions["evaluation_collector"] = evaluation_collector
    app.extensions["focus_session_service"] = focus_session_service
    app.extensions["auth_service"] = auth_service
    app.extensions["mobile_token_store"] = mobile_token_store
    app.extensions["mobile_auth_rate_limiter"] = mobile_auth_rate_limiter
    app.extensions["mobile_frame_rate_limiter"] = mobile_frame_rate_limiter
    app.extensions["browser_auth_rate_limiter"] = browser_auth_rate_limiter

    # 注册蓝图
    from app.blueprints.auth_bp import auth_bp
    from app.blueprints.pages_bp import pages_bp
    from app.blueprints.api_bp import api_bp
    from app.blueprints.mobile_api_bp import mobile_api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(mobile_api_bp)

    return app
