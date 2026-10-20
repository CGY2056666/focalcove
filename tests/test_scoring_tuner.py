from __future__ import annotations

import json

from focus_engine.scoring_policy import ScoringPolicy, scoring_policy_from_mapping
from scripts import tune_scoring_policy as tuner


def _row(
    sample_id: str,
    expected: str,
    *,
    goal: int,
    task: int,
    context: int,
    distraction: int,
    overall: int,
    split: str = "",
    source_group: str = "",
    label_source: str = "human_review",
    label_status: str = "human_continuous_ground_truth",
) -> dict:
    category = {"focused": "focus", "uncertain": "neutral", "distracted": "distract"}[expected]
    return {
        "candidate": "candidate-a",
        "sample_id": sample_id,
        "expected_state": expected,
        "raw_category": category,
        "raw_confidence": 0.9,
        "raw_goal_relevance": goal,
        "raw_task_evidence": task,
        "raw_context_fit": context,
        "raw_distraction_level": distraction,
        "structured_ok": True,
        "score_version": "multidim-v1",
        "human_review": True,
        "human_annotation_complete": True,
        "human_goal_relevance": goal,
        "human_task_evidence": task,
        "human_context_fit": context,
        "human_distraction_level": distraction,
        "human_overall_score": overall,
        "annotation_confidence": 0.75,
        "scoring_rubric_version": "multidim-v1",
        "label_source": label_source,
        "label_status": label_status,
        "split": split,
        "source_group": source_group or sample_id,
    }


def _formal_rows() -> list[dict]:
    target_policy = ScoringPolicy(
        goal_relevance_weight=0.35,
        task_evidence_weight=0.40,
        context_fit_weight=0.15,
        inverse_distraction_weight=0.10,
        confidence_shrink_weight=0.0,
    )
    counts = {"focused": 40, "uncertain": 20, "distracted": 20}
    rows: list[dict] = []
    for state in tuner.STATES:
        for index in range(counts[state]):
            if state == "focused":
                dimensions = (3 + index % 2, 2 + index % 3, 3 + index % 2, index % 2)
            elif state == "uncertain":
                dimensions = (1 + index % 3, 1 + (index + 1) % 3, 1 + index % 2, 1 + index % 3)
            else:
                dimensions = (index % 2, index % 2, 1 + index % 2, 3 + index % 2)
            score = tuner.composite_focus_score(
                dimensions[0] * 25,
                dimensions[1] * 25,
                dimensions[2] * 25,
                dimensions[3] / 4,
                0.9,
                target_policy,
            )
            validation_limit = 10 if state == "focused" else 5
            split = "validation" if index < validation_limit else "train"
            rows.append(
                _row(
                    f"{state}-{index}",
                    state,
                    goal=dimensions[0],
                    task=dimensions[1],
                    context=dimensions[2],
                    distraction=dimensions[3],
                    overall=max(0, min(10, round(score / 10))),
                    split=split,
                )
            )
    return rows


def test_policy_grid_obeys_declared_bounds_and_keeps_thresholds_fixed():
    policies = tuner.policy_grid()

    assert policies
    epsilon = 1e-9
    assert all(0.35 - epsilon <= item.goal_relevance_weight <= 0.60 + epsilon for item in policies)
    assert all(0.20 - epsilon <= item.task_evidence_weight <= 0.40 + epsilon for item in policies)
    assert all(0.05 - epsilon <= item.context_fit_weight <= 0.20 + epsilon for item in policies)
    assert all(0.05 - epsilon <= item.inverse_distraction_weight <= 0.20 + epsilon for item in policies)
    assert all(
        round(
            item.goal_relevance_weight
            + item.task_evidence_weight
            + item.context_fit_weight
            + item.inverse_distraction_weight,
            8,
        )
        == 1.0
        for item in policies
    )
    assert {item.confidence_shrink_weight for item in policies} == set(tuner.CONFIDENCE_SHRINK_GRID)
    assert {item.focused_confidence_min for item in policies} == {0.60}
    assert {item.distracted_confidence_min for item in policies} == {0.75}


def test_ai_reference_labels_are_always_diagnostic_and_never_return_policy():
    rows = [
        _row(
            f"ai-{index}",
            ("focused", "uncertain", "distracted")[index % 3],
            goal=2,
            task=2,
            context=2,
            distraction=2,
            overall=5,
            label_source="ai_reference",
            label_status="not_human_ground_truth",
        )
        for index in range(90)
    ]

    report = tuner.tune(rows)["candidate-a"]

    assert report["diagnostic_only"] is True
    assert report["deployment_recommended"] is False
    assert report["recommended_policy"] is None
    assert "labels_not_human_ground_truth" in report["errors"]


def test_class_only_human_rows_do_not_enter_continuous_tuning():
    row = _row(
        "legacy", "focused", goal=4, task=4, context=4, distraction=0, overall=10
    )
    row["human_annotation_complete"] = False
    row["scoring_rubric_version"] = "legacy-v1"

    observations, errors = tuner.parse_observations([row])
    report = tuner.tune([row])["candidate-a"]

    assert observations == []
    assert any("incomplete human multidimensional annotation" in error for error in errors)
    assert report["diagnostic_only"] is True
    assert report["recommended_policy"] is None


def test_legacy_model_results_do_not_enter_multidimensional_tuning():
    rows = _formal_rows()
    for row in rows:
        row["score_version"] = "legacy-v1"

    observations, errors = tuner.parse_observations(rows)
    report = tuner.tune(rows)["candidate-a"]

    assert observations == []
    assert any("model score_version is not multidim-v1" in error for error in errors)
    assert report["diagnostic_only"] is True
    assert report["deployment_recommended"] is False
    assert report["recommended_policy"] is None


def test_invalid_model_outputs_are_excluded_from_sample_counts():
    rows = _formal_rows()
    for row in rows:
        row["structured_ok"] = False
        row["raw_goal_relevance"] = None

    observations, errors = tuner.parse_observations(rows)
    report = tuner.tune(rows)["candidate-a"]

    assert observations == []
    assert any("model result is not structured" in error for error in errors)
    assert report["diagnostic_only"] is True
    assert report["counts"]["unique_complete_human_samples"] == 0
    assert report["recommended_policy"] is None


def test_grouped_split_keeps_related_samples_together():
    rows = []
    for state in tuner.STATES:
        for index in range(8):
            rows.append(
                _row(
                    f"{state}-{index}", state, goal=2, task=2, context=2,
                    distraction=2, overall=5, source_group=f"{state}-session-{index // 2}",
                )
            )
    observations, errors = tuner.parse_observations(rows)
    train, validation, _, split_errors = tuner.split_observations(observations)

    assert errors == []
    assert split_errors == []
    assert {item.group_id for item in train}.isdisjoint({item.group_id for item in validation})


def test_complete_human_scores_can_promote_a_runtime_loadable_policy():
    report = tuner.tune(_formal_rows())["candidate-a"]

    assert report["diagnostic_only"] is False
    assert report["classification_threshold_search"] == "not_run"
    assert report["validation_gate_met"] is True
    assert report["deployment_recommended"] is True
    policy = scoring_policy_from_mapping(report["recommended_policy"])
    assert policy.score_version == "multidim-v1"
    assert policy.focused_confidence_min == 0.60
    assert policy.distracted_confidence_min == 0.75
    assert report["selected_validation"]["balanced_mae"] <= 12
    assert report["selected_validation"]["within_15_rate"] >= 0.80


def test_cli_does_not_write_policy_for_ai_reference_run(monkeypatch, tmp_path):
    results_path = tmp_path / "results.jsonl"
    report_path = tmp_path / "report.json"
    policy_path = tmp_path / "policy.json"
    rows = [
        _row(
            f"ai-{index}",
            ("focused", "uncertain", "distracted")[index % 3],
            goal=2,
            task=2,
            context=2,
            distraction=2,
            overall=5,
            label_source="ai_reference",
            label_status="not_human_ground_truth",
        )
        for index in range(90)
    ]
    results_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "tune_scoring_policy.py", "--results", str(results_path), "--annotations",
            str(tmp_path / "missing"), "--candidate", "candidate-a", "--output",
            str(report_path), "--policy-output", str(policy_path),
        ],
    )

    assert tuner.main() == 2
    assert report_path.exists()
    assert not policy_path.exists()
