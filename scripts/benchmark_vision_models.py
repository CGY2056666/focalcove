"""按同一份脱敏清单比较视觉评分候选。

该脚本会产生真实 API 费用，只在显式运行时调用外部模型；pytest 不会导入执行 main。
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from focus_engine.config import DEFAULT_CONFIG
from focus_engine.goal_profiles import build_goal_profile
from focus_engine.pipeline import FocusAnalyzer
from focus_engine.scoring import finalize_frame_scores


CANDIDATES = {
    "siliconflow-qwen3.5": {
        "provider": "siliconflow",
        "model": "Qwen/Qwen3.5-35B-A3B",
    },
    "siliconflow-qwen3.6": {
        "provider": "siliconflow",
        "model": "Qwen/Qwen3.6-35B-A3B",
    },
    "bailian-qwen3.7-flash": {
        "provider": "bailian",
        "model": "qwen3.7-flash",
    },
    "bailian-qwen3.8-27b": {
        "provider": "bailian",
        "model": "qwen3.8-27b",
    },
}


def _config_for(candidate: str, *, timeout_seconds: float | None = None):
    spec = CANDIDATES[candidate]
    overrides = {}
    if timeout_seconds is not None:
        overrides["siliconflow_timeout_seconds"] = float(timeout_seconds)
    if spec["provider"] == "bailian":
        return replace(
            DEFAULT_CONFIG,
            vision_provider="bailian",
            bailian_model=spec["model"],
            **overrides,
        )
    return replace(
        DEFAULT_CONFIG,
        vision_provider="siliconflow",
        siliconflow_model=spec["model"],
        **overrides,
    )


def _read_manifest(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_candidate(
    candidate: str,
    rows: list[dict],
    *,
    repeats: int = 1,
    timeout_seconds: float | None = None,
    skip_keys: set[tuple[str, str, int]] | None = None,
    on_result: Callable[[dict], None] | None = None,
) -> list[dict]:
    repeats = max(1, int(repeats))
    results: list[dict] = []
    for repeat_index in range(repeats):
        # 每轮使用新实例，确保同一截图不会命中进程内模型缓存。
        candidate_config = _config_for(candidate, timeout_seconds=timeout_seconds)
        analyzer = FocusAnalyzer(candidate_config)
        status = analyzer.scoring_status()
        if not status.get("configured"):
            raise RuntimeError(f"{candidate} 未配置 API Key")

        for row in rows:
            image_path = Path(str(row["image"]))
            sample_id = str(
                row.get("sample_id")
                or f"{row.get('expected_state') or 'unknown'}/{image_path.name}"
            )
            if skip_keys and (candidate, sample_id, repeat_index + 1) in skip_keys:
                continue
            started = time.perf_counter()
            frame = analyzer.analyze_frame(
                build_goal_profile(str(row.get("goal") or "完成当前专注任务")),
                image_path.name,
                image_path.read_bytes(),
                frame_id=image_path.stem,
                captured_at=time.time(),
            )
            # 冻结模型原始四维输出；模型协议不再生成总分，调参只能读取这些维度。
            raw_breakdown = dict(getattr(frame, "score_breakdown", {}) or {})
            raw_model = {
                "category_type": str(
                    raw_breakdown.get("model_category_type")
                    or getattr(frame, "category_type", "neutral")
                    or "neutral"
                ),
                "category_label": str(
                    raw_breakdown.get("model_category_label")
                    or getattr(frame, "category_label", "")
                    or ""
                ),
                "score_version": str(getattr(frame, "score_version", "legacy-v1") or "legacy-v1"),
                "score_confidence": float(getattr(frame, "score_confidence", 0.0)),
                "confidence": float(getattr(frame, "score_confidence", 0.0)),
                "goal_relevance": raw_breakdown.get(
                    "model_goal_relevance_level",
                    raw_breakdown.get("goal_relevance_level"),
                ),
                "task_evidence": raw_breakdown.get(
                    "model_task_evidence_level",
                    raw_breakdown.get("task_evidence_level"),
                ),
                "context_fit": raw_breakdown.get(
                    "model_context_fit_level",
                    raw_breakdown.get("context_fit_level"),
                ),
                "distraction_level": raw_breakdown.get(
                    "model_distraction_level",
                    raw_breakdown.get("distraction_level"),
                ),
                "goal_relevance_score": None,
                "task_evidence_score": None,
                "context_fit_score": None,
                "distraction_score": None,
                "reason": str(
                    raw_breakdown.get("model_reason")
                    or getattr(frame, "base_decision_reason", "")
                    or getattr(frame, "decision_reason", "")
                    or ""
                ),
            }
            if raw_model["goal_relevance"] is not None:
                raw_model["goal_relevance_score"] = float(raw_model["goal_relevance"]) * 25.0
            if raw_model["task_evidence"] is not None:
                raw_model["task_evidence_score"] = float(raw_model["task_evidence"]) * 25.0
            if raw_model["context_fit"] is not None:
                raw_model["context_fit_score"] = float(raw_model["context_fit"]) * 25.0
            if raw_model["distraction_level"] is not None:
                raw_model["distraction_score"] = round(
                    float(raw_model["distraction_level"]) / 4.0,
                    3,
                )
            analyzer_policy = getattr(analyzer, "scoring_policy", None)
            if analyzer_policy is None:
                finalize_frame_scores([frame])
            else:
                finalize_frame_scores([frame], policy=analyzer_policy)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            postprocessed = frame.to_dict()
            stable_state = frame.state
            raw_state = str(getattr(frame, "raw_state", "") or postprocessed.get("raw_state") or stable_state)
            results.append(
                {
                    "candidate": candidate,
                    "provider": str(status.get("provider") or CANDIDATES[candidate]["provider"]),
                    "model": str(status.get("model") or CANDIDATES[candidate]["model"]),
                    "model_timeout_seconds": float(
                        candidate_config.siliconflow_timeout_seconds
                    ),
                    "sample_id": sample_id,
                    "image": image_path.name,
                    "expected_state": row.get("expected_state"),
                    "label_source": row.get("label_source"),
                    "label_status": row.get("label_status"),
                    "split": row.get("split"),
                    "sequence_id": row.get("sequence_id"),
                    "sequence_index": row.get("sequence_index"),
                    "source_group": row.get("source_group"),
                    "perceptual_group": row.get("perceptual_group"),
                    "repeat_index": repeat_index + 1,
                    "repeat_count": repeats,
                    "predicted_state": raw_state,
                    "raw_state": raw_state,
                    "raw_category": raw_model["category_type"],
                    "raw_confidence": raw_model["confidence"],
                    "raw_goal_relevance": raw_model["goal_relevance"],
                    "raw_task_evidence": raw_model["task_evidence"],
                    "raw_context_fit": raw_model["context_fit"],
                    "raw_distraction_level": raw_model["distraction_level"],
                    "raw_goal_relevance_score": raw_model["goal_relevance_score"],
                    "raw_task_evidence_score": raw_model["task_evidence_score"],
                    "raw_context_fit_score": raw_model["context_fit_score"],
                    "raw_distraction_score": raw_model["distraction_score"],
                    "stable_state": stable_state,
                    "score_version": str(getattr(frame, "score_version", "legacy-v1") or "legacy-v1"),
                    "raw_focus_score": getattr(frame, "raw_focus_score", None),
                    "focus_score": frame.focus_score,
                    "confidence": frame.score_confidence,
                    "reason": frame.decision_reason or frame.fallback_reason or frame.warning or "",
                    "structured_ok": not frame.review_required,
                    "latency_ms": latency_ms,
                    "error": frame.warning or frame.fallback_reason or "",
                    "raw": raw_model,
                    "postprocessed": postprocessed,
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False))
            if on_result:
                on_result(results[-1])
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/vision_manifest.jsonl"))
    parser.add_argument("--candidate", choices=["all", *CANDIDATES], default="all")
    parser.add_argument("--output", type=Path, default=Path("evaluation/vision_results.jsonl"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        help="仅用于离线评测的模型套接字超时；实时系统仍受配置中的 7 秒上限约束。",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if args.timeout_seconds is not None and not 0.1 <= args.timeout_seconds <= 60.0:
        parser.error("--timeout-seconds 必须在 0.1 到 60 之间")

    rows = _read_manifest(args.manifest)
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]
    if not rows:
        raise SystemExit("评测清单为空，请先运行 scripts/build_vision_manifest.py")
    candidates = list(CANDIDATES) if args.candidate == "all" else [args.candidate]
    missing_keys = [
        candidate
        for candidate in candidates
        if not (
            _config_for(candidate).bailian_api_key
            if CANDIDATES[candidate]["provider"] == "bailian"
            else _config_for(candidate).siliconflow_api_key
        )
    ]
    if missing_keys:
        raise SystemExit("以下候选未配置 API Key：" + ", ".join(missing_keys))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed: set[tuple[str, str, int]] = set()
    if args.resume and args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            previous = json.loads(line)
            completed.add(
                (
                    str(previous.get("candidate") or ""),
                    str(previous.get("sample_id") or previous.get("image") or ""),
                    int(previous.get("repeat_index") or 1),
                )
            )
    mode = "a" if args.resume else "w"
    with args.output.open(mode, encoding="utf-8") as sink:
        def persist(result: dict) -> None:
            sink.write(json.dumps(result, ensure_ascii=False) + "\n")
            sink.flush()
            completed.add(
                (
                    str(result.get("candidate") or ""),
                    str(result.get("sample_id") or result.get("image") or ""),
                    int(result.get("repeat_index") or 1),
                )
            )

        for candidate in candidates:
            run_candidate(
                candidate,
                rows,
                repeats=max(1, args.repeats),
                timeout_seconds=args.timeout_seconds,
                skip_keys=completed,
                on_result=persist,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
