from scripts.compare_timeout_results import compare


def _row(sample_id, *, ok, latency, state="uncertain", score=50, dimensions=(2, 2, 2, 2)):
    return {
        "sample_id": sample_id,
        "structured_ok": ok,
        "latency_ms": latency,
        "error": "" if ok else "The read operation timed out",
        "raw_state": state if ok else "unscorable",
        "focus_score": score if ok else 0,
        "raw_goal_relevance": dimensions[0] if ok else None,
        "raw_task_evidence": dimensions[1] if ok else None,
        "raw_context_fit": dimensions[2] if ok else None,
        "raw_distraction_level": dimensions[3] if ok else None,
    }


def test_compare_reports_recovery_and_repeat_variability():
    baseline = [
        _row("a", ok=False, latency=8100),
        _row("b", ok=True, latency=4000, state="focused", score=90, dimensions=(4, 3, 4, 0)),
    ]
    extended = [
        _row("a", ok=True, latency=9000, state="distracted", score=20, dimensions=(0, 1, 1, 4)),
        _row("b", ok=True, latency=4500, state="focused", score=85, dimensions=(4, 3, 4, 0)),
    ]

    result = compare(baseline, extended)

    assert result["paired_samples"] == 2
    assert result["baseline"]["structured"] == 1
    assert result["extended_timeout"]["structured"] == 2
    assert result["previous_timeouts"]["recovered"] == 1
    assert result["repeat_variability"]["state_agreement"] == 1.0
    assert result["repeat_variability"]["dimension_exact_agreement"] == 1.0
    assert result["repeat_variability"]["score_abs_diff_median"] == 5.0
