#本部分使用AI辅助进行了编程：Qwen3.5plus 2026.04.01 2026.04.10
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import time
from typing import Any
from urllib import error, request

import cv2
import numpy as np

logger = logging.getLogger(__name__)

from .config import AnalyzerConfig, DEFAULT_CONFIG
from .models import GoalProfile
from .scoring_policy import SCORE_VERSION, score_components
from .utils import LRUCache, clamp


SYSTEM_PROMPT = """你是画面任务相关度分析器。只评价截图中的可见内容是否服务当前目标，不推断用户的心理专注程度，不猜测不可见内容。

category_type 只能是：
- focus：截图有明确证据正在服务当前目标。
- neutral：通用工具、空白页、证据不足或无法判断；neutral 不是分心。
- distract：截图有明确证据与当前目标无关。若娱乐、购物等本身就是目标，则不能据此判为分心。

输出四个互相独立的 0-4 整数维度，统一锚点为：0=完全没有或相反，1=弱，2=一般或无法确认，3=明确，4=直接且充分。
- goal_relevance：画面主体与具体目标的相关程度。
- task_evidence：是否有实际阅读、编写、检索、操作或产出的可见证据。
- context_fit：当前应用、网页或工具是否适合完成目标。
- distraction_level：无关内容在画面中的主导程度。

约束：
- focus 必须同时满足 goal_relevance>=3、task_evidence>=2、distraction_level<=1，否则应选 neutral。
- distract 必须同时满足 distraction_level>=3、goal_relevance<=1，否则应选 neutral。
- 专注小窝自身页面仅显示目标文字时，task_evidence 最高只能为1，且应选 neutral；只有目标本身是开发或测试专注小窝，并出现实际开发证据时例外。
- 空白页、欢迎页、没有任务内容的通用 IDE 或文件管理器应选 neutral。
- 目标相关网站必须显示正在处理的具体目标内容，不能只凭网站类型选 focus。

只输出一个 JSON 对象，字段必须为：category_type、category_label、goal_relevance、task_evidence、context_fit、distraction_level、confidence、reason。
confidence 为 0-1；reason 用一句简短中文说明可见证据。不要计算或输出总分。
不要输出 Markdown、OCR 全文、思考过程或额外字段。"""

_REQUIRED_RESPONSE_FIELDS = {
    "category_type",
    "category_label",
    "goal_relevance",
    "task_evidence",
    "context_fit",
    "distraction_level",
    "confidence",
    "reason",
}

_FOCUS_HOME_DIRECT_MARKERS = (
    "专注小窝",
    "专注工具",
    "专注计时器",
    "专注计时",
    "focus compass",
    "focus timer",
    "pomodoro",
)
_FOCUS_HOME_LABEL_MARKERS = ("专注工具设置页", "专注任务执行中")
_FOCUS_HOME_TIMER_MARKERS = ("倒计时", "当前目标", "剩余时间")
_FOCUS_HOME_DEVELOPMENT_INTENTS = (
    "开发",
    "测试",
    "调试",
    "编程",
    "代码",
    "前端",
    "后端",
    "接口",
    "重构",
    "修复",
)
_VISIBLE_DEVELOPMENT_EVIDENCE = (
    "代码编辑器",
    "正在编辑",
    "源码",
    "ide",
    "终端",
    "命令行",
    "控制台",
    "开发者工具",
    "测试结果",
    "测试通过",
    "pytest",
    "unittest",
    ".py",
    ".js",
    ".html",
    "函数",
    "类定义",
    "flask",
)


def _looks_like_focus_home_page(category_label: str, reason: str) -> bool:
    label = category_label.casefold()
    evidence = f"{category_label} {reason}".casefold()
    if any(marker in evidence for marker in _FOCUS_HOME_DIRECT_MARKERS):
        return True
    return any(marker in label for marker in _FOCUS_HOME_LABEL_MARKERS) and any(
        marker in evidence for marker in _FOCUS_HOME_TIMER_MARKERS
    )


def _has_visible_focus_home_development_evidence(
    profile: GoalProfile,
    category_label: str,
    reason: str,
) -> bool:
    goal = f"{profile.raw_goal} {profile.normalized_goal}".casefold()
    evidence = f"{category_label} {reason}".casefold()
    product_is_goal = any(marker in goal for marker in ("专注小窝", "focus compass"))
    development_is_goal = any(marker in goal for marker in _FOCUS_HOME_DEVELOPMENT_INTENTS)
    visible_development = any(marker in evidence for marker in _VISIBLE_DEVELOPMENT_EVIDENCE)
    return product_is_goal and development_is_goal and visible_development


def _resize_for_api(image: np.ndarray, config: AnalyzerConfig) -> np.ndarray:
    height, width = image.shape[:2]
    max_edge = max(height, width)
    if max_edge <= config.max_image_edge:
        return image
    scale = config.max_image_edge / max_edge
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _jpeg_data_url_and_digest(image: np.ndarray) -> tuple[str, str]:
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok or buf is None:
        raise RuntimeError("无法将截图编码为 JPEG。")
    raw = buf.tobytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    return f"data:image/jpeg;base64,{b64}", digest


def _extract_json_payload(content: str) -> str:
    """
    从一段可能“夹带额外文本/代码块”的输出中提取第一个完整的 JSON 对象。
    使用简易的括号计数，并正确处理字符串内的花括号/引号转义。
    """
    stripped = content.strip()
    start = stripped.find("{")
    if start == -1:
        raise RuntimeError("模型返回内容中未找到 '{'，无法提取 JSON。")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "\"":
                in_string = False
            continue

        if ch == "\"":
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]

    raise RuntimeError("模型返回 JSON 对象未闭合，可能是输出被截断。")


class SiliconFlowVlmScorer:
    """通过 SiliconFlow OpenAI 兼容接口调用千问等多模态模型，一次性完成「读图 + 评分」。"""

    def __init__(self, config: AnalyzerConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.cache = LRUCache(config.llm_cache_size)
        self.provider_name = "siliconflow"
        self.api_key = config.siliconflow_api_key
        self.base_url = config.siliconflow_base_url
        self.model = config.siliconflow_model

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": bool(self.api_key),
            "model": self.model,
            "base_url": self.base_url,
        }

    def vision_ready_message(self) -> tuple[bool, str]:
        if self.api_key:
            label = "阿里云百炼" if self.provider_name == "bailian" else "SiliconFlow"
            return True, f"{label} · {self.model}"
        env_name = "BAILIAN_API_KEY" if self.provider_name == "bailian" else "SILICONFLOW_API_KEY"
        return False, f"请配置 {env_name}（视觉模型）"

    def analyze(
        self,
        profile: GoalProfile,
        filename: str,
        image_bgr: np.ndarray,
        thumbnail_hash: str,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        if not self.api_key:
            return self._review_result("视觉模型 API Key 未配置。", 0.0)

        resized = _resize_for_api(image_bgr, self.config)
        try:
            data_url, jpeg_digest = _jpeg_data_url_and_digest(resized)
        except Exception:
            logger.exception("VLM screenshot encoding failed")
            return self._review_result("截图编码失败，本帧待复核。", 0.0)

        cache_key = self._cache_key(profile, jpeg_digest)
        if not bypass_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                out = dict(cached)
                out["cache_hit"] = True
                return out

        system_prompt, user_text = self._build_text_prompt(profile, filename)
        started = time.perf_counter()
        try:
            logger.info(
                "VLM 请求开始：provider=%s goal_len=%d",
                self.provider_name,
                len(profile.normalized_goal),
            )
            payload_raw = self._request_completion(system_prompt, user_text, data_url, use_json_object=True)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "VLM 请求完成：%dms provider=%s",
                elapsed_ms,
                self.provider_name,
            )
            result = self._normalize_response(payload_raw, 0.0, "", profile)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            error_message = str(exc)
            if "account balance is insufficient" in error_message:
                logger.warning("VLM 余额不足：%dms", elapsed_ms)
                return self._review_result("视觉模型账户余额不足，请充值后再使用。", 0.0)
            logger.warning(
                "VLM 调用失败（%dms）：provider=%s error=%s",
                elapsed_ms,
                self.provider_name,
                type(exc).__name__,
            )
            return self._review_result("视觉模型调用失败，本帧待复核。", 0.0)

        result["score_breakdown"]["llm_latency_ms"] = float(elapsed_ms)
        if result.get("review_required"):
            result["cache_hit"] = False
            return result
        result["score_breakdown"]["vlm_scored"] = 1.0
        self.cache.set(cache_key, dict(result))
        result["cache_hit"] = False
        return result

    def _cache_key(self, profile: GoalProfile, jpeg_digest: str) -> str:
        payload = {
            "goal": profile.normalized_goal,
            "model": self.model,
            "score_version": SCORE_VERSION,
            "jpeg_digest": jpeg_digest,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _build_text_prompt(self, profile: GoalProfile, filename: str) -> tuple[str, str]:
        output_schema = {
            "category_type": "neutral",
            "category_label": "通用工具界面",
            "goal_relevance": 2,
            "task_evidence": 1,
            "context_fit": 2,
            "distraction_level": 1,
            "confidence": 0.42,
            "reason": "截图属于通用工作环境，但缺少与目标直接相关的可见证据",
        }
        lines = [
            f"当前目标：{profile.raw_goal}",
            f"核心线索：{json.dumps(profile.core_keywords[:10], ensure_ascii=False)}",
            f"相关场景：{json.dumps(profile.scene_keywords[:8], ensure_ascii=False)}",
            f"可能无关的线索（必须结合目标判断）：{json.dumps(profile.negative_keywords[:6], ensure_ascii=False)}",
            "请结合截图输出以下 JSON：",
            json.dumps(output_schema, ensure_ascii=False),
        ]
        return SYSTEM_PROMPT, "\n".join(lines)

    def _request_completion(
        self,
        system_prompt: str,
        user_text: str,
        image_data_url: str,
        *,
        use_json_object: bool,
    ) -> dict[str, Any]:
        endpoint = self._build_endpoint()
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.config.siliconflow_temperature,
            "max_tokens": self.config.siliconflow_max_tokens,
            "enable_thinking": self.config.siliconflow_enable_thinking,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        }
        if use_json_object:
            payload["response_format"] = {"type": "json_object"}

        # 实时帧只调用一次；任何超时、HTTP 错误或解析失败都标记为待复核。
        return self._post_chat_completion(endpoint, payload)

    def _post_chat_completion(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.config.siliconflow_timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {error_body[:400]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"网络请求失败：{exc.reason}") from exc

        try:
            body = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            snippet = raw_response[:400].replace("\n", "\\n")
            raise RuntimeError(f"视觉模型返回了非 JSON 响应：{exc}. raw_snippet={snippet}") from exc
        message = ((body.get("choices") or [{}])[0].get("message") or {})
        content = str(message.get("content") or "").strip()
        reasoning = str(message.get("reasoning_content") or "").strip()
        if not content and reasoning:
            content = reasoning
        if not content:
            raise RuntimeError("模型返回了空内容。")

        # 优先把 content 当作“纯 JSON”直接解析；失败再做花括号提取与二次解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            extracted = _extract_json_payload(content)
            try:
                return json.loads(extracted)
            except json.JSONDecodeError as exc:
                snippet = content[:400].replace("\n", "\\n")
                raise RuntimeError(
                    f"模型返回内容JSON解析失败：{exc}. content_snippet={snippet}"
                ) from exc

    def _build_endpoint(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _normalize_response(
        self,
        payload: dict[str, Any],
        ocr_quality: float,
        ocr_text: str,
        profile: GoalProfile | None = None,
    ) -> dict[str, Any]:
        validation_error = self._validate_response(payload)
        if validation_error:
            return self._review_result(f"模型响应无效：{validation_error}", 0.0)

        requested_category = self._normalize_category(payload.get("category_type"))
        category_label = str(
            payload.get("category_label") or self._default_category_label(requested_category)
        ).strip()
        reason = str(payload.get("reason") or "模型已完成截图分析。").strip()
        goal_relevance = self._coerce_dimension_level(payload.get("goal_relevance"))
        task_evidence = self._coerce_dimension_level(payload.get("task_evidence"))
        context_fit = self._coerce_dimension_level(payload.get("context_fit"))
        distraction_level = self._coerce_dimension_level(payload.get("distraction_level"))
        confidence = self._coerce_score(payload.get("confidence"))

        # 模型偶尔会把“目标文字 + 倒计时”本身当成任务产出。这里不做 OCR
        # 或图像分类，只依据模型自己的场景说明做最小保护；同时保留模型原始
        # 四维值，供离线 benchmark 与调权诊断使用。
        model_category_type = requested_category
        model_goal_relevance = goal_relevance
        model_task_evidence = task_evidence
        model_context_fit = context_fit
        model_distraction_level = distraction_level
        focus_home_guard_applied = bool(
            profile is not None
            and _looks_like_focus_home_page(category_label, reason)
            and not _has_visible_focus_home_development_evidence(
                profile,
                category_label,
                reason,
            )
        )
        if focus_home_guard_applied:
            task_evidence = min(task_evidence, 1)

        category_type = self._gate_category(
            requested_category,
            goal_relevance,
            task_evidence,
            distraction_level,
        )
        status = self._normalize_status(category_type)
        model_reason = reason
        if focus_home_guard_applied:
            reason = f"{reason}；专注小窝自身页面未出现实际开发证据，任务证据按1级处理"
        if category_type != requested_category:
            reason = f"{reason}；类别与维度条件冲突，已降为证据不足"

        goal_relevance_score = float(goal_relevance * 25)
        task_evidence_score = float(task_evidence * 25)
        context_fit_score = float(context_fit * 25)
        distraction_score = round(distraction_level / 4.0, 3)
        calculated = score_components(
            goal_relevance_score,
            task_evidence_score,
            context_fit_score,
            distraction_score,
            confidence,
        )
        focus_score = calculated["confidence_adjusted_score"]
        focus_probability = round(clamp(focus_score / 100.0), 3)

        # 八字段响应是唯一证据源。下面这些键仅为兼容现有 FrameAnalysis
        # 数据结构而保留，不能从模型额外返回的旧字段或调用参数中取值。
        ocr_text = ""
        ocr_quality = 0.0
        semantic_match_score = 0.0
        keyword_hit_score = 0.0
        strong_hit_score = 0.0
        coverage_score = 0.0
        structure_score = 0.0
        app_context_score = 0.0
        relevance_score = round(goal_relevance_score / 100.0, 3)
        matched_keywords: list[str] = []
        strong_hits: list[str] = []
        scene_hits: list[str] = []
        support_hits: list[str] = []
        negative_hits: list[str] = []
        matched_context_patterns: list[str] = []
        positive_rule = ""
        negative_rule = ""

        return {
            "score_version": SCORE_VERSION,
            "ocr_text": ocr_text,
            "ocr_quality": ocr_quality,
            "category_type": category_type,
            "category_label": category_label,
            "semantic_match_score": semantic_match_score,
            "keyword_hit_score": keyword_hit_score,
            "strong_hit_score": strong_hit_score,
            "coverage_score": coverage_score,
            "structure_score": structure_score,
            "app_context_score": app_context_score,
            "relevance_score": relevance_score,
            "goal_relevance_score": goal_relevance_score,
            "task_evidence_score": task_evidence_score,
            "context_fit_score": context_fit_score,
            "distraction_score": distraction_score,
            "focus_score": focus_score,
            "focus_probability": focus_probability,
            "confidence": confidence,
            "status": status,
            "matched_keywords": matched_keywords,
            "strong_hits": strong_hits,
            "scene_hits": scene_hits,
            "support_hits": support_hits,
            "negative_hits": negative_hits,
            "matched_context_patterns": matched_context_patterns,
            "positive_rule": positive_rule,
            "negative_rule": negative_rule,
            "reason": reason,
            "fallback_reason": "",
            "review_required": False,
            "score_breakdown": {
                "score_version": SCORE_VERSION,
                "model_category_type": model_category_type,
                "model_category_label": category_label,
                "model_reason": model_reason,
                "model_goal_relevance_level": float(model_goal_relevance),
                "model_task_evidence_level": float(model_task_evidence),
                "model_context_fit_level": float(model_context_fit),
                "model_distraction_level": float(model_distraction_level),
                "focus_home_guard_applied": float(focus_home_guard_applied),
                "goal_relevance_level": float(goal_relevance),
                "task_evidence_level": float(task_evidence),
                "context_fit_level": float(context_fit),
                "distraction_level": float(distraction_level),
                **calculated,
                "semantic_score": semantic_match_score,
                "strong_hit_score": strong_hit_score,
                "coverage_score": coverage_score,
                "keyword_hit_score": keyword_hit_score,
                "structure_score": structure_score,
                "app_context_score": app_context_score,
                "ocr_quality_score": ocr_quality,
                "base_relevance_score": relevance_score,
                "distraction_score": distraction_score,
                "confidence": confidence,
                "llm_scored": 1.0,
            },
        }

    @staticmethod
    def _validate_response(payload: Any) -> str:
        if not isinstance(payload, dict):
            return "顶层必须是 JSON 对象"

        missing = sorted(_REQUIRED_RESPONSE_FIELDS - set(payload))
        if missing:
            return f"缺少必填字段：{', '.join(missing)}"

        category = payload.get("category_type")
        if not isinstance(category, str) or category.strip().lower() not in {"focus", "neutral", "distract"}:
            return "category_type 必须是 focus、neutral 或 distract"
        category = category.strip().lower()

        for field_name in ("category_label", "reason"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return f"{field_name} 必须是非空字符串"

        for field_name in (
            "goal_relevance",
            "task_evidence",
            "context_fit",
            "distraction_level",
        ):
            value = payload.get(field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{field_name} 必须是 0-4 整数"
            number = float(value)
            if not math.isfinite(number) or not 0.0 <= number <= 4.0 or not number.is_integer():
                return f"{field_name} 必须是 0-4 整数"

        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return "confidence 必须是数字"
        confidence_number = float(confidence)
        if not math.isfinite(confidence_number) or not 0.0 <= confidence_number <= 1.0:
            return "confidence 必须在 0-1 范围内且为有限数"
        return ""

    def _review_result(self, message: str, ocr_quality: float) -> dict[str, Any]:
        return {
            "score_version": SCORE_VERSION,
            "ocr_text": "",
            "ocr_quality": round(clamp(ocr_quality), 3),
            "category_type": "neutral",
            "category_label": "待复核场景",
            "semantic_match_score": 0.0,
            "keyword_hit_score": 0.0,
            "strong_hit_score": 0.0,
            "coverage_score": 0.0,
            "structure_score": 0.0,
            "app_context_score": 0.0,
            "relevance_score": 0.0,
            "goal_relevance_score": None,
            "task_evidence_score": None,
            "context_fit_score": None,
            "distraction_score": None,
            "focus_score": 0.0,
            "focus_probability": 0.0,
            "confidence": 0.0,
            "status": "待复核",
            "matched_keywords": [],
            "strong_hits": [],
            "scene_hits": [],
            "support_hits": [],
            "negative_hits": [],
            "matched_context_patterns": [],
            "positive_rule": "",
            "negative_rule": "",
            "reason": message,
            "fallback_reason": message,
            "review_required": True,
            "cache_hit": False,
            "score_breakdown": {
                "score_version": SCORE_VERSION,
                "goal_relevance_level": None,
                "task_evidence_level": None,
                "context_fit_level": None,
                "distraction_level": None,
                "semantic_score": 0.0,
                "strong_hit_score": 0.0,
                "coverage_score": 0.0,
                "keyword_hit_score": 0.0,
                "structure_score": 0.0,
                "app_context_score": 0.0,
                "ocr_quality_score": round(clamp(ocr_quality), 3),
                "base_relevance_score": 0.0,
                "distraction_score": None,
                "confidence": 0.0,
                "llm_scored": 0.0,
            },
        }

    def _normalize_category(self, value: Any) -> str:
        text = str(value or "neutral").strip().lower()
        if text in {"focus", "study", "learning", "goal_related", "related"}:
            return "focus"
        if text in {"distract", "distraction", "distracting", "entertainment", "game", "social"}:
            return "distract"
        return "neutral"

    @staticmethod
    def _gate_category(
        category_type: str,
        goal_relevance: int,
        task_evidence: int,
        distraction_level: int,
    ) -> str:
        if category_type == "focus" and not (
            goal_relevance >= 3
            and task_evidence >= 2
            and distraction_level <= 1
        ):
            return "neutral"
        if category_type == "distract" and not (
            distraction_level >= 3 and goal_relevance <= 1
        ):
            return "neutral"
        return category_type

    def _normalize_status(self, category_type: str) -> str:
        if category_type == "focus":
            return "专注"
        if category_type == "distract":
            return "分心"
        return "轻微偏离"

    def _default_category_label(self, category_type: str) -> str:
        if category_type == "focus":
            return "目标相关场景"
        if category_type == "distract":
            return "明显分心场景"
        return "待确认场景"

    def _coerce_score(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if number > 1.0 and number <= 100.0:
            number = number / 100.0
        return round(clamp(number), 3)

    @staticmethod
    def _coerce_dimension_level(value: Any) -> int:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return 0
        return max(0, min(number, 4))

    def _coerce_focus_score(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(number, 100.0)), 1)

    def _coerce_list(self, value: Any, limit: int) -> list[str]:
        if isinstance(value, str):
            source = [value]
        elif isinstance(value, list):
            source = value
        else:
            source = []

        items: list[str] = []
        seen: set[str] = set()
        for raw in source:
            text = str(raw or "").strip()
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(text)
            if len(items) >= limit:
                break
        return items

    def generate_session_summary(self, goal: str, summary_stats: dict) -> str:
        """本地生成屏幕相关性总结（纯模板，无 API 调用）。"""
        try:
            focus_ratio = float(summary_stats.get("focus_ratio") or 0)
        except (TypeError, ValueError, OverflowError):
            focus_ratio = 0.0
        raw_average = summary_stats.get("avg_focus_score")
        try:
            avg_focus_score = float(raw_average) if raw_average is not None else None
        except (TypeError, ValueError, OverflowError):
            avg_focus_score = None
        top_context = str(summary_stats.get("top_context", "无"))
        top_distractor = str(summary_stats.get("top_distractor", "无"))
        focus_count = int(summary_stats.get("focus_count", 0))
        distract_count = int(summary_stats.get("distract_count", 0))

        if focus_ratio >= 80:
            encouragement = (
                "共享画面在大部分已观测时间里都与目标直接相关，可以继续沿用当前任务环境。"
            )
        elif focus_ratio >= 50:
            encouragement = (
                "共享画面整体以目标相关内容为主，中间存在一些不确定或偏离片段，可结合时间线自行复核。"
            )
        elif focus_ratio >= 30:
            encouragement = (
                "本轮目标相关画面占比较低。可先检查目标是否写得足够具体，以及共享范围是否包含任务主体。"
            )
        else:
            encouragement = (
                "本轮缺少足够的目标相关屏幕证据；这不等于你本人没有专注，建议结合原任务和截图质量判断。"
            )

        score_text = (
            f"平均画面相关度 {avg_focus_score:g}/100"
            if avg_focus_score is not None
            else "没有足够明确的画面用于计算平均相关度"
        )
        parts = [
            f'本次目标"{goal}"，目标相关画面占比 {focus_ratio:g}%，{score_text}。',
            f'最常见场景是"{top_context}"，共 {focus_count} 帧被判为目标相关。',
        ]
        if distract_count > 0 and top_distractor and top_distractor != "无":
            parts.append(f'主要无关场景是"{top_distractor}"，共 {distract_count} 帧被判为目标无关。')
        parts.append("")
        parts.append(encouragement)

        return "\n".join(parts)
