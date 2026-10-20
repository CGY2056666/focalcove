"""Compare paired vision benchmark runs that differ only in timeout budget."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any


DIMENSION_FIELDS = (
    "raw_goal_relevance",
    "raw_task_evidence",
    "raw_context_fit",
    "raw_distraction_level",
)


def _read(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _latency_summary(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    values = [float(row.get("latency_ms") or 0.0) for row in rows]
    return {
        "structured": sum(row.get("structured_ok") is True for row in rows),
        "timeouts": sum("timed out" in str(row.get("error") or "") for row in rows),
        "median_ms": round(median(values), 1) if values else 0.0,
        "p95_ms": round(_percentile(values, 0.95), 1),
        "max_ms": round(max(values), 1) if values else 0.0,
        "over_7s": sum(value > 7000.0 for value in values),
        "over_8s": sum(value > 8000.0 for value in values),
        "over_10s": sum(value > 10000.0 for value in values),
    }


def compare(
    baseline_rows: list[dict[str, Any]],
    extended_rows: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    if limit is not None:
        baseline_rows = baseline_rows[: max(0, limit)]
    extended_by_id = {
        str(row.get("sample_id") or row.get("image") or ""): row
        for row in extended_rows
    }
    pairs = [
        (row, extended_by_id[sample_id])
        for row in baseline_rows
        if (sample_id := str(row.get("sample_id") or row.get("image") or ""))
        in extended_by_id
    ]
    baseline = [pair[0] for pair in pairs]
    extended = [pair[1] for pair in pairs]
    previous_timeouts = [
        pair for pair in pairs if pair[0].get("structured_ok") is not True
    ]
    recovered_latencies = [
        float(after.get("latency_ms") or 0.0)
        for _, after in previous_timeouts
        if after.get("structured_ok") is True
    ]
    both_success = [
        pair
        for pair in pairs
        if pair[0].get("structured_ok") is True
        and pair[1].get("structured_ok") is True
    ]
    score_differences = [
        abs(float(before["focus_score"]) - float(after["focus_score"]))
        for before, after in both_success
        if before.get("focus_score") is not None and after.get("focus_score") is not None
    ]
    state_matches = sum(
        str(before.get("raw_state")) == str(after.get("raw_state"))
        for before, after in both_success
    )
    same_dimensions = sum(
        tuple(before.get(field) for field in DIMENSION_FIELDS)
        == tuple(after.get(field) for field in DIMENSION_FIELDS)
        for before, after in both_success
    )
    transitions = Counter(
        f"{before.get('raw_state')}->{after.get('raw_state')}"
        for before, after in both_success
    )
    return {
        "paired_samples": len(pairs),
        "baseline": _latency_summary(baseline),
        "extended_timeout": _latency_summary(extended),
        "previous_timeouts": {
            "count": len(previous_timeouts),
            "recovered": len(recovered_latencies),
            "median_ms_after_recovery": (
                round(median(recovered_latencies), 1) if recovered_latencies else 0.0
            ),
            "p95_ms_after_recovery": round(_percentile(recovered_latencies, 0.95), 1),
            "max_ms_after_recovery": (
                round(max(recovered_latencies), 1) if recovered_latencies else 0.0
            ),
        },
        "repeat_variability": {
            "both_success": len(both_success),
            "same_state": state_matches,
            "state_agreement": (
                round(state_matches / len(both_success), 4) if both_success else 0.0
            ),
            "same_four_dimensions": same_dimensions,
            "dimension_exact_agreement": (
                round(same_dimensions / len(both_success), 4) if both_success else 0.0
            ),
            "score_abs_diff_median": (
                round(median(score_differences), 1) if score_differences else 0.0
            ),
            "score_abs_diff_p95": round(_percentile(score_differences, 0.95), 1),
            "state_transitions": dict(sorted(transitions.items())),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("extended", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(_read(args.baseline), _read(args.extended), limit=args.limit)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
