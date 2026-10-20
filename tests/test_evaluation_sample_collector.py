from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.evaluation_sample_collector import EvaluationSampleCollector
from app.services.focus_session_service import FocusSessionService


def _frame(**updates):
    payload = {
        "index": 3,
        "captured_at": 1234.5,
        "state": "distracted",
        "raw_state": "focused",
        "confidence": 0.42,
        "raw_confidence": 0.83,
        "raw_category": "relevant",
        "focus_score": 44,
        "raw_focus_score": 88,
        "distraction_score": 0.7,
        "raw_distraction_score": 0.08,
        "score_version": "multidim-v1",
        "goal_relevance_score": 75,
        "task_evidence_score": 50,
        "context_fit_score": 100,
        "decision_reason": "截图正在编辑 Python 测试代码",
        "source": "siliconflow",
        "thumbnail_hash": "perceptual-hash",
        "duplicate_of": None,
    }
    payload.update(updates)
    return payload


def _collector(tmp_path, **kwargs):
    return EvaluationSampleCollector(
        tmp_path / "evaluation" / "inbox",
        enabled=True,
        provider="siliconflow",
        model="Qwen/Qwen3.6-35B-A3B",
        **kwargs,
    )


def test_collection_is_disabled_by_default_and_can_be_dynamically_disabled(tmp_path):
    inbox = tmp_path / "evaluation" / "inbox"
    disabled = EvaluationSampleCollector(inbox)
    assert disabled.collect(
        image_bytes=b"image",
        filename="screen.jpg",
        session_id="session",
        goal="学习",
        captured_at=1,
        frame_result=_frame(),
    ) is None
    assert not inbox.exists()

    runtime = {"testing": False}
    dynamic = EvaluationSampleCollector(
        inbox,
        enabled=True,
        enabled_check=lambda: not runtime["testing"],
    )
    assert dynamic.enabled is True
    runtime["testing"] = True
    assert dynamic.enabled is False
    assert dynamic.collect(
        image_bytes=b"image",
        filename="screen.jpg",
        session_id="session",
        goal="学习",
        captured_at=1,
        frame_result=_frame(),
    ) is None
    assert not inbox.exists()


def test_collects_anonymous_raw_first_metadata_and_opens_image(tmp_path):
    collector = _collector(tmp_path)
    image_bytes = b"fake-jpeg-content"
    result = collector.collect(
        image_bytes=image_bytes,
        filename="screen.jpg",
        session_id="secret-session-id",
        goal="学习 Python",
        captured_at=1234.5,
        frame_result=_frame(),
    )

    content_sha256 = hashlib.sha256(image_bytes).hexdigest()
    sample_id = collector._sample_id(content_sha256, "学习 Python")
    assert result is not None
    assert result["sample_id"] == sample_id
    assert result["content_sha256"] == content_sha256
    assert result["suggested_state"] == "focused"
    assert result["confidence"] == 0.83
    assert result["raw_focus_score"] == 88
    assert result["raw_distraction_score"] == 0.08
    assert result["score_version"] == "multidim-v1"
    assert result["goal_relevance_score"] == 75
    assert result["task_evidence_score"] == 50
    assert result["context_fit_score"] == 100
    assert result["model_reason"] == "截图正在编辑 Python 测试代码"
    assert result["source_group"] == result["sequence_id"] == result["group_id"]
    assert result["sequence_index"] == 3
    assert result["perceptual_group"] == "perceptual-hash"
    assert result["reviewed"] is False
    assert result["human_review"] is False
    assert "username" not in result

    metadata_text = (collector.inbox_dir / f"{sample_id}.json").read_text(encoding="utf-8")
    assert "secret-session-id" not in metadata_text
    assert json.loads(metadata_text) == result
    opened, mime_type = collector.open_image(sample_id)
    assert opened == image_bytes
    assert mime_type == "image/jpeg"


def test_unscorable_multidimensional_scores_remain_null_in_metadata(tmp_path):
    collector = _collector(tmp_path)
    result = collector.collect(
        image_bytes=b"unscorable-image",
        filename="screen.jpg",
        session_id="session",
        goal="学习 Python",
        captured_at=1234.5,
        frame_result=_frame(
            state="unscorable",
            raw_state="unscorable",
            focus_score=0,
            raw_focus_score=None,
            distraction_score=None,
            raw_distraction_score=None,
            goal_relevance_score=None,
            task_evidence_score=None,
            context_fit_score=None,
        ),
    )

    assert result is not None
    assert result["raw_focus_score"] is None
    assert result["raw_distraction_score"] is None
    assert result["goal_relevance_score"] is None
    assert result["task_evidence_score"] is None
    assert result["context_fit_score"] is None


def test_deduplicates_by_content_and_normalized_goal_and_keeps_other_goals(tmp_path):
    collector = _collector(tmp_path)
    first = collector.collect(
        image_bytes=b"same-image",
        filename="first.jpg",
        session_id="session-a",
        goal="目标",
        captured_at=1,
        frame_result=_frame(),
    )
    second = collector.collect(
        image_bytes=b"same-image",
        filename="second.png",
        session_id="session-b",
        goal="  目标  ",
        captured_at=2,
        frame_result=_frame(),
    )
    assert first == second

    other_goal = collector.collect(
        image_bytes=b"same-image",
        filename="third.jpg",
        session_id="session-c",
        goal="另一个目标",
        captured_at=2,
        frame_result=_frame(),
    )
    assert other_goal is not None
    assert first is not None
    assert other_goal["sample_id"] != first["sample_id"]
    assert other_goal["content_sha256"] == first["content_sha256"]
    assert len(list(collector.inbox_dir.iterdir())) == 4

    assert collector.collect(
        image_bytes=b"reused-image",
        filename="reuse.jpg",
        session_id="session",
        goal="目标",
        captured_at=3,
        frame_result=_frame(source="reuse"),
    ) is None
    assert collector.collect(
        image_bytes=b"near-duplicate",
        filename="duplicate.jpg",
        session_id="session",
        goal="目标",
        captured_at=4,
        frame_result=_frame(duplicate_of="older-frame"),
    ) is None
    assert len(collector.list_pending()) == 2


def test_label_retry_recovers_partial_destination_and_cleans_inbox(tmp_path):
    collector = _collector(tmp_path)
    pending = collector.collect(
        image_bytes=b"partial-label-image",
        filename="partial.jpg",
        session_id="session",
        goal="目标",
        captured_at=1,
        frame_result=_frame(),
    )
    assert pending is not None
    sample_id = pending["sample_id"]
    destination = collector.screenshots_dir / "focused"
    destination.mkdir(parents=True)
    reviewed = dict(
        pending,
        reviewed=True,
        human_review=True,
        human_label="focused",
        expected_state="focused",
    )
    collector._atomic_json(destination / f"{sample_id}.json", reviewed)

    result = collector.label_sample(sample_id, "focused")

    assert result["human_label"] == "focused"
    assert (destination / pending["image_file"]).read_bytes() == b"partial-label-image"
    assert not (collector.inbox_dir / f"{sample_id}.json").exists()
    assert collector.list_pending() == []


def test_session_goal_perceptual_hash_skips_near_duplicate_candidates(tmp_path):
    collector = _collector(tmp_path)
    first = collector.collect(
        image_bytes=b"perceptual-first",
        filename="first.jpg",
        session_id="session-a",
        goal="目标",
        captured_at=1,
        frame_result=_frame(thumbnail_hash="0000000000000000"),
    )
    near = collector.collect(
        image_bytes=b"perceptual-near",
        filename="near.jpg",
        session_id="session-a",
        goal=" 目标 ",
        captured_at=2,
        frame_result=_frame(thumbnail_hash="0000000000000001"),
    )
    other_goal = collector.collect(
        image_bytes=b"perceptual-other-goal",
        filename="other.jpg",
        session_id="session-a",
        goal="另一个目标",
        captured_at=3,
        frame_result=_frame(thumbnail_hash="0000000000000001"),
    )

    assert first is not None
    assert near is None
    assert other_goal is not None


def test_relative_evaluation_directory_resolves_from_project_root(monkeypatch):
    from focus_engine import config as config_module

    monkeypatch.setenv("FOCUS_EVAL_CAPTURE_DIR", "evaluation/custom-inbox")

    resolved = Path(
        config_module._env_path(
            "FOCUS_EVAL_CAPTURE_DIR",
            config_module._DEFAULT_EVAL_CAPTURE_DIR,
        )
    )

    assert resolved == (config_module._ENV_FILE.parent / "evaluation/custom-inbox").resolve()
    assert resolved.is_absolute()


def test_list_label_discard_and_path_safety(tmp_path, monkeypatch):
    from app.services import evaluation_sample_collector as module

    ticks = iter([20.0, 10.0, 30.0, 40.0])
    monkeypatch.setattr(module.time, "time", lambda: next(ticks))
    collector = _collector(tmp_path)
    first = collector.collect(
        image_bytes=b"first",
        filename="first.jpg",
        session_id="session",
        goal="目标",
        captured_at=1,
        frame_result=_frame(),
    )
    second = collector.collect(
        image_bytes=b"second",
        filename="second.png",
        session_id="session",
        goal="目标",
        captured_at=2,
        frame_result=_frame(),
    )
    assert first is not None and second is not None
    assert [item["sample_id"] for item in collector.list_pending()] == [
        second["sample_id"],
        first["sample_id"],
    ]

    reviewed = collector.label_sample(first["sample_id"], "focused")
    destination = collector.screenshots_dir / "focused"
    assert reviewed["reviewed"] is True
    assert reviewed["human_review"] is True
    assert reviewed["human_label"] == reviewed["expected_state"] == "focused"
    assert (destination / f"{first['sample_id']}.json").exists()
    assert (destination / first["image_file"]).exists()
    assert not (collector.inbox_dir / f"{first['sample_id']}.json").exists()
    assert collector.label_sample(first["sample_id"], "focused") == reviewed
    with pytest.raises(ValueError, match="sample_already_labelled"):
        collector.label_sample(first["sample_id"], "distracted")

    # 丢弃只作用于 inbox；已标注数据不会被碰触。
    assert collector.discard_sample(first["sample_id"]) is False
    assert (destination / f"{first['sample_id']}.json").exists()
    assert collector.discard_sample(second["sample_id"]) is True
    assert collector.list_pending() == []

    with pytest.raises(ValueError, match="invalid_sample_id"):
        collector.open_image("../outside")
    with pytest.raises(ValueError, match="invalid_sample_id"):
        collector.discard_sample("../outside")
    with pytest.raises(ValueError, match="invalid_evaluation_label"):
        collector.label_sample("0" * 64, "unknown")


def test_complete_multidimensional_annotation_is_saved_as_tuning_ground_truth(tmp_path):
    collector = _collector(tmp_path)
    sample = collector.collect(
        image_bytes=b"scored-image",
        filename="capture.jpg",
        session_id="session",
        goal="学习 Python",
        captured_at=1,
        frame_result=_frame(),
    )
    assert sample is not None

    reviewed = collector.label_sample(
        sample["sample_id"],
        "focused",
        annotation={
            "goal_relevance": 4,
            "task_evidence": 3,
            "context_fit": 4,
            "distraction_level": 0,
            "overall_score": 9,
            "annotation_confidence": 0.75,
            "scoring_rubric_version": "multidim-v1",
        },
    )

    assert reviewed["human_annotation_complete"] is True
    assert reviewed["label_source"] == "human_review"
    assert reviewed["label_status"] == "human_continuous_ground_truth"
    assert reviewed["human_goal_relevance"] == 4
    assert reviewed["human_task_evidence"] == 3
    assert reviewed["human_context_fit"] == 4
    assert reviewed["human_distraction_level"] == 0
    assert reviewed["human_overall_score"] == 9
    assert reviewed["annotation_confidence"] == 0.75


def test_invalid_multidimensional_annotation_does_not_move_sample(tmp_path):
    collector = _collector(tmp_path)
    sample = collector.collect(
        image_bytes=b"invalid-score-image",
        filename="capture.jpg",
        session_id="session",
        goal="学习 Python",
        captured_at=1,
        frame_result=_frame(),
    )
    assert sample is not None

    with pytest.raises(ValueError, match="invalid_goal_relevance"):
        collector.label_sample(
            sample["sample_id"],
            "focused",
            annotation={
                "goal_relevance": 5,
                "task_evidence": 3,
                "context_fit": 4,
                "distraction_level": 0,
                "overall_score": 9,
                "annotation_confidence": 1.0,
                "scoring_rubric_version": "multidim-v1",
            },
        )

    assert collector.list_pending()[0]["sample_id"] == sample["sample_id"]


class _FrameManager:
    def __init__(self, payload):
        self.payload = payload

    def add_frame(self, session_id, filename, file_bytes, *, frame_id=None, captured_at=None):
        return self.payload


class _SpyCollector:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def collect(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def test_focus_session_service_collects_after_analysis_and_isolates_failures(caplog):
    latest = _frame(captured_at=5678.0)
    payload = {"goal": "写报告", "latest_item": latest, "summary": {}}
    manager = _FrameManager(payload)
    spy = _SpyCollector()
    service = FocusSessionService(manager, object(), evaluation_collector=spy)

    result = service.add_frame(
        "session-id",
        "screen.jpg",
        b"screenshot",
        frame_id="frame-id",
        captured_at=5600,
    )
    assert result is payload
    assert spy.calls == [
        {
            "image_bytes": b"screenshot",
            "filename": "screen.jpg",
            "session_id": "session-id",
            "goal": "写报告",
            "captured_at": 5678.0,
            "frame_result": latest,
        }
    ]

    broken = _SpyCollector(RuntimeError("disk unavailable"))
    isolated = FocusSessionService(manager, object(), evaluation_collector=broken)
    assert isolated.add_frame("session-id", "screen.jpg", b"screenshot") is payload
    assert "评测截图采集失败" in caplog.text


def test_testing_app_exposes_but_disables_evaluation_collector(app):
    collector = app.extensions["evaluation_collector"]
    assert collector.enabled is False
