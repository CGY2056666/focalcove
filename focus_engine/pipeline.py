from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace

import numpy as np

from .config import AnalyzerConfig, DEFAULT_CONFIG
from .goal_profiles import build_goal_profile
from .models import FrameAnalysis, GoalProfile
from .image_utils import average_hash, decode_image, hash_distance
from .scoring import build_summary, finalize_frame_scores, clean_ocr_text, score_ocr_quality
from .scoring_policy import load_scoring_policy
from .vision_provider import create_vision_scorer
from .utils import normalize_text
from typing import Any


def is_protected_blank_image(image: np.ndarray | None) -> bool:
    """Conservatively detect near-black protected-content frames.

    The center crop excludes system bars. Requiring both very low luminance and
    very low variance avoids treating ordinary dark-theme screens as blank.
    """
    if image is None or image.size == 0 or image.ndim < 2:
        return False
    height, width = image.shape[:2]
    top, bottom = int(height * 0.08), max(int(height * 0.92), 1)
    left, right = int(width * 0.08), max(int(width * 0.92), 1)
    center = image[top:bottom, left:right]
    if center.size == 0:
        center = image
    if center.ndim == 3:
        luminance = center.astype(np.float32).mean(axis=2)
    else:
        luminance = center.astype(np.float32)
    return bool(float(luminance.mean()) <= 5.0 and float(luminance.std()) <= 2.5)


@dataclass
class PreparedFrame:
    index: int
    filename: str
    image_valid: bool
    image: np.ndarray | None = None
    width: int = 0
    height: int = 0
    thumbnail_hash: str = ""
    duplicate_of: int | None = None
    protected_blank: bool = False


class FocusAnalyzer:
    def __init__(self, config: AnalyzerConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.vlm = create_vision_scorer(config)
        policy_result = load_scoring_policy(config.scoring_policy_path)
        self.scoring_policy = policy_result.policy
        self.scoring_policy_source = policy_result.source
        self.scoring_policy_error = policy_result.error

    def vision_ready_message(self) -> tuple[bool, str]:
        return self.vlm.vision_ready_message()

    def scoring_status(self) -> dict[str, Any]:
        status = dict(self.vlm.status())
        status.update(
            {
                "scoring_policy_source": self.scoring_policy_source,
                "scoring_policy_error": self.scoring_policy_error,
                "scoring_policy": self.scoring_policy.to_dict(),
            }
        )
        return status

    def allowed_file(self, filename: str) -> bool:
        return filename.lower().endswith(self.config.supported_extensions)

    def analyze_uploads(self, goal: str, uploads: list[tuple[str, bytes]]) -> dict:
        profile, items, summary = self.analyze_objects(goal, uploads)
        ready, engine = self.vision_ready_message()
        scoring = self.scoring_status()
        return {
            "goal_profile": profile.to_dict(),
            "summary": summary,
            "items": [item.to_dict() for item in items],
            "runtime": {
                "ocr_ready": ready,
                "ocr_engine": engine,
                "workers": self.config.max_workers,
                "llm_ready": bool(scoring["configured"]),
                "llm_provider": str(scoring["provider"]),
                "llm_model": str(scoring["model"]),
            },
        }

    def analyze_objects(self, goal: str, uploads: list[tuple[str, bytes]]) -> tuple[GoalProfile, list[FrameAnalysis], dict]:
        started = time.perf_counter()
        # 这里用到goal_profiles！！
        profile = build_goal_profile(goal)
        prepared = self._prepare_frames(uploads[: self.config.max_uploads])
        analyzed = self._analyze_prepared_frames(profile, prepared)
        finalize_frame_scores(analyzed, policy=self.scoring_policy)
        summary = build_summary(profile, analyzed, int((time.perf_counter() - started) * 1000))
        return profile, analyzed, summary

    def analyze_frame(
        self,
        profile: GoalProfile,
        filename: str,
        file_bytes: bytes,
        *,
        frame_id: str = "",
        captured_at: float | None = None,
        previous_frame: FrameAnalysis | None = None,
        last_model_analysis_at: float | None = None,
    ) -> FrameAnalysis:
        captured_at = float(captured_at or time.time())
        prepared = self._prepare_frames([(filename, file_bytes)])
        frame = prepared[0]
        if not frame.image_valid:
            return FrameAnalysis(
                index=0,
                filename=filename,
                image_valid=False,
                frame_id=frame_id,
                captured_at=captured_at,
                processed_at=time.time(),
                state="unscorable",
                source="decode_error",
                status="无法分析",
                decision_reason="图片无法解码，请重新共享更清晰的窗口后再试。",
            )
        if frame.protected_blank:
            analyzed = self._analyze_unique_frame(profile, frame)
            analyzed.frame_id = frame_id
            analyzed.captured_at = captured_at
            analyzed.processed_at = time.time()
            return analyzed

        near_duplicate = (
            previous_frame is not None
            and previous_frame.image_valid
            and previous_frame.state != "unscorable"
            and previous_frame.thumbnail_hash
            and hash_distance(frame.thumbnail_hash, previous_frame.thumbnail_hash)
            <= self.config.duplicate_distance_threshold
        )
        can_reuse = (
            near_duplicate
            and last_model_analysis_at is not None
            and captured_at - last_model_analysis_at <= self.config.duplicate_recheck_seconds
        )
        if can_reuse:
            return replace(
                previous_frame,
                index=0,
                filename=filename,
                frame_id=frame_id,
                captured_at=captured_at,
                processed_at=time.time(),
                width=frame.width,
                height=frame.height,
                thumbnail_hash=frame.thumbnail_hash,
                duplicate_of=previous_frame.filename,
                cache_hit=True,
                source="reuse",
                scoring_source="reuse",
                processing_ms=1,
                fallback_reason="与上一帧高度相似，复用最近一次有效评分。",
                score_breakdown=dict(previous_frame.score_breakdown),
                matched_keywords=list(previous_frame.matched_keywords),
                strong_hits=list(previous_frame.strong_hits),
                scene_hits=list(previous_frame.scene_hits),
                support_hits=list(previous_frame.support_hits),
                negative_hits=list(previous_frame.negative_hits),
                matched_context_patterns=list(previous_frame.matched_context_patterns),
            )

        force_model_refresh = bool(
            near_duplicate
            and last_model_analysis_at is not None
            and captured_at - last_model_analysis_at > self.config.duplicate_recheck_seconds
        )
        analyzed = self._analyze_unique_frame(
            profile,
            frame,
            force_model_refresh=force_model_refresh,
        )
        analyzed.frame_id = frame_id
        analyzed.captured_at = captured_at
        analyzed.processed_at = time.time()
        if analyzed.source != "protected_content":
            analyzed.source = str(self.vlm.status().get("provider") or "vision_model")
        return analyzed

    def _prepare_frames(self, uploads: list[tuple[str, bytes]]) -> list[PreparedFrame]:
        prepared: list[PreparedFrame] = []
        last_unique: PreparedFrame | None = None

        for index, (filename, file_bytes) in enumerate(uploads):
            image = decode_image(file_bytes)
            if image is None:
                prepared.append(PreparedFrame(index=index, filename=filename, image_valid=False))
                continue

            height, width = image.shape[:2]
            thumbnail_hash = average_hash(image, self.config.thumbnail_hash_size)
            duplicate_of = None
            protected_blank = is_protected_blank_image(image)

            if (
                not protected_blank
                and last_unique
                and hash_distance(thumbnail_hash, last_unique.thumbnail_hash)
                <= self.config.duplicate_distance_threshold
            ):
                duplicate_of = last_unique.index

            frame = PreparedFrame(
                index=index,
                filename=filename,
                image_valid=True,
                image=image,
                width=width,
                height=height,
                thumbnail_hash=thumbnail_hash,
                duplicate_of=duplicate_of,
                protected_blank=protected_blank,
            )
            prepared.append(frame)
            if duplicate_of is None and not protected_blank:
                last_unique = frame

        return prepared

    def _analyze_prepared_frames(self, profile: GoalProfile, prepared: list[PreparedFrame]) -> list[FrameAnalysis]:
        by_index: dict[int, FrameAnalysis] = {}
        unique_frames = [frame for frame in prepared if frame.image_valid and frame.duplicate_of is None]

        if unique_frames:
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                futures = {
                    executor.submit(self._analyze_unique_frame, profile, frame): frame.index
                    for frame in unique_frames
                }
                for future in as_completed(futures):
                    frame_index = futures[future]
                    by_index[frame_index] = future.result()

        items: list[FrameAnalysis] = []
        for frame in prepared:
            if not frame.image_valid:
                items.append(
                    FrameAnalysis(
                        index=frame.index,
                        filename=frame.filename,
                        image_valid=False,
                        status="无法分析",
                        decision_reason="图片无法解码，请重新上传更完整的截图。",
                    )
                )
                continue

            if frame.duplicate_of is not None and frame.duplicate_of in by_index:
                source = by_index[frame.duplicate_of]
                clone = replace(
                    source,
                    index=frame.index,
                    filename=frame.filename,
                    duplicate_of=source.filename,
                    cache_hit=True,
                    source="reuse",
                    scoring_source="reuse",
                    processing_ms=1,
                    fallback_reason="与上一张截图高度相似，已复用识别和评分结果。",
                )
                items.append(clone)
                continue

            items.append(by_index[frame.index])

        return items

    def _analyze_unique_frame(
        self,
        profile: GoalProfile,
        frame: PreparedFrame,
        *,
        force_model_refresh: bool = False,
    ) -> FrameAnalysis:
        assert frame.image is not None
        started = time.perf_counter()
        if frame.protected_blank or is_protected_blank_image(frame.image):
            reason = (
                "画面近乎全黑，可能由系统安全窗口保护产生；本帧仅降低有效覆盖率，"
                "不判定为分心。"
            )
            return FrameAnalysis(
                index=frame.index,
                filename=frame.filename,
                image_valid=True,
                processed_at=time.time(),
                state="unscorable",
                source="protected_content",
                width=frame.width,
                height=frame.height,
                thumbnail_hash=frame.thumbnail_hash,
                category_label="受保护或空白画面",
                category_type="neutral",
                status="待复核",
                decision_reason=reason,
                base_decision_reason=reason,
                fallback_reason=reason,
                warning=reason,
                scoring_source="protected_content",
                review_required=True,
                used_fallback=True,
                processing_ms=max(1, int((time.perf_counter() - started) * 1000)),
            )
        if force_model_refresh:
            merged = self.vlm.analyze(
                profile,
                frame.filename,
                frame.image,
                frame.thumbnail_hash,
                bypass_cache=True,
            )
        else:
            merged = self.vlm.analyze(profile, frame.filename, frame.image, frame.thumbnail_hash)

        # 模型失败时保留待复核结果；不再制造没有视觉证据的本地分数。
        review_required = bool(merged.get("review_required"))

        ocr_text = str(merged.get("ocr_text") or "")
        ocr_quality = float(merged.get("ocr_quality") or 0.0)
        llm_cache_hit = bool(merged.get("cache_hit"))

        fallback_reason = str(merged.get("fallback_reason") or "")

        elapsed = max(int((time.perf_counter() - started) * 1000), int(merged["score_breakdown"].get("llm_latency_ms", 0) or 0))

        return FrameAnalysis(
            index=frame.index,
            filename=frame.filename,
            image_valid=True,
            processed_at=time.time(),
            state="unscorable" if review_required else "uncertain",
            score_version=str(merged.get("score_version") or "legacy-v1"),
            source=str(self.vlm.status().get("provider") or "vision_model"),
            width=frame.width,
            height=frame.height,
            thumbnail_hash=frame.thumbnail_hash,
            ocr_text=ocr_text,
            ocr_quality_score=ocr_quality,
            semantic_match_score=float(merged["semantic_match_score"]),
            keyword_hit_score=float(merged["keyword_hit_score"]),
            strong_hit_score=float(merged["strong_hit_score"]),
            coverage_score=float(merged["coverage_score"]),
            structure_score=float(merged["structure_score"]),
            app_context_score=float(merged["app_context_score"]),
            base_relevance_score=float(merged["relevance_score"]),
            relevance_score=float(merged["relevance_score"]),
            goal_relevance_score=(
                float(merged["goal_relevance_score"])
                if merged.get("goal_relevance_score") is not None
                else None
            ),
            task_evidence_score=(
                float(merged["task_evidence_score"])
                if merged.get("task_evidence_score") is not None
                else None
            ),
            context_fit_score=(
                float(merged["context_fit_score"])
                if merged.get("context_fit_score") is not None
                else None
            ),
            focus_score=float(merged["focus_score"]),
            focus_probability=float(merged["focus_probability"]),
            score_confidence=float(merged["confidence"]),
            distraction_score=(
                float(merged["distraction_score"])
                if merged.get("distraction_score") is not None
                else None
            ),
            category_label=str(merged["category_label"]),
            category_type=str(merged["category_type"]),
            matched_keywords=list(merged["matched_keywords"]),
            strong_hits=list(merged["strong_hits"]),
            scene_hits=list(merged["scene_hits"]),
            support_hits=list(merged["support_hits"]),
            negative_hits=list(merged["negative_hits"]),
            matched_context_patterns=list(merged["matched_context_patterns"]),
            status=str(merged["status"]),
            decision_reason=str(merged["reason"]),
            base_decision_reason=str(merged["reason"]),
            cache_hit=llm_cache_hit,
            used_fallback=review_required,
            processing_ms=elapsed,
            warning=None,
            fallback_reason=fallback_reason,
            positive_rule=str(merged["positive_rule"]),
            negative_rule=str(merged["negative_rule"]),
            score_breakdown=dict(merged["score_breakdown"]),
            scoring_source="fallback" if review_required else str(self.vlm.status().get("provider") or "vision_model"),
            review_required=review_required,
        )
