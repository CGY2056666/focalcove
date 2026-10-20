"""Optional, failure-isolated collection of screenshots for human evaluation."""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)

VALID_LABELS = frozenset({"focused", "uncertain", "distracted", "unscorable"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_SAMPLE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SCORING_RUBRIC_VERSION = "multidim-v1"
_HUMAN_DIMENSION_FIELDS = (
    "goal_relevance",
    "task_evidence",
    "context_fit",
    "distraction_level",
)


class EvaluationSampleCollector:
    """Store deduplicated, anonymous samples for later human review.

    ``enabled`` controls automatic collection only.  Pending samples can still
    be listed and labelled while collection is disabled.
    """

    def __init__(
        self,
        inbox_dir: str | Path,
        *,
        enabled: bool = False,
        provider: str = "",
        model: str = "",
        enabled_check: Callable[[], bool] | None = None,
        duplicate_distance_threshold: int = 6,
    ) -> None:
        self._enabled = bool(enabled)
        self._enabled_check = enabled_check
        self.inbox_dir = Path(inbox_dir).expanduser().resolve()
        self.screenshots_dir = (self.inbox_dir.parent / "screenshots").resolve()
        self.provider = str(provider or "")
        self.model = str(model or "")
        self.duplicate_distance_threshold = max(0, int(duplicate_distance_threshold))
        self._last_perceptual_hash: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        if not self._enabled:
            return False
        return bool(self._enabled_check()) if self._enabled_check is not None else True

    @staticmethod
    def _normalize_goal(goal: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(goal or ""))
        return " ".join(normalized.split()).casefold()

    @classmethod
    def _sample_id(cls, content_sha256: str, goal: str) -> str:
        identity = f"{content_sha256}\0{cls._normalize_goal(goal)}".encode("utf-8")
        return hashlib.sha256(identity).hexdigest()

    @staticmethod
    def _group_id(session_id: str) -> str:
        digest = hashlib.sha256(f"focus-eval-group:{session_id}".encode("utf-8")).hexdigest()
        return digest[:20]

    @staticmethod
    def _image_suffix(filename: str) -> str:
        suffix = Path(str(filename or "")).suffix.lower()
        return suffix if suffix in IMAGE_SUFFIXES else ".jpg"

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return number if number == number and abs(number) != float("inf") else default

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _optional_number(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number == number and abs(number) != float("inf") else None

    @classmethod
    def _human_annotation(
        cls,
        label: str,
        annotation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate optional multidimensional human scores.

        Keeping ``annotation`` optional preserves already-written class-only
        review tools.  Such rows are explicitly marked incomplete and the
        tuner will never treat them as continuous-score ground truth.
        """

        if annotation is None:
            return {
                "human_annotation_complete": False,
                "label_source": "human_review",
                "label_status": "human_class_only",
                "scoring_rubric_version": "legacy-v1",
            }
        if not isinstance(annotation, dict):
            raise ValueError("invalid_human_annotation")

        rubric_version = str(annotation.get("scoring_rubric_version") or "").strip()
        if rubric_version != SCORING_RUBRIC_VERSION:
            raise ValueError("invalid_scoring_rubric_version")

        if label == "unscorable":
            return {
                "human_annotation_complete": False,
                "label_source": "human_review",
                "label_status": "human_class_only",
                "scoring_rubric_version": rubric_version,
                "human_goal_relevance": None,
                "human_task_evidence": None,
                "human_context_fit": None,
                "human_distraction_level": None,
                "human_overall_score": None,
                "annotation_confidence": None,
            }

        dimensions: dict[str, int] = {}
        for field in _HUMAN_DIMENSION_FIELDS:
            value = annotation.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4:
                raise ValueError(f"invalid_{field}")
            dimensions[field] = value

        overall = annotation.get("overall_score")
        if isinstance(overall, bool) or not isinstance(overall, int) or not 0 <= overall <= 10:
            raise ValueError("invalid_overall_score")
        confidence = cls._optional_number(annotation.get("annotation_confidence"))
        if confidence is None or not 0.0 <= confidence <= 1.0:
            raise ValueError("invalid_annotation_confidence")

        return {
            "human_annotation_complete": True,
            "label_source": "human_review",
            "label_status": "human_continuous_ground_truth",
            "scoring_rubric_version": rubric_version,
            "human_goal_relevance": dimensions["goal_relevance"],
            "human_task_evidence": dimensions["task_evidence"],
            "human_context_fit": dimensions["context_fit"],
            "human_distraction_level": dimensions["distraction_level"],
            "human_overall_score": overall,
            "annotation_confidence": round(confidence, 4),
        }

    @staticmethod
    def _hash_distance(left: str, right: str) -> int | None:
        left_value = str(left or "").strip().lower()
        right_value = str(right or "").strip().lower()
        if not left_value or len(left_value) != len(right_value):
            return None
        try:
            return (int(left_value, 16) ^ int(right_value, 16)).bit_count()
        except ValueError:
            return None

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            if os.name == "posix":
                os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    @classmethod
    def _atomic_json(cls, path: Path, payload: dict[str, Any]) -> None:
        cls._atomic_write(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    @staticmethod
    def _safe_child(directory: Path, filename: str) -> Path:
        root = directory.resolve()
        candidate = (root / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("path_outside_collection_directory") from exc
        return candidate

    @staticmethod
    def _validate_sample_id(sample_id: str) -> str:
        value = str(sample_id or "").strip().lower()
        if not _SAMPLE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid_sample_id")
        return value

    def _labelled_metadata_path(self, sample_id: str) -> Path | None:
        for label in sorted(VALID_LABELS):
            candidate = self._safe_child(self.screenshots_dir / label, f"{sample_id}.json")
            if candidate.exists():
                return candidate
        return None

    def collect(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        session_id: str,
        goal: str,
        captured_at: Any,
        frame_result: dict[str, Any] | None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any] | None:
        """Collect one sample, returning metadata or ``None`` when disabled."""

        if not self.enabled:
            return None
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise ValueError("empty_evaluation_image")

        raw = dict(frame_result or {})
        if str(raw.get("source") or "").lower() == "reuse" or raw.get("duplicate_of"):
            return None
        content_sha256 = hashlib.sha256(bytes(image_bytes)).hexdigest()
        sample_id = self._sample_id(content_sha256, goal)
        suffix = self._image_suffix(filename)
        suggested_state = str(raw.get("raw_state") or raw.get("state") or "unscorable").lower()
        if suggested_state not in VALID_LABELS:
            suggested_state = "unscorable"
        raw_confidence = raw.get("raw_confidence")
        if raw_confidence is None:
            raw_confidence = raw.get("confidence", raw.get("score_confidence", 0.0))
        score_version = str(raw.get("score_version") or "legacy-v1")
        raw_focus_score = raw.get("raw_focus_score")
        if raw_focus_score is None and score_version != SCORING_RUBRIC_VERSION:
            raw_focus_score = raw.get("focus_score", 0.0)
        raw_distraction_score = raw.get("raw_distraction_score")
        if raw_distraction_score is None and score_version != SCORING_RUBRIC_VERSION:
            raw_distraction_score = raw.get("distraction_score", 0.0)
        raw_focus_score = self._optional_number(raw_focus_score)
        raw_distraction_score = self._optional_number(raw_distraction_score)
        goal_relevance_score = self._optional_number(raw.get("goal_relevance_score"))
        task_evidence_score = self._optional_number(raw.get("task_evidence_score"))
        context_fit_score = self._optional_number(raw.get("context_fit_score"))
        source_provider = str(raw.get("provider") or raw.get("source") or "").strip()
        if source_provider.lower() in {"", "reuse", "timeout", "fallback", "local"}:
            source_provider = ""
        anonymous_group = self._group_id(str(session_id or "anonymous"))
        normalized_goal = self._normalize_goal(goal)
        perceptual_hash = str(raw.get("thumbnail_hash") or "").strip().lower()
        perceptual_key = (anonymous_group, normalized_goal)
        model_reason = str(
            raw.get("base_decision_reason")
            or raw.get("decision_reason")
            or raw.get("reason")
            or raw.get("fallback_reason")
            or ""
        ).strip()[:500]

        with self._lock:
            labelled = self._labelled_metadata_path(sample_id)
            if labelled is not None:
                if perceptual_hash:
                    self._last_perceptual_hash[perceptual_key] = perceptual_hash
                return json.loads(labelled.read_text(encoding="utf-8"))

            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = self._safe_child(self.inbox_dir, f"{sample_id}.json")
            if metadata_path.exists():
                existing = json.loads(metadata_path.read_text(encoding="utf-8"))
                existing_image_name = str(existing.get("image_file") or "")
                existing_image_path = self._safe_child(self.inbox_dir, existing_image_name)
                if existing_image_path.stem != sample_id:
                    raise ValueError("sample_id_mismatch")
                if not existing_image_path.exists():
                    self._atomic_write(existing_image_path, bytes(image_bytes))
                if perceptual_hash:
                    self._last_perceptual_hash[perceptual_key] = perceptual_hash
                return existing


            previous_hash = self._last_perceptual_hash.get(perceptual_key, "")
            distance = self._hash_distance(previous_hash, perceptual_hash)
            if distance is not None and distance <= self.duplicate_distance_threshold:
                return None

            image_name = f"{sample_id}{suffix}"
            image_path = self._safe_child(self.inbox_dir, image_name)
            metadata = {
                "sample_id": sample_id,
                "content_sha256": content_sha256,
                "image_file": image_name,
                "group_id": anonymous_group,
                "source_group": anonymous_group,
                "sequence_id": anonymous_group,
                "sequence_index": self._integer(raw.get("index")),
                "perceptual_group": str(raw.get("thumbnail_hash") or "").strip(),
                "goal": str(goal or ""),
                "captured_at": self._number(captured_at),
                "provider": str(provider or source_provider or self.provider),
                "model": str(model or raw.get("model") or self.model),
                "suggested_state": suggested_state,
                "model_reason": model_reason,
                "raw_category": str(raw.get("raw_category") or raw.get("category_type") or "neutral"),
                "confidence": round(self._number(raw_confidence), 4),
                "raw_focus_score": (
                    round(raw_focus_score, 4) if raw_focus_score is not None else None
                ),
                "raw_distraction_score": (
                    round(raw_distraction_score, 4)
                    if raw_distraction_score is not None
                    else None
                ),
                "score_version": score_version,
                "goal_relevance_score": (
                    round(goal_relevance_score, 4) if goal_relevance_score is not None else None
                ),
                "task_evidence_score": (
                    round(task_evidence_score, 4) if task_evidence_score is not None else None
                ),
                "context_fit_score": (
                    round(context_fit_score, 4) if context_fit_score is not None else None
                ),
                "reviewed": False,
                "human_review": False,
                "created_at": time.time(),
            }
            self._atomic_write(image_path, bytes(image_bytes))
            try:
                self._atomic_json(metadata_path, metadata)
            except Exception:
                image_path.unlink(missing_ok=True)
                raise
            if perceptual_hash:
                self._last_perceptual_hash[perceptual_key] = perceptual_hash
            return dict(metadata)

    def list_pending(self) -> list[dict[str, Any]]:
        """Return pending metadata, oldest first; corrupt entries are skipped."""

        if not self.inbox_dir.exists():
            return []
        pending: list[dict[str, Any]] = []
        with self._lock:
            for path in self.inbox_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    sample_id = self._validate_sample_id(str(payload.get("sample_id") or path.stem))
                    image_file = str(payload.get("image_file") or "")
                    if sample_id != path.stem or not image_file:
                        continue
                    image_path = self._safe_child(self.inbox_dir, image_file)
                    if image_path.exists() and not payload.get("reviewed"):
                        pending.append(payload)
                except (OSError, ValueError, json.JSONDecodeError):
                    logger.warning("跳过损坏的评测样本元数据：%s", path.name)
        return sorted(pending, key=lambda item: self._number(item.get("created_at")))

    def open_image(self, sample_id: str) -> tuple[bytes, str]:
        """Return pending image bytes and MIME type without exposing a path."""

        resolved_id = self._validate_sample_id(sample_id)
        with self._lock:
            metadata_path = self._safe_child(self.inbox_dir, f"{resolved_id}.json")
            if not metadata_path.exists():
                raise FileNotFoundError("evaluation_sample_not_found")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if str(metadata.get("sample_id") or "") != resolved_id:
                raise ValueError("sample_id_mismatch")
            image_name = str(metadata.get("image_file") or "")
            image_path = self._safe_child(self.inbox_dir, image_name)
            if not image_path.exists() or image_path.stem != resolved_id:
                raise FileNotFoundError("evaluation_image_not_found")
            mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
            return image_path.read_bytes(), mime_type

    def discard_sample(self, sample_id: str) -> bool:
        """Delete one pending sample only; labelled datasets are never touched."""

        resolved_id = self._validate_sample_id(sample_id)
        with self._lock:
            metadata_path = self._safe_child(self.inbox_dir, f"{resolved_id}.json")
            candidates: set[Path] = {
                self._safe_child(self.inbox_dir, f"{resolved_id}{suffix}")
                for suffix in IMAGE_SUFFIXES
            }
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    image_name = str(metadata.get("image_file") or "")
                    image_path = self._safe_child(self.inbox_dir, image_name)
                    if image_path.stem == resolved_id:
                        candidates.add(image_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    # 人工排除敏感样本时，即使元数据已损坏，也删除 inbox 中的精确 hash 文件。
                    pass

            removed = False
            for image_path in candidates:
                if image_path.exists():
                    image_path.unlink()
                    removed = True
            if metadata_path.exists():
                metadata_path.unlink()
                removed = True
            return removed

    def label_sample(
        self,
        sample_id: str,
        label: str,
        *,
        annotation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Move a pending sample into the human-labelled dataset."""

        resolved_id = self._validate_sample_id(sample_id)
        resolved_label = str(label or "").strip().lower()
        if resolved_label not in VALID_LABELS:
            raise ValueError("invalid_evaluation_label")
        human_annotation = self._human_annotation(resolved_label, annotation)

        with self._lock:
            existing = self._labelled_metadata_path(resolved_id)
            if existing is not None:
                payload = json.loads(existing.read_text(encoding="utf-8"))
                if payload.get("human_label") == resolved_label:
                    # 元数据先落盘、图片后落盘；若进程曾在两步之间中断，幂等重试补齐图片。
                    image_name = str(payload.get("image_file") or "")
                    destination_image = self._safe_child(existing.parent, image_name)
                    if not destination_image.exists():
                        pending_metadata = self._safe_child(
                            self.inbox_dir,
                            f"{resolved_id}.json",
                        )
                        if not pending_metadata.exists():
                            raise FileNotFoundError("evaluation_image_not_found")
                        pending = json.loads(pending_metadata.read_text(encoding="utf-8"))
                        source_image = self._safe_child(
                            self.inbox_dir,
                            str(pending.get("image_file") or ""),
                        )
                        if not source_image.exists() or source_image.stem != resolved_id:
                            raise FileNotFoundError("evaluation_image_not_found")
                        self._atomic_write(destination_image, source_image.read_bytes())
                    # 上次若在目标文件落盘后、清理 inbox 前中断，幂等重试负责收尾。
                    self.discard_sample(resolved_id)
                    return payload
                raise ValueError("sample_already_labelled")

            metadata_path = self._safe_child(self.inbox_dir, f"{resolved_id}.json")
            if not metadata_path.exists():
                raise FileNotFoundError("evaluation_sample_not_found")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if str(metadata.get("sample_id") or "") != resolved_id:
                raise ValueError("sample_id_mismatch")

            image_name = str(metadata.get("image_file") or "")
            source_image = self._safe_child(self.inbox_dir, image_name)
            if not source_image.exists() or source_image.stem != resolved_id:
                raise FileNotFoundError("evaluation_image_not_found")

            destination_dir = (self.screenshots_dir / resolved_label).resolve()
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination_image = self._safe_child(destination_dir, image_name)
            destination_metadata = self._safe_child(destination_dir, f"{resolved_id}.json")
            reviewed = dict(metadata)
            reviewed.update(
                {
                    "reviewed": True,
                    "human_review": True,
                    "human_label": resolved_label,
                    "expected_state": resolved_label,
                    "reviewed_at": time.time(),
                    **human_annotation,
                }
            )

            # 先写 sidecar，再发布图片；manifest 只扫描图片，因此崩溃不会把无元数据
            # 的半成品误当成人工真值。重试路径会从 inbox 恢复缺失的目标图片。
            self._atomic_json(destination_metadata, reviewed)
            try:
                self._atomic_write(destination_image, source_image.read_bytes())
            except Exception:
                destination_metadata.unlink(missing_ok=True)
                raise
            source_image.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            return reviewed
