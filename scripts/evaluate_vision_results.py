"""汇总视觉模型 JSONL 结果并执行原型发布门槛。"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


STABLE_STATES = ("focused", "uncertain", "distracted")
RUNTIME_STATES = (*STABLE_STATES, "unscorable")
MULTIDIM_SCORE_VERSION = "multidim-v1"
MIN_TOTAL_SAMPLES = 80
MIN_SAMPLES_PER_STABLE_STATE = 20
REFERENCE_LABEL_SOURCES = {"ai", "ai_reference", "model", "model_generated"}
NON_GROUND_TRUTH_STATUSES = {
    "ai_reference",
    "diagnostic_only",
    "not_human_ground_truth",
}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _model_prediction(item: dict) -> str:
    raw_payload = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    value = str(
        item.get("raw_state")
        or raw_payload.get("raw_state")
        or item.get("predicted_state")
        or item.get("stable_state")
        or "unscorable"
    ).strip().lower()
    return value if value in RUNTIME_STATES else "unscorable"


def _raw_payload(item: dict) -> dict:
    return item.get("raw") if isinstance(item.get("raw"), dict) else {}


def _dimension_level(item: dict, name: str) -> float | None:
    raw = _raw_payload(item)
    value = item.get(f"raw_{name}")
    if value is None:
        value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not number.is_integer() or not 0.0 <= number <= 4.0:
        return None
    return number


def _multidim_protocol_ok(item: dict) -> bool:
    """Only count complete multidim-v1 model responses as structured."""

    if item.get("structured_ok") is not True:
        return False
    raw = _raw_payload(item)
    versions = [
        str(value).strip()
        for value in (item.get("score_version"), raw.get("score_version"))
        if str(value or "").strip()
    ]
    if not versions or any(value != MULTIDIM_SCORE_VERSION for value in versions):
        return False
    return all(
        _dimension_level(item, name) is not None
        for name in (
            "goal_relevance",
            "task_evidence",
            "context_fit",
            "distraction_level",
        )
    )


def _three_state_metrics(items: list[dict]) -> tuple[float, dict[str, dict[str, float | int]]]:
    classified = [item for item in items if str(item.get("expected_state") or "").strip().lower() in STABLE_STATES]
    metrics: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for state in STABLE_STATES:
        true_positive = sum(
            str(item.get("expected_state") or "").strip().lower() == state
            and _model_prediction(item) == state
            for item in classified
        )
        false_positive = sum(
            str(item.get("expected_state") or "").strip().lower() != state
            and _model_prediction(item) == state
            for item in classified
        )
        false_negative = sum(
            str(item.get("expected_state") or "").strip().lower() == state
            and _model_prediction(item) != state
            for item in classified
        )
        support = sum(str(item.get("expected_state") or "").strip().lower() == state for item in classified)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        metrics[state] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
    return sum(f1_values) / len(STABLE_STATES), metrics


def _sample_key(item: dict, index: int) -> str:
    return str(item.get("sample_id") or item.get("image") or f"row-{index}")


def _repeat_index(item: dict) -> int:
    value = item.get("repeat_index", 1)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 1


def _collapse_classification_samples(
    items: list[dict],
) -> tuple[list[dict], set[str], set[str], float]:
    """Collapse repeated calls to one classification row per semantic sample.

    The lowest ``repeat_index`` is the canonical classification inference. Other
    calls only contribute to repeat stability and call-level reliability/latency.
    """

    grouped: dict[str, list[tuple[int, int, dict]]] = defaultdict(list)
    for row_index, item in enumerate(items):
        grouped[_sample_key(item, row_index)].append(
            (_repeat_index(item), row_index, item)
        )

    samples: list[dict] = []
    label_conflicts: set[str] = set()
    split_conflicts: set[str] = set()
    repeat_agreements: list[float] = []
    for sample_key, repeats in grouped.items():
        ordered = sorted(repeats, key=lambda entry: (entry[0], entry[1]))
        labels = {
            str(entry[2].get("expected_state") or "").strip().lower()
            for entry in ordered
        }
        if len(labels) != 1:
            label_conflicts.add(sample_key)
            continue
        splits = {
            str(entry[2].get("split") or "").strip().lower()
            for entry in ordered
        }
        if len(splits) != 1:
            split_conflicts.add(sample_key)
            continue

        canonical = dict(ordered[0][2])
        canonical["sample_id"] = sample_key
        canonical["expected_state"] = next(iter(labels))
        canonical["split"] = next(iter(splits))
        samples.append(canonical)

        predictions = [_model_prediction(entry[2]) for entry in ordered]
        highest = max(Counter(predictions).values())
        repeat_agreements.append(highest / len(predictions))

    stability = sum(repeat_agreements) / len(repeat_agreements) if repeat_agreements else 0.0
    return samples, label_conflicts, split_conflicts, stability


def _classification_summary(items: list[dict]) -> dict[str, object]:
    classified = [
        item
        for item in items
        if str(item.get("expected_state") or "").strip().lower() in STABLE_STATES
    ]
    true_distracted = sum(
        str(item.get("expected_state") or "").strip().lower() == "distracted"
        and _model_prediction(item) == "distracted"
        for item in classified
    )
    predicted_distracted = sum(
        _model_prediction(item) == "distracted" for item in classified
    )
    uncertain_total = sum(
        str(item.get("expected_state") or "").strip().lower() == "uncertain"
        for item in classified
    )
    uncertain_false_alerts = sum(
        str(item.get("expected_state") or "").strip().lower() == "uncertain"
        and _model_prediction(item) == "distracted"
        for item in classified
    )
    precision = true_distracted / predicted_distracted if predicted_distracted else 0.0
    false_alert_rate = uncertain_false_alerts / uncertain_total if uncertain_total else 0.0
    macro_f1, class_metrics = _three_state_metrics(classified)
    return {
        "samples": len(items),
        "stable_samples": len(classified),
        "distracted_precision": precision,
        "uncertain_false_alert_rate": false_alert_rate,
        "macro_f1": macro_f1,
        "focused_recall": float(class_metrics["focused"]["recall"]),
        "distracted_recall": float(class_metrics["distracted"]["recall"]),
        "class_metrics": class_metrics,
        "confusion": Counter(
            (str(item.get("expected_state") or "unknown"), _model_prediction(item))
            for item in classified
        ),
    }


def _render_classification_summary(summary: dict[str, object]) -> dict[str, object]:
    class_metrics = summary["class_metrics"]
    confusion = summary["confusion"]
    return {
        "samples": int(summary["samples"]),
        "stable_samples": int(summary["stable_samples"]),
        "distracted_precision": round(float(summary["distracted_precision"]), 4),
        "uncertain_false_alert_rate": round(
            float(summary["uncertain_false_alert_rate"]), 4
        ),
        "macro_f1": round(float(summary["macro_f1"]), 4),
        "focused_recall": round(float(summary["focused_recall"]), 4),
        "distracted_recall": round(float(summary["distracted_recall"]), 4),
        "class_metrics": {
            state: {
                "precision": round(float(class_metrics[state]["precision"]), 4),
                "recall": round(float(class_metrics[state]["recall"]), 4),
                "f1": round(float(class_metrics[state]["f1"]), 4),
                "support": int(class_metrics[state]["support"]),
            }
            for state in STABLE_STATES
        },
        "confusion": {
            f"{expected}->{predicted}": count
            for (expected, predicted), count in sorted(confusion.items())
        },
    }


def evaluate(rows: list[dict]) -> dict:
    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_model[str(row.get("candidate") or "unknown")].append(row)

    reports: dict[str, dict] = {}
    for candidate, items in sorted(by_model.items()):
        unique_items, label_conflicts, split_conflicts, repeat_agreement = (
            _collapse_classification_samples(items)
        )
        label_sources = sorted(
            {
                str(item.get("label_source") or "").strip().lower()
                for item in unique_items
                if str(item.get("label_source") or "").strip()
            }
        )
        label_statuses = sorted(
            {
                str(item.get("label_status") or "").strip().lower()
                for item in unique_items
                if str(item.get("label_status") or "").strip()
            }
        )
        reference_labels_only = bool(
            set(label_sources) & REFERENCE_LABEL_SOURCES
            or set(label_statuses) & NON_GROUND_TRUTH_STATUSES
        )
        structured = [_multidim_protocol_ok(item) for item in items]
        structured_rate = sum(structured) / len(structured) if structured else 0.0
        p95_ms = _percentile([float(item.get("latency_ms") or 0) for item in items], 0.95)

        overall_summary = _classification_summary(unique_items)
        split_names = sorted(
            {
                str(item.get("split") or "").strip().lower()
                for item in unique_items
                if str(item.get("split") or "").strip()
            }
        )
        recognized_splits = {"train", "validation", "test"}
        explicit_splits = set(split_names) & recognized_splits
        invalid_splits = set(split_names) - recognized_splits
        has_unassigned = any(
            not str(item.get("split") or "").strip() for item in unique_items
        )
        split_errors: list[str] = []
        if invalid_splits:
            split_errors.append("invalid_split")
        if explicit_splits and has_unassigned:
            split_errors.append("explicit_split_incomplete")
        split_summaries = {
            split: _classification_summary(
                [
                    item
                    for item in unique_items
                    if str(item.get("split") or "").strip().lower() == split
                ]
            )
            for split in split_names
        }
        gate_split = (
            "test"
            if "test" in split_summaries
            else "validation"
            if "validation" in split_summaries
            else "all"
        )
        gate_summary = split_summaries.get(gate_split, overall_summary)
        gate_items = (
            unique_items
            if gate_split == "all"
            else [
                item
                for item in unique_items
                if str(item.get("split") or "").strip().lower() == gate_split
            ]
        )
        rendered_gate = _render_classification_summary(gate_summary)
        expected_counts = Counter(
            str(item.get("expected_state") or "").strip().lower()
            for item in unique_items
        )
        gate_expected_counts = Counter(
            str(item.get("expected_state") or "").strip().lower()
            for item in gate_items
        )
        overall_sample_requirements_met = (
            len(unique_items) >= MIN_TOTAL_SAMPLES
            and all(expected_counts[state] >= MIN_SAMPLES_PER_STABLE_STATE for state in STABLE_STATES)
            and not label_conflicts
            and not split_conflicts
            and not split_errors
        )
        gate_sample_requirements_met = (
            len(gate_items) >= MIN_TOTAL_SAMPLES
            and all(
                gate_expected_counts[state] >= MIN_SAMPLES_PER_STABLE_STATE
                for state in STABLE_STATES
            )
        )
        sample_requirements_met = (
            overall_sample_requirements_met and gate_sample_requirements_met
        )
        quality_gate_met = (
            float(gate_summary["distracted_precision"]) >= 0.90
            and float(gate_summary["uncertain_false_alert_rate"]) <= 0.10
            and structured_rate >= 0.98
            and p95_ms <= 7000
            and float(gate_summary["macro_f1"]) >= 0.80
            and float(gate_summary["focused_recall"]) >= 0.80
            and float(gate_summary["distracted_recall"]) >= 0.75
        )
        passed = sample_requirements_met and quality_gate_met and not reference_labels_only
        gate_failures: list[str] = []
        if reference_labels_only:
            gate_failures.append("labels_not_human_ground_truth")
        if len(unique_items) < MIN_TOTAL_SAMPLES:
            gate_failures.append(f"samples<{MIN_TOTAL_SAMPLES}")
        if label_conflicts:
            gate_failures.append("sample_label_conflict")
        if split_conflicts:
            gate_failures.append("sample_split_conflict")
        gate_failures.extend(split_errors)
        for state in STABLE_STATES:
            if expected_counts[state] < MIN_SAMPLES_PER_STABLE_STATE:
                gate_failures.append(f"{state}_samples<{MIN_SAMPLES_PER_STABLE_STATE}")
        if gate_split != "all":
            if len(gate_items) < MIN_TOTAL_SAMPLES:
                gate_failures.append(f"{gate_split}_samples<{MIN_TOTAL_SAMPLES}")
            for state in STABLE_STATES:
                if gate_expected_counts[state] < MIN_SAMPLES_PER_STABLE_STATE:
                    gate_failures.append(
                        f"{gate_split}_{state}_samples<{MIN_SAMPLES_PER_STABLE_STATE}"
                    )
        if float(gate_summary["distracted_precision"]) < 0.90:
            gate_failures.append("distracted_precision<0.90")
        if float(gate_summary["uncertain_false_alert_rate"]) > 0.10:
            gate_failures.append("uncertain_false_alert_rate>0.10")
        if structured_rate < 0.98:
            gate_failures.append("structured_success_rate<0.98")
        if p95_ms > 7000:
            gate_failures.append("p95_latency_ms>7000")
        if float(gate_summary["macro_f1"]) < 0.80:
            gate_failures.append("macro_f1<0.80")
        if float(gate_summary["focused_recall"]) < 0.80:
            gate_failures.append("focused_recall<0.80")
        if float(gate_summary["distracted_recall"]) < 0.75:
            gate_failures.append("distracted_recall<0.75")

        first = items[0] if items else {}
        reports[candidate] = {
            "provider": str(first.get("provider") or ""),
            "model": str(first.get("model") or ""),
            "prediction_basis": "raw_state",
            "samples": len(unique_items),
            "inferences": len(items),
            "stable_samples": int(overall_summary["stable_samples"]),
            "classified_inferences": sum(
                str(item.get("expected_state") or "").strip().lower() in STABLE_STATES
                for item in items
            ),
            "expected_state_counts": {state: expected_counts[state] for state in STABLE_STATES},
            "gate_expected_state_counts": {
                state: gate_expected_counts[state] for state in STABLE_STATES
            },
            "overall_sample_requirements_met": overall_sample_requirements_met,
            "gate_sample_requirements_met": gate_sample_requirements_met,
            "sample_requirements_met": sample_requirements_met,
            "label_sources": label_sources,
            "label_statuses": label_statuses,
            "reference_labels_only": reference_labels_only,
            "diagnostic_only": not sample_requirements_met or reference_labels_only,
            "gate_split": gate_split,
            "distracted_precision": rendered_gate["distracted_precision"],
            "uncertain_false_alert_rate": rendered_gate["uncertain_false_alert_rate"],
            "structured_success_rate": round(structured_rate, 4),
            "score_versions": dict(
                sorted(
                    Counter(
                        str(item.get("score_version") or "missing")
                        for item in items
                    ).items()
                )
            ),
            "p95_latency_ms": round(p95_ms, 1),
            "repeat_agreement": round(repeat_agreement, 4),
            "macro_f1": rendered_gate["macro_f1"],
            "focused_recall": rendered_gate["focused_recall"],
            "distracted_recall": rendered_gate["distracted_recall"],
            "class_metrics": rendered_gate["class_metrics"],
            "splits": {},
            "passed": passed,
            "gate_failures": gate_failures,
            "confusion": rendered_gate["confusion"],
        }
        split_reports = {
            "all": _render_classification_summary(overall_summary),
            **{
                split: _render_classification_summary(summary)
                for split, summary in split_summaries.items()
            },
        }
        for split, split_report in split_reports.items():
            split_inferences = (
                items
                if split == "all"
                else [
                    item
                    for item in items
                    if str(item.get("split") or "").strip().lower() == split
                ]
            )
            split_structured = [
                _multidim_protocol_ok(item) for item in split_inferences
            ]
            split_report["inferences"] = len(split_inferences)
            split_report["structured_success_rate"] = round(
                sum(split_structured) / len(split_structured) if split_structured else 0.0,
                4,
            )
            split_report["p95_latency_ms"] = round(
                _percentile(
                    [float(item.get("latency_ms") or 0) for item in split_inferences],
                    0.95,
                ),
                1,
            )
        reports[candidate]["splits"] = split_reports
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reports = evaluate(rows)
    rendered = json.dumps(reports, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if reports and any(report["passed"] for report in reports.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
