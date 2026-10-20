"""Tune multidimensional score weights from complete human annotations only.

This command never calls an external API. Classification thresholds stay
fixed, so numeric calibration cannot silently change alert behaviour.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable, Mapping

from focus_engine.scoring_policy import (
    DEFAULT_SCORING_POLICY,
    ScoringPolicy,
    composite_focus_score,
)


STATES = ("focused", "uncertain", "distracted")
SCORING_RUBRIC_VERSION = "multidim-v1"
MIN_TOTAL_UNIQUE_SAMPLES = 80
MIN_TRAIN_PER_STATE = 10
MIN_VALIDATION_PER_STATE = 5
DEFAULT_WEIGHT_STEP = 0.05
CONFIDENCE_SHRINK_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
AI_REFERENCE_SOURCES = frozenset({"ai", "ai_reference", "model", "model_generated"})
NON_HUMAN_STATUSES = frozenset({"not_human_ground_truth", "ai_reference", "diagnostic_only"})


@dataclass(frozen=True)
class Observation:
    candidate: str
    sample_id: str
    group_id: str
    expected_state: str
    raw_category: str
    raw_confidence: float
    goal_relevance: float
    task_evidence: float
    context_fit: float
    distraction_level: float
    human_overall_score: float
    annotation_confidence: float
    structured_ok: bool
    split: str
    group_tokens: tuple[str, ...]
    repeat_index: int


def _bounded_number(value: object, lower: float, upper: float) -> tuple[float, bool]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0, False
    number = float(value)
    return (number, True) if math.isfinite(number) and lower <= number <= upper else (0.0, False)


def _raw_value(row: Mapping[str, Any], raw: Mapping[str, Any], *names: str) -> object:
    for name in names:
        if name in row:
            return row[name]
        if name in raw:
            return raw[name]
    return None


def _normalized_category(value: object) -> str:
    return {
        "focused": "focus",
        "uncertain": "neutral",
        "distracted": "distract",
    }.get(str(value or "").strip().lower(), str(value or "neutral").strip().lower())


def _dimension_level(
    row: Mapping[str, Any],
    raw: Mapping[str, Any],
    level_names: tuple[str, ...],
    score_names: tuple[str, ...],
) -> tuple[float, bool]:
    level = _raw_value(row, raw, *level_names)
    if level is not None:
        value, ok = _bounded_number(level, 0.0, 4.0)
        return value, ok and value.is_integer()
    score = _raw_value(row, raw, *score_names)
    value, ok = _bounded_number(score, 0.0, 100.0)
    level_value = value / 25.0
    return (
        (level_value, True)
        if ok and level_value.is_integer()
        else (0.0, False)
    )


def _distraction_level(row: Mapping[str, Any], raw: Mapping[str, Any]) -> tuple[float, bool]:
    level = _raw_value(row, raw, "raw_distraction_level", "distraction_level")
    if level is not None:
        value, ok = _bounded_number(level, 0.0, 4.0)
        return value, ok and value.is_integer()
    score, ok = _bounded_number(
        _raw_value(row, raw, "raw_distraction_score", "distraction_score"), 0.0, 1.0
    )
    level_value = score * 4.0
    return (
        (level_value, True)
        if ok and level_value.is_integer()
        else (0.0, False)
    )


def _group_tokens(row: Mapping[str, Any], sample_id: str) -> tuple[str, ...]:
    tokens = {f"sample:{sample_id}"}
    for field in ("session_id", "sequence_id", "source_group", "group_id"):
        value = str(row.get(field) or "").strip()
        if value:
            tokens.add(f"context:{value}")
    for field in ("perceptual_group", "content_sha256"):
        value = str(row.get(field) or "").strip()
        if value:
            tokens.add(f"visual:{value}")
    return tuple(sorted(tokens))


def _joint_group_observations(observations: list[Observation]) -> list[Observation]:
    parents = list(range(len(observations)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    token_owner: dict[str, int] = {}
    for index, observation in enumerate(observations):
        for token in observation.group_tokens:
            union(index, token_owner.setdefault(token, index))
    component_tokens: dict[int, set[str]] = defaultdict(set)
    for index, observation in enumerate(observations):
        component_tokens[find(index)].update(observation.group_tokens)
    component_ids = {
        root: "joint:" + hashlib.sha256("\0".join(sorted(tokens)).encode()).hexdigest()[:16]
        for root, tokens in component_tokens.items()
    }
    return [
        replace(observation, group_id=component_ids[find(index)])
        for index, observation in enumerate(observations)
    ]


def _is_ai_reference(row: Mapping[str, Any]) -> bool:
    source = str(row.get("label_source") or "").strip().lower()
    status = str(row.get("label_status") or "").strip().lower()
    return source in AI_REFERENCE_SOURCES or status in NON_HUMAN_STATUSES


def _complete_human_annotation(row: Mapping[str, Any]) -> bool:
    return (
        row.get("human_review") is True
        and row.get("human_annotation_complete") is True
        and str(row.get("scoring_rubric_version") or "").strip() == SCORING_RUBRIC_VERSION
        and not _is_ai_reference(row)
    )


def parse_observations(rows: Iterable[dict]) -> tuple[list[Observation], list[str]]:
    observations: list[Observation] = []
    errors: list[str] = []
    for index, row in enumerate(rows):
        candidate = str(row.get("candidate") or "unknown")
        sample_id = str(row.get("sample_id") or row.get("image") or f"row-{index}")
        if _is_ai_reference(row):
            errors.append(f"{candidate}/{sample_id}: AI reference label is diagnostic only")
            continue
        expected = str(row.get("expected_state") or row.get("human_label") or "").strip().lower()
        if expected not in STATES:
            continue
        if not _complete_human_annotation(row):
            errors.append(f"{candidate}/{sample_id}: incomplete human multidimensional annotation")
            continue

        raw = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
        score_versions = [
            str(value).strip()
            for value in (row.get("score_version"), raw.get("score_version"))
            if str(value or "").strip()
        ]
        if not score_versions or any(
            value != SCORING_RUBRIC_VERSION for value in score_versions
        ):
            errors.append(f"{candidate}/{sample_id}: model score_version is not multidim-v1")
            continue
        if row.get("structured_ok") is not True:
            errors.append(f"{candidate}/{sample_id}: model result is not structured")
            continue

        category_value = _raw_value(row, raw, "raw_category", "category_type")
        category = _normalized_category(category_value)
        confidence, confidence_ok = _bounded_number(
            _raw_value(row, raw, "raw_confidence", "confidence", "score_confidence"), 0.0, 1.0
        )
        goal_relevance, goal_ok = _dimension_level(
            row, raw, ("raw_goal_relevance", "goal_relevance"),
            ("raw_goal_relevance_score", "goal_relevance_score"),
        )
        task_evidence, task_ok = _dimension_level(
            row, raw, ("raw_task_evidence", "task_evidence"),
            ("raw_task_evidence_score", "task_evidence_score"),
        )
        context_fit, context_ok = _dimension_level(
            row, raw, ("raw_context_fit", "context_fit"),
            ("raw_context_fit_score", "context_fit_score"),
        )
        distraction_level, distraction_ok = _distraction_level(row, raw)
        overall, overall_ok = _bounded_number(row.get("human_overall_score"), 0.0, 10.0)
        annotation_confidence, annotation_confidence_ok = _bounded_number(
            row.get("annotation_confidence"), 0.0, 1.0
        )
        human_dimension_checks: dict[str, bool] = {}
        for name in (
            "goal_relevance",
            "task_evidence",
            "context_fit",
            "distraction_level",
        ):
            value, valid = _bounded_number(row.get(f"human_{name}"), 0.0, 4.0)
            human_dimension_checks[name] = valid and value.is_integer()
        checks = {
            "raw category": category_value is not None and category in {"focus", "neutral", "distract"},
            "raw confidence": confidence_ok,
            "goal relevance": goal_ok,
            "task evidence": task_ok,
            "context fit": context_ok,
            "distraction level": distraction_ok,
            "human overall score": overall_ok,
            "annotation confidence": annotation_confidence_ok,
            **{f"human {name.replace('_', ' ')}": valid for name, valid in human_dimension_checks.items()},
        }
        invalid_fields: list[str] = []
        for name, valid in checks.items():
            if not valid:
                invalid_fields.append(name)
                errors.append(f"{candidate}/{sample_id}: invalid {name}")
        if invalid_fields:
            continue
        repeat_value = row.get("repeat_index", 1)
        repeat_index = (
            repeat_value
            if isinstance(repeat_value, int) and not isinstance(repeat_value, bool) and repeat_value >= 1
            else 1
        )
        observations.append(
            Observation(
                candidate=candidate, sample_id=sample_id, group_id="", expected_state=expected,
                raw_category=category, raw_confidence=confidence, goal_relevance=goal_relevance,
                task_evidence=task_evidence, context_fit=context_fit,
                distraction_level=distraction_level, human_overall_score=overall * 10.0,
                annotation_confidence=annotation_confidence, structured_ok=True,
                split=str(row.get("split") or "").strip().lower(),
                group_tokens=_group_tokens(row, sample_id), repeat_index=repeat_index,
            )
        )
    return _joint_group_observations(observations), errors


def _stable_hash(value: str, seed: int = 20260819) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{value}".encode()).digest()[:8], "big")


def _unique_samples(observations: list[Observation]) -> dict[str, Observation]:
    samples: dict[str, Observation] = {}
    for observation in observations:
        previous = samples.get(observation.sample_id)
        if previous and (
            previous.expected_state != observation.expected_state
            or previous.group_id != observation.group_id
            or previous.human_overall_score != observation.human_overall_score
        ):
            raise ValueError(f"sample {observation.sample_id} has conflicting labels, groups, or scores")
        samples.setdefault(observation.sample_id, observation)
    return samples


def _state_counts(observations: list[Observation]) -> dict[str, int]:
    return dict(Counter(item.expected_state for item in _unique_samples(observations).values()))


def split_observations(
    observations: list[Observation], *, validation_fraction: float = 0.25, seed: int = 20260819
) -> tuple[list[Observation], list[Observation], list[Observation], list[str]]:
    if not observations:
        return [], [], [], ["no complete human observations"]
    groups: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        groups[observation.group_id].append(observation)
    explicit = {item.split for item in observations if item.split in {"train", "validation", "test"}}
    if explicit:
        if any(item.split not in {"train", "validation", "test"} for item in observations):
            return [], [], [], ["explicit split is incomplete"]
        errors = [
            f"group {group_id} crosses explicit splits"
            for group_id, group_rows in groups.items()
            if len({item.split for item in group_rows}) != 1
        ]
        if errors:
            return [], [], [], errors
        return (
            [item for item in observations if item.split == "train"],
            [item for item in observations if item.split == "validation"],
            [item for item in observations if item.split == "test"], [],
        )

    unique = _unique_samples(observations)
    counts_by_group: dict[str, Counter] = defaultdict(Counter)
    for sample in unique.values():
        counts_by_group[sample.group_id][sample.expected_state] += 1
    totals = Counter(sample.expected_state for sample in unique.values())
    targets = {state: max(1, math.ceil(totals[state] * validation_fraction)) for state in STATES}
    chosen: set[str] = set()
    chosen_counts: Counter = Counter()
    for state in STATES:
        candidates = [group for group, counts in counts_by_group.items() if counts[state] and group not in chosen]
        candidates.sort(key=lambda group: (sum(counts_by_group[group].values()), _stable_hash(group, seed)))
        for group in candidates:
            if chosen_counts[state] >= targets[state]:
                break
            chosen.add(group)
            chosen_counts.update(counts_by_group[group])
    return (
        [item for item in observations if item.group_id not in chosen],
        [item for item in observations if item.group_id in chosen], [], [],
    )


def _predict(observation: Observation, policy: ScoringPolicy) -> str:
    if not observation.structured_ok:
        return "unscorable"
    if observation.raw_category == "focus" and observation.raw_confidence >= policy.focused_confidence_min:
        return "focused"
    if observation.raw_category == "distract" and observation.raw_confidence >= policy.distracted_confidence_min:
        return "distracted"
    return "uncertain"


def _score(observation: Observation, policy: ScoringPolicy) -> float:
    return composite_focus_score(
        observation.goal_relevance * 25.0,
        observation.task_evidence * 25.0,
        observation.context_fit * 25.0,
        observation.distraction_level / 4.0,
        observation.raw_confidence,
        policy,
    )


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        rank = (start + end - 1) / 2.0 + 1.0
        for index in ordered[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _spearman(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or len(left) != len(right):
        return 0.0
    left_ranks, right_ranks = _ranks(left), _ranks(right)
    left_mean, right_mean = mean(left_ranks), mean(right_ranks)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_ranks, right_ranks))
    denominator = math.sqrt(
        sum((a - left_mean) ** 2 for a in left_ranks)
        * sum((b - right_mean) ** 2 for b in right_ranks)
    )
    return numerator / denominator if denominator else 0.0


def _sample_results(observations: list[Observation], policy: ScoringPolicy) -> list[dict[str, Any]]:
    by_sample: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        by_sample[observation.sample_id].append(observation)
    results: list[dict[str, Any]] = []
    for sample_id, repeats in sorted(by_sample.items()):
        expected = {item.expected_state for item in repeats}
        targets = {item.human_overall_score for item in repeats}
        if len(expected) != 1 or len(targets) != 1:
            raise ValueError(f"sample {sample_id} has conflicting human annotations")
        valid_scores = [_score(item, policy) for item in repeats if item.structured_ok]
        canonical = min(repeats, key=lambda item: item.repeat_index)
        results.append({
            "sample_id": sample_id, "expected": next(iter(expected)),
            "predicted": _predict(canonical, policy), "target": next(iter(targets)),
            "score": mean(valid_scores) if valid_scores else None,
            "score_std": pstdev(valid_scores) if len(valid_scores) > 1 else 0.0,
        })
    return results


def metrics(observations: list[Observation], policy: ScoringPolicy) -> dict[str, Any]:
    samples = _sample_results(observations, policy)
    scored = [item for item in samples if item["score"] is not None]
    errors = [abs(float(item["score"]) - float(item["target"])) for item in scored]
    per_state_mae = {
        state: mean(
            abs(float(item["score"]) - float(item["target"]))
            for item in scored if item["expected"] == state
        ) if any(item["expected"] == state for item in scored) else float("inf")
        for state in STATES
    }
    predicted_scores = [float(item["score"]) for item in scored]
    target_scores = [float(item["target"]) for item in scored]
    false_alerts = sum(item["expected"] == "uncertain" and item["predicted"] == "distracted" for item in samples)
    uncertain_total = sum(item["expected"] == "uncertain" for item in samples)
    return {
        "samples": len(samples), "scored_samples": len(scored),
        "mae": mean(errors) if errors else float("inf"),
        "balanced_mae": mean(per_state_mae.values()), "per_state_mae": per_state_mae,
        "spearman": _spearman(predicted_scores, target_scores),
        "within_15_rate": sum(error <= 15.0 for error in errors) / len(errors) if errors else 0.0,
        "score_std_mean": mean(float(item["score_std"]) for item in scored) if scored else 0.0,
        "classification_accuracy": sum(item["expected"] == item["predicted"] for item in samples) / max(len(samples), 1),
        "uncertain_false_alert_rate": false_alerts / max(uncertain_total, 1),
        "false_alert_count": false_alerts,
    }


def _policy_kwargs(**overrides: Any) -> dict[str, Any]:
    values = DEFAULT_SCORING_POLICY.to_dict()
    values.update(overrides)
    return values


def policy_grid(weight_step: float = DEFAULT_WEIGHT_STEP) -> list[ScoringPolicy]:
    units = round(1.0 / weight_step)
    if units < 1 or not math.isclose(units * weight_step, 1.0, abs_tol=1e-9):
        raise ValueError("weight step must divide 1 exactly")

    def bounds(lower: float, upper: float) -> range:
        return range(math.ceil(lower / weight_step - 1e-9), math.floor(upper / weight_step + 1e-9) + 1)

    policies: list[ScoringPolicy] = []
    distraction_bounds = bounds(0.05, 0.20)
    for goal_units in bounds(0.35, 0.60):
        for task_units in bounds(0.20, 0.40):
            for context_units in bounds(0.05, 0.20):
                distraction_units = units - goal_units - task_units - context_units
                if distraction_units not in distraction_bounds:
                    continue
                for shrink in CONFIDENCE_SHRINK_GRID:
                    policies.append(ScoringPolicy(**_policy_kwargs(
                        goal_relevance_weight=goal_units * weight_step,
                        task_evidence_weight=task_units * weight_step,
                        context_fit_weight=context_units * weight_step,
                        inverse_distraction_weight=distraction_units * weight_step,
                        confidence_shrink_weight=shrink,
                    )))
    return policies


def _policy_distance(policy: ScoringPolicy) -> float:
    return sum(
        abs(float(getattr(policy, field)) - float(getattr(DEFAULT_SCORING_POLICY, field)))
        for field in (
            "goal_relevance_weight", "task_evidence_weight", "context_fit_weight",
            "inverse_distraction_weight", "confidence_shrink_weight",
        )
    )


def _quality_gate(values: Mapping[str, Any]) -> bool:
    per_state = values.get("per_state_mae") or {}
    return (
        float(values.get("balanced_mae", math.inf)) <= 12.0
        and all(float(per_state.get(state, math.inf)) <= 15.0 for state in STATES)
        and float(values.get("spearman", 0.0)) >= 0.70
        and float(values.get("within_15_rate", 0.0)) >= 0.80
    )


def _minimum_count_errors(
    all_observations: list[Observation], train: list[Observation], validation: list[Observation]
) -> list[str]:
    errors: list[str] = []
    if len(_unique_samples(all_observations)) < MIN_TOTAL_UNIQUE_SAMPLES:
        errors.append(f"complete_human_samples<{MIN_TOTAL_UNIQUE_SAMPLES}")
    all_counts, train_counts, validation_counts = (
        _state_counts(all_observations), _state_counts(train), _state_counts(validation)
    )
    for state in STATES:
        if all_counts.get(state, 0) < 20:
            errors.append(f"{state}_complete_human_samples<20")
        if train_counts.get(state, 0) < MIN_TRAIN_PER_STATE:
            errors.append(f"train_{state}<{MIN_TRAIN_PER_STATE}")
        if validation_counts.get(state, 0) < MIN_VALIDATION_PER_STATE:
            errors.append(f"validation_{state}<{MIN_VALIDATION_PER_STATE}")
    return errors


def _render_metrics(values: Mapping[str, Any]) -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, Mapping):
            rendered[key] = {name: round(float(number), 4) for name, number in value.items()}
        elif isinstance(value, float):
            rendered[key] = round(value, 4)
        else:
            rendered[key] = value
    return rendered


def tune_candidate(
    observations: list[Observation], *, validation_fraction: float = 0.25,
    seed: int = 20260819, weight_step: float = DEFAULT_WEIGHT_STEP,
    forced_diagnostic_reasons: list[str] | None = None,
) -> dict[str, Any]:
    candidate = observations[0].candidate if observations else "unknown"
    try:
        train, validation, test, split_errors = split_observations(
            observations, validation_fraction=validation_fraction, seed=seed
        )
    except ValueError as exc:
        train, validation, test, split_errors = [], [], [], [str(exc)]
    errors = list(forced_diagnostic_reasons or []) + split_errors
    if not errors:
        errors.extend(_minimum_count_errors(observations, train, validation))
    counts = {
        "unique_complete_human_samples": len(_unique_samples(observations)) if observations else 0,
        "inferences": len(observations), "all": _state_counts(observations) if observations else {},
        "train": _state_counts(train) if train else {},
        "validation": _state_counts(validation) if validation else {},
        "test": _state_counts(test) if test else {},
    }
    if errors:
        return {
            "candidate": candidate, "diagnostic_only": True, "deployment_recommended": False,
            "errors": errors, "counts": counts, "classification_threshold_search": "not_run",
            "baseline_policy": DEFAULT_SCORING_POLICY.to_dict(), "recommended_policy": None,
        }

    candidates = policy_grid(weight_step)
    candidate_metrics = [(policy, metrics(train, policy)) for policy in candidates]
    selected, selected_train = min(candidate_metrics, key=lambda item: (
        float(item[1]["balanced_mae"]), -float(item[1]["spearman"]),
        -float(item[1]["within_15_rate"]), _policy_distance(item[0]),
    ))
    baseline_train = metrics(train, DEFAULT_SCORING_POLICY)
    baseline_validation = metrics(validation, DEFAULT_SCORING_POLICY)
    selected_validation = metrics(validation, selected)
    baseline_test = metrics(test, DEFAULT_SCORING_POLICY) if test else None
    selected_test = metrics(test, selected) if test else None
    test_gate = not test or (selected_test is not None and _quality_gate(selected_test))
    deployment_recommended = (
        selected != DEFAULT_SCORING_POLICY and _quality_gate(selected_validation)
        and float(selected_validation["balanced_mae"]) < float(baseline_validation["balanced_mae"])
        and test_gate
    )
    reason = (
        "human_continuous_validation_passed" if deployment_recommended
        else "sealed_test_gate_failed" if test and not test_gate
        else "baseline_already_best" if selected == DEFAULT_SCORING_POLICY
        else "continuous_score_acceptance_gate_not_met"
    )
    return {
        "candidate": candidate, "diagnostic_only": False,
        "deployment_recommended": deployment_recommended, "recommendation_reason": reason,
        "errors": [], "counts": counts, "classification_threshold_search": "not_run",
        "classification_note": "状态阈值保持默认值；本轮只调连续分权重。",
        "search": {
            "grid_size": len(candidates), "weight_step": weight_step,
            "confidence_shrink_grid": list(CONFIDENCE_SHRINK_GRID),
            "seed": seed, "validation_fraction": validation_fraction,
        },
        "acceptance_thresholds": {
            "balanced_mae_max": 12, "per_state_mae_max": 15,
            "spearman_min": 0.70, "within_15_rate_min": 0.80,
        },
        "baseline_policy": DEFAULT_SCORING_POLICY.to_dict(),
        "selected_policy": selected.to_dict(),
        "recommended_policy": selected.to_dict() if deployment_recommended else None,
        "baseline_train": _render_metrics(baseline_train),
        "selected_train": _render_metrics(selected_train),
        "baseline_validation": _render_metrics(baseline_validation),
        "selected_validation": _render_metrics(selected_validation),
        "validation_gate_met": _quality_gate(selected_validation),
        "test": {
            "gate_met": test_gate, "baseline": _render_metrics(baseline_test or {}),
            "selected": _render_metrics(selected_test or {}),
        } if test else None,
    }


def tune(
    rows: list[dict], *, candidate: str | None = None, validation_fraction: float = 0.25,
    seed: int = 20260819, weight_step: float = DEFAULT_WEIGHT_STEP,
) -> dict[str, dict[str, Any]]:
    candidate_names = sorted({
        str(row.get("candidate") or "unknown") for row in rows
        if not candidate or str(row.get("candidate") or "unknown") == candidate
    })
    observations, parse_errors = parse_observations(rows)
    by_candidate: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        if not candidate or observation.candidate == candidate:
            by_candidate[observation.candidate].append(observation)
    reports: dict[str, dict[str, Any]] = {}
    for name in candidate_names:
        source_rows = [row for row in rows if str(row.get("candidate") or "unknown") == name]
        forced = ["labels_not_human_ground_truth"] if any(_is_ai_reference(row) for row in source_rows) else []
        report = tune_candidate(
            by_candidate.get(name, []), validation_fraction=validation_fraction, seed=seed,
            weight_step=weight_step, forced_diagnostic_reasons=forced,
        )
        report["candidate"] = name
        warnings = [error for error in parse_errors if error.startswith(f"{name}/")]
        if warnings:
            report["parse_warnings"] = warnings[:50]
        reports[name] = report
    return reports


def _read_annotation_records(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    records: list[dict[str, Any]] = []
    paths = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    for item in paths:
        try:
            if item.suffix.lower() == ".jsonl":
                payloads = [json.loads(line) for line in item.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                payload = json.loads(item.read_text(encoding="utf-8"))
                payloads = payload if isinstance(payload, list) else [payload]
            records.extend(payload for payload in payloads if isinstance(payload, dict))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return {str(record.get("sample_id")): record for record in records if str(record.get("sample_id") or "").strip()}


def _merge_annotations(rows: list[dict], annotations: Mapping[str, dict[str, Any]]) -> list[dict]:
    human_fields = {
        "human_review", "human_label", "expected_state", "human_annotation_complete",
        "human_goal_relevance", "human_task_evidence", "human_context_fit",
        "human_distraction_level", "human_overall_score", "annotation_confidence",
        "scoring_rubric_version", "label_source", "label_status", "split",
        "sequence_id", "source_group", "perceptual_group", "content_sha256",
    }
    merged_rows: list[dict] = []
    for row in rows:
        merged = dict(row)
        annotation = annotations.get(str(row.get("sample_id") or ""), {})
        for field in human_fields:
            if field in annotation:
                merged[field] = annotation[field]
        merged_rows.append(merged)
    return merged_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, default=Path("evaluation/screenshots"))
    parser.add_argument("--candidate")
    parser.add_argument("--output", type=Path, default=Path("evaluation/scoring_tuning_report.json"))
    parser.add_argument("--policy-output", type=Path)
    parser.add_argument("--validation-fraction", type=float, default=0.25)
    parser.add_argument("--weight-step", type=float, default=DEFAULT_WEIGHT_STEP)
    parser.add_argument("--seed", type=int, default=20260819)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = _merge_annotations(rows, _read_annotation_records(args.annotations))
    reports = tune(
        rows, candidate=args.candidate, validation_fraction=args.validation_fraction,
        seed=args.seed, weight_step=args.weight_step,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(reports, ensure_ascii=False, indent=2)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.policy_output:
        if len(reports) != 1:
            raise SystemExit("--policy-output 需要用 --candidate 唯一指定一个候选")
        report = next(iter(reports.values()))
        policy = report.get("recommended_policy")
        if report.get("diagnostic_only") or not report.get("deployment_recommended") or not policy:
            print("未生成策略文件：只有完整人工连续分通过验收门槛后才能输出可部署策略。")
            return 2
        args.policy_output.parent.mkdir(parents=True, exist_ok=True)
        args.policy_output.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 2 if not reports or all(report["diagnostic_only"] for report in reports.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
