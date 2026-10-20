from __future__ import annotations

import json
import sys

import pytest

from scripts import benchmark_vision_models as benchmark
from scripts import build_vision_manifest as manifest_module
from scripts.build_vision_manifest import (
    build_manifest,
    effective_manifest_rows,
    manifest_requirement_failures,
    manifest_sample_statistics,
)
from scripts.evaluate_vision_results import evaluate


def _row(
    candidate: str,
    expected_state: str,
    predicted_state: str,
    *,
    structured_ok: bool = True,
    latency_ms: float = 1000,
) -> dict:
    dimensions = {
        "focused": (4, 3, 4, 0),
        "uncertain": (2, 1, 2, 1),
        "distracted": (0, 0, 1, 4),
    }.get(predicted_state, (None, None, None, None))
    return {
        "candidate": candidate,
        "expected_state": expected_state,
        "predicted_state": predicted_state,
        "structured_ok": structured_ok,
        "score_version": "multidim-v1",
        "raw_goal_relevance": dimensions[0],
        "raw_task_evidence": dimensions[1],
        "raw_context_fit": dimensions[2],
        "raw_distraction_level": dimensions[3],
        "latency_ms": latency_ms,
    }


def _qualified_rows(candidate: str = "qualified") -> list[dict]:
    return [
        *[_row(candidate, "focused", "focused") for _ in range(40)],
        *[_row(candidate, "uncertain", "uncertain") for _ in range(20)],
        *[_row(candidate, "distracted", "distracted") for _ in range(20)],
    ]


def test_evaluation_gate_accepts_qualified_candidate():
    report = evaluate(_qualified_rows())["qualified"]

    assert report["passed"] is True
    assert report["diagnostic_only"] is False
    assert report["sample_requirements_met"] is True
    assert report["macro_f1"] == 1.0
    assert report["focused_recall"] == 1.0
    assert report["distracted_recall"] == 1.0
    assert report["distracted_precision"] == 1.0
    assert report["uncertain_false_alert_rate"] == 0.0
    assert report["prediction_basis"] == "raw_state"


def test_evaluation_uses_raw_model_state_for_independent_screenshots():
    rows = _qualified_rows("raw-model")
    for row in rows:
        row["raw_state"] = row["expected_state"]
        row["stable_state"] = "uncertain"

    report = evaluate(rows)["raw-model"]

    assert report["passed"] is True
    assert report["macro_f1"] == 1.0


def test_evaluation_gate_marks_small_perfect_sample_as_diagnostic_only():
    rows = [
        *[_row("small", "focused", "focused") for _ in range(20)],
        *[_row("small", "uncertain", "uncertain") for _ in range(20)],
        *[_row("small", "distracted", "distracted") for _ in range(20)],
    ]

    report = evaluate(rows)["small"]

    assert report["samples"] == 60
    assert report["macro_f1"] == 1.0
    assert report["diagnostic_only"] is True
    assert report["sample_requirements_met"] is False
    assert report["passed"] is False
    assert "samples<80" in report["gate_failures"]


def test_ai_reference_labels_remain_diagnostic_even_when_metrics_are_perfect():
    rows = _qualified_rows("ai-reference")
    for row in rows:
        row["label_source"] = "ai_reference"
        row["label_status"] = "not_human_ground_truth"

    report = evaluate(rows)["ai-reference"]

    assert report["sample_requirements_met"] is True
    assert report["macro_f1"] == 1.0
    assert report["reference_labels_only"] is True
    assert report["diagnostic_only"] is True
    assert report["passed"] is False
    assert "labels_not_human_ground_truth" in report["gate_failures"]


@pytest.mark.parametrize(
    ("label_source", "label_status"),
    [
        ("ai", "model_generated"),
        ("model", "diagnostic_only"),
    ],
)
def test_all_ai_label_aliases_remain_diagnostic(label_source, label_status):
    rows = _qualified_rows("ai-alias")
    for row in rows:
        row["label_source"] = label_source
        row["label_status"] = label_status

    report = evaluate(rows)["ai-alias"]

    assert report["reference_labels_only"] is True
    assert report["diagnostic_only"] is True
    assert report["passed"] is False
    assert "labels_not_human_ground_truth" in report["gate_failures"]


def test_legacy_protocol_cannot_pass_multidimensional_structured_gate():
    rows = _qualified_rows("legacy-protocol")
    for row in rows:
        row["score_version"] = "legacy-v1"

    report = evaluate(rows)["legacy-protocol"]

    assert report["score_versions"] == {"legacy-v1": 80}
    assert report["structured_success_rate"] == 0.0
    assert report["passed"] is False
    assert "structured_success_rate<0.98" in report["gate_failures"]


def test_missing_multidimensional_fields_are_not_structured_successes():
    rows = _qualified_rows("missing-components")
    for row in rows:
        row.pop("raw_task_evidence")

    report = evaluate(rows)["missing-components"]

    assert report["structured_success_rate"] == 0.0
    assert report["passed"] is False


def test_evaluation_gate_rejects_candidate_that_misses_all_focused_frames():
    rows = [
        *[_row("blind-to-focus", "focused", "uncertain") for _ in range(40)],
        *[_row("blind-to-focus", "uncertain", "uncertain") for _ in range(20)],
        *[_row("blind-to-focus", "distracted", "distracted") for _ in range(20)],
    ]

    report = evaluate(rows)["blind-to-focus"]

    assert report["diagnostic_only"] is False
    assert report["distracted_precision"] == 1.0
    assert report["uncertain_false_alert_rate"] == 0.0
    assert report["focused_recall"] == 0.0
    assert report["macro_f1"] < 0.8
    assert report["passed"] is False
    assert "focused_recall<0.80" in report["gate_failures"]


def test_evaluation_gate_rejects_uncertain_false_alerts_with_formal_sample():
    rows = [
        *[_row("noisy", "focused", "focused") for _ in range(40)],
        *[_row("noisy", "uncertain", "distracted") for _ in range(20)],
        *[_row("noisy", "distracted", "distracted") for _ in range(20)],
    ]

    report = evaluate(rows)["noisy"]

    assert report["diagnostic_only"] is False
    assert report["uncertain_false_alert_rate"] == 1.0
    assert report["passed"] is False


def test_evaluation_gate_requires_twenty_samples_for_each_stable_state():
    rows = [
        *[_row("imbalanced", "focused", "focused") for _ in range(41)],
        *[_row("imbalanced", "uncertain", "uncertain") for _ in range(20)],
        *[_row("imbalanced", "distracted", "distracted") for _ in range(19)],
    ]

    report = evaluate(rows)["imbalanced"]

    assert report["samples"] == 80
    assert report["diagnostic_only"] is True
    assert report["passed"] is False
    assert "distracted_samples<20" in report["gate_failures"]


def test_unscorable_robustness_rows_count_toward_structured_success_only():
    rows = _qualified_rows("robustness")
    rows.append(_row("robustness", "unscorable", "unscorable", structured_ok=False))

    report = evaluate(rows)["robustness"]

    assert report["samples"] == 81
    assert report["stable_samples"] == 80
    assert report["macro_f1"] == 1.0
    assert report["structured_success_rate"] == 0.9877
    assert report["passed"] is True


def test_repeated_inferences_do_not_inflate_unique_sample_gate():
    unique_rows = [
        *[_row("repeated", "focused", "focused") for _ in range(10)],
        *[_row("repeated", "uncertain", "uncertain") for _ in range(10)],
        *[_row("repeated", "distracted", "distracted") for _ in range(10)],
    ]
    for index, row in enumerate(unique_rows):
        row["sample_id"] = f"sample-{index}"
    rows = [dict(row, repeat_index=repeat) for row in unique_rows for repeat in range(3)]

    report = evaluate(rows)["repeated"]

    assert report["samples"] == 30
    assert report["inferences"] == 90
    assert report["diagnostic_only"] is True
    assert report["passed"] is False


def test_repeated_inferences_do_not_weight_classification_metrics():
    rows = _qualified_rows("repeat-metrics")
    for index, row in enumerate(rows):
        row["sample_id"] = f"sample-{index}"
    target = rows[-1]
    target["predicted_state"] = "focused"
    rows.extend(
        dict(target, predicted_state="distracted", repeat_index=repeat)
        for repeat in range(2, 11)
    )

    report = evaluate(rows)["repeat-metrics"]

    assert report["samples"] == 80
    assert report["inferences"] == 89
    assert report["distracted_recall"] == 0.95
    assert report["confusion"]["distracted->focused"] == 1


def test_explicit_test_split_is_reported_and_controls_deployment_gate():
    rows = _qualified_rows("sealed")
    for index, row in enumerate(rows):
        row["sample_id"] = f"train-{index}"
        row["split"] = "train"
    for index, expected in enumerate(("focused", "uncertain", "distracted")):
        wrong = {"focused": "distracted", "uncertain": "focused", "distracted": "focused"}[expected]
        row = _row("sealed", expected, wrong)
        row["sample_id"] = f"test-{index}"
        row["split"] = "test"
        rows.append(row)

    report = evaluate(rows)["sealed"]

    assert report["gate_split"] == "test"
    assert report["splits"]["train"]["macro_f1"] == 1.0
    assert report["splits"]["test"]["macro_f1"] == 0.0
    assert report["passed"] is False


def test_tiny_perfect_test_split_cannot_approve_a_large_bad_training_set():
    rows = _qualified_rows("tiny-test")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        state = row["expected_state"]
        row["sample_id"] = f"sample-{index}"
        if state not in seen:
            row["split"] = "test"
            seen.add(state)
        else:
            row["split"] = "train"
            row["predicted_state"] = (
                "distracted" if state != "distracted" else "focused"
            )

    report = evaluate(rows)["tiny-test"]

    assert report["gate_split"] == "test"
    assert report["splits"]["test"]["samples"] == 3
    assert report["splits"]["test"]["macro_f1"] == 1.0
    assert report["gate_sample_requirements_met"] is False
    assert report["diagnostic_only"] is True
    assert report["passed"] is False
    assert "test_samples<80" in report["gate_failures"]


def test_benchmark_result_contains_traceable_model_and_stable_output(monkeypatch, tmp_path):
    class FakeFrame:
        state = "focused"
        raw_state = "focused"
        category_type = "focus"
        category_label = "代码编辑器"
        score_version = "multidim-v1"
        focus_score = 88.0
        raw_focus_score = None
        score_confidence = 0.91
        goal_relevance_score = 100.0
        task_evidence_score = 75.0
        context_fit_score = 100.0
        distraction_score = 0.0
        score_breakdown = {
            "goal_relevance_level": 4,
            "task_evidence_level": 3,
            "context_fit_level": 4,
            "distraction_level": 0,
        }
        decision_reason = "目标相关"
        base_decision_reason = "目标相关"
        fallback_reason = ""
        warning = None
        review_required = False

        def to_dict(self) -> dict:
            return {
                "state": self.state,
                "focus_score": self.focus_score,
                "score_confidence": self.score_confidence,
                "decision_reason": self.decision_reason,
            }

    class FakeAnalyzer:
        def __init__(self, _config):
            pass

        def scoring_status(self) -> dict:
            return {"configured": True, "provider": "siliconflow", "model": "fake-vision-model"}

        def analyze_frame(self, *_args, **_kwargs):
            return FakeFrame()

    monkeypatch.setattr(benchmark, "FocusAnalyzer", FakeAnalyzer)
    def mutate_postprocessed_score(frames):
        frames[0].focus_score = 12.0
        return frames

    monkeypatch.setattr(benchmark, "finalize_frame_scores", mutate_postprocessed_score)
    image_path = tmp_path / "focused.jpg"
    image_path.write_bytes(b"offline fixture")

    result = benchmark.run_candidate(
        "siliconflow-qwen3.5",
        [{
            "image": str(image_path),
            "expected_state": "focused",
            "goal": "编写测试",
            "label_source": "ai_reference",
            "label_status": "not_human_ground_truth",
        }],
    )[0]

    assert result["provider"] == "siliconflow"
    assert result["model"] == "fake-vision-model"
    assert result["raw_state"] == "focused"
    assert result["stable_state"] == "focused"
    assert result["focus_score"] == 12.0
    assert result["reason"] == "目标相关"
    assert result["raw"]["score_confidence"] == 0.91
    assert result["raw"]["goal_relevance"] == 4
    assert result["raw_goal_relevance_score"] == 100.0
    assert result["raw_task_evidence_score"] == 75.0
    assert result["raw_context_fit_score"] == 100.0
    assert result["raw_distraction_level"] == 0
    assert result["raw_focus_score"] is None
    assert result["postprocessed"]["focus_score"] == 12.0
    assert result["label_source"] == "ai_reference"
    assert result["label_status"] == "not_human_ground_truth"


def test_benchmark_repeats_use_fresh_analyzers_and_keep_split(monkeypatch, tmp_path):
    created = []

    class FakeFrame:
        state = "focused"
        raw_state = "focused"
        focus_score = 88.0
        score_confidence = 0.91
        decision_reason = "目标相关"
        fallback_reason = ""
        warning = None
        review_required = False

        def to_dict(self) -> dict:
            return {"raw_state": self.raw_state, "distraction_score": 0.1}

    class FakeAnalyzer:
        def __init__(self, _config):
            created.append(self)

        def scoring_status(self) -> dict:
            return {"configured": True, "provider": "siliconflow", "model": "fake"}

        def analyze_frame(self, *_args, **_kwargs):
            return FakeFrame()

    monkeypatch.setattr(benchmark, "FocusAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(benchmark, "finalize_frame_scores", lambda frames: frames)
    image_path = tmp_path / "focused.jpg"
    image_path.write_bytes(b"fixture")

    results = benchmark.run_candidate(
        "siliconflow-qwen3.5",
        [{"image": str(image_path), "expected_state": "focused", "split": "validation"}],
        repeats=3,
    )

    assert len(created) == 3
    assert [row["repeat_index"] for row in results] == [1, 2, 3]
    assert all(row["split"] == "validation" for row in results)


def test_offline_benchmark_can_override_timeout_without_changing_runtime_default(
    monkeypatch, tmp_path
):
    seen_timeouts = []

    class FakeFrame:
        state = "uncertain"
        raw_state = "uncertain"
        focus_score = 50.0
        score_confidence = 0.5
        decision_reason = "证据不足"
        fallback_reason = ""
        warning = None
        review_required = False

        def to_dict(self) -> dict:
            return {"raw_state": self.raw_state}

    class FakeAnalyzer:
        def __init__(self, config):
            seen_timeouts.append(config.siliconflow_timeout_seconds)

        def scoring_status(self) -> dict:
            return {"configured": True, "provider": "bailian", "model": "fake"}

        def analyze_frame(self, *_args, **_kwargs):
            return FakeFrame()

    monkeypatch.setattr(benchmark, "FocusAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(benchmark, "finalize_frame_scores", lambda frames: frames)
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"fixture")

    result = benchmark.run_candidate(
        "bailian-qwen3.7-flash",
        [{"image": str(image_path), "expected_state": "uncertain"}],
        timeout_seconds=15.0,
    )[0]

    assert seen_timeouts == [15.0]
    assert result["model_timeout_seconds"] == 15.0
    assert benchmark._config_for(
        "bailian-qwen3.7-flash"
    ).siliconflow_timeout_seconds == 16.0


def test_qwen38_candidate_uses_bailian_and_matches_runtime_default():
    candidate = benchmark._config_for("bailian-qwen3.8-27b")

    assert candidate.vision_provider == "bailian"
    assert candidate.bailian_model == "qwen3.8-27b"
    assert benchmark.DEFAULT_CONFIG.bailian_model == "qwen3.8-27b"


def test_manifest_gate_requires_each_semantic_state_even_with_eighty_total_rows():
    rows = [
        *[{"expected_state": "focused"} for _ in range(41)],
        *[{"expected_state": "uncertain"} for _ in range(20)],
        *[{"expected_state": "distracted"} for _ in range(19)],
    ]

    failures = manifest_requirement_failures(rows)

    assert failures == ["distracted 少于 20 张"]


def test_manifest_effective_counts_collapse_duplicates_and_reject_label_conflicts():
    rows = [
        {"expected_state": "focused", "goal": " 学习 Python ", "perceptual_group": "aa", "sample_id": "1"},
        {"expected_state": "focused", "goal": "学习  Python", "perceptual_group": "aa", "sample_id": "2"},
        {"expected_state": "uncertain", "goal": "学习 Python", "perceptual_group": "bb", "sample_id": "3"},
    ]
    statistics = manifest_sample_statistics(rows)
    assert statistics["raw_total"] == 3
    assert statistics["effective_total"] == 2
    assert statistics["raw_counts"]["focused"] == 2
    assert statistics["effective_counts"]["focused"] == 1
    assert len(effective_manifest_rows(rows)) == 2

    rows.append(
        {"expected_state": "distracted", "goal": "学习 Python", "perceptual_group": "aa", "sample_id": "4"}
    )
    conflicted = manifest_sample_statistics(rows)
    assert conflicted["label_conflict_count"] == 1
    assert conflicted["effective_counts"]["focused"] == 0
    assert conflicted["effective_counts"]["distracted"] == 0
    assert len(effective_manifest_rows(rows)) == 1
    assert "存在 1 个近重复单元标签冲突" in manifest_requirement_failures(
        rows,
        minimum_total=0,
        minimum_per_stable_state=0,
    )


def test_manifest_accepts_only_integrity_checked_human_labels(tmp_path):
    from app.services.evaluation_sample_collector import EvaluationSampleCollector

    collector = EvaluationSampleCollector(tmp_path / "evaluation" / "inbox", enabled=True)
    pending = collector.collect(
        image_bytes=b"verified-image",
        filename="capture.jpg",
        session_id="session",
        goal="核对清单",
        captured_at=1,
        frame_result={"raw_state": "focused", "thumbnail_hash": "00"},
    )
    assert pending is not None
    collector.label_sample(pending["sample_id"], "focused")

    issues: list[str] = []
    rows = build_manifest(collector.screenshots_dir, issues=issues)
    assert len(rows) == 1
    assert rows[0]["sample_id"] == pending["sample_id"]
    assert issues == []

    labelled_image = collector.screenshots_dir / "focused" / pending["image_file"]
    labelled_image.write_bytes(b"tampered-image")
    issues = []
    assert build_manifest(collector.screenshots_dir, issues=issues) == []
    assert any("content_sha256 与图片不一致" in issue for issue in issues)


def test_manifest_skips_image_without_human_review_sidecar(tmp_path):
    source = tmp_path / "screenshots"
    state_dir = source / "focused"
    state_dir.mkdir(parents=True)
    (state_dir / "orphan.jpg").write_bytes(b"orphan")
    issues: list[str] = []

    assert build_manifest(source, issues=issues) == []
    assert issues == ["focused/orphan.jpg: 缺少同名人工复核 JSON"]


def test_manifest_cli_writes_only_effective_rows_and_reports_both_counts(
    tmp_path,
    monkeypatch,
    capsys,
):
    from app.services.evaluation_sample_collector import EvaluationSampleCollector

    collector = EvaluationSampleCollector(tmp_path / "evaluation" / "inbox", enabled=True)
    pending = []
    for index, image_bytes in enumerate((b"near-a", b"near-b")):
        item = collector.collect(
            image_bytes=image_bytes,
            filename=f"capture-{index}.jpg",
            session_id=f"session-{index}",
            goal="核对近重复",
            captured_at=index,
            frame_result={"raw_state": "focused", "thumbnail_hash": "00"},
        )
        assert item is not None
        pending.append(item)
    for item in pending:
        collector.label_sample(item["sample_id"], "focused")

    output = tmp_path / "manifest.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_vision_manifest",
            "--source",
            str(collector.screenshots_dir),
            "--output",
            str(output),
            "--minimum",
            "1",
            "--minimum-per-stable-state",
            "0",
        ],
    )

    assert manifest_module.main() == 0
    written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    report = json.loads(capsys.readouterr().out.splitlines()[0])
    assert len(written) == 1
    assert report["raw_total"] == 2
    assert report["effective_total"] == 1
    assert report["counts"]["focused"] == {"raw": 2, "effective": 1}
