"""从按状态分组的脱敏截图生成视觉模型评测清单。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


STATES = ("focused", "uncertain", "distracted", "unscorable")
STABLE_STATES = ("focused", "uncertain", "distracted")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_SAMPLE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _normalize_goal(goal: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(goal or ""))
    return " ".join(normalized.split()).casefold()


def _expected_sample_id(content_sha256: str, goal: object) -> str:
    identity = f"{content_sha256}\0{_normalize_goal(goal)}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def build_manifest(
    source: Path,
    *,
    issues: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    reported_issues = issues if issues is not None else []
    for state in STATES:
        state_dir = source / state
        if not state_dir.exists():
            continue
        for image in sorted(state_dir.iterdir()):
            if not image.is_file() or image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            metadata_path = image.with_suffix(".json")
            display_name = f"{state}/{image.name}"
            if not metadata_path.exists():
                reported_issues.append(f"{display_name}: 缺少同名人工复核 JSON")
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                reported_issues.append(f"{display_name}: JSON 无法读取（{exc}）")
                continue
            if not isinstance(metadata, dict):
                reported_issues.append(f"{display_name}: JSON 根节点不是对象")
                continue

            try:
                image_bytes = image.read_bytes()
            except OSError as exc:
                reported_issues.append(f"{display_name}: 图片无法读取（{exc}）")
                continue
            actual_content_sha256 = hashlib.sha256(image_bytes).hexdigest()
            content_sha256 = str(metadata.get("content_sha256") or "").strip().lower()
            sample_id = str(metadata.get("sample_id") or "").strip().lower()
            goal = str(metadata.get("goal") or "")
            validation_errors: list[str] = []
            if metadata.get("human_review") is not True:
                validation_errors.append("human_review 不为 true")
            if str(metadata.get("human_label") or "").strip().lower() != state:
                validation_errors.append("human_label 与目录不一致")
            if str(metadata.get("expected_state") or "").strip().lower() != state:
                validation_errors.append("expected_state 与目录不一致")
            if content_sha256 != actual_content_sha256:
                validation_errors.append("content_sha256 与图片不一致")
            if not _SAMPLE_ID_PATTERN.fullmatch(sample_id):
                validation_errors.append("sample_id 非法")
            elif sample_id != _expected_sample_id(actual_content_sha256, goal):
                validation_errors.append("sample_id 与图片及目标不一致")
            if image.stem != sample_id:
                validation_errors.append("图片文件名与 sample_id 不一致")
            if str(metadata.get("image_file") or "") != image.name:
                validation_errors.append("image_file 与图片文件名不一致")
            if validation_errors:
                reported_issues.append(f"{display_name}: " + "；".join(validation_errors))
                continue

            rows.append(
                {
                    "sample_id": sample_id,
                    "image": image.resolve().as_posix(),
                    "goal": goal,
                    "expected_state": state,
                    "note": str(metadata.get("note") or ""),
                    "split": str(metadata.get("split") or ""),
                    "sequence_id": str(metadata.get("sequence_id") or ""),
                    "sequence_index": metadata.get("sequence_index"),
                    "source_group": str(metadata.get("source_group") or ""),
                    "perceptual_group": str(metadata.get("perceptual_group") or ""),
                    "content_sha256": content_sha256,
                }
            )
    return rows


def manifest_sample_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count effective semantic samples without letting exact hash groups inflate gates."""

    raw_counts = {
        state: sum(row.get("expected_state") == state for row in rows)
        for state in STATES
    }
    grouped_states: dict[tuple[str, str], set[str]] = {}
    for index, row in enumerate(rows):
        state = str(row.get("expected_state") or "").strip().lower()
        if state not in STATES:
            continue
        goal = _normalize_goal(row.get("goal"))
        fingerprint = str(
            row.get("perceptual_group")
            or row.get("content_sha256")
            or row.get("sample_id")
            or row.get("image")
            or f"row-{index}"
        ).strip().lower()
        grouped_states.setdefault((goal, fingerprint), set()).add(state)

    conflicts = {
        key: states
        for key, states in grouped_states.items()
        if len(states) > 1
    }
    effective_counts = {state: 0 for state in STATES}
    for key, states in grouped_states.items():
        if key in conflicts:
            # 同一目标与图像单元出现冲突标签时，不给任何类别增加有效样本数。
            continue
        effective_counts[next(iter(states))] += 1

    return {
        "raw_total": len(rows),
        "effective_total": sum(effective_counts.values()),
        "raw_counts": raw_counts,
        "effective_counts": effective_counts,
        "label_conflict_count": len(conflicts),
    }


def effective_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row per consistent semantic image unit; omit conflicting units."""

    grouped: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    order: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        state = str(row.get("expected_state") or "").strip().lower()
        goal = _normalize_goal(row.get("goal"))
        fingerprint = str(
            row.get("perceptual_group")
            or row.get("content_sha256")
            or row.get("sample_id")
            or row.get("image")
            or f"row-{index}"
        ).strip().lower()
        key = (goal, fingerprint)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((state, row))

    effective: list[dict[str, Any]] = []
    for key in order:
        candidates = grouped[key]
        states = {state for state, _ in candidates}
        if len(states) != 1:
            continue
        effective.append(candidates[0][1])
    return effective


def manifest_requirement_failures(
    rows: list[dict[str, Any]],
    *,
    minimum_total: int = 80,
    minimum_per_stable_state: int = 20,
) -> list[str]:
    statistics = manifest_sample_statistics(rows)
    counts = statistics["effective_counts"]
    failures: list[str] = []
    if statistics["effective_total"] < minimum_total:
        failures.append(f"总样本少于 {minimum_total} 张")
    failures.extend(
        f"{state} 少于 {minimum_per_stable_state} 张"
        for state in STABLE_STATES
        if counts[state] < minimum_per_stable_state
    )
    if statistics["label_conflict_count"]:
        failures.append(
            f"存在 {statistics['label_conflict_count']} 个近重复单元标签冲突"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("evaluation/screenshots"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/vision_manifest.jsonl"))
    parser.add_argument("--minimum", type=int, default=80)
    parser.add_argument("--minimum-per-stable-state", type=int, default=20)
    args = parser.parse_args()

    issues: list[str] = []
    rows = build_manifest(args.source, issues=issues)
    effective_rows = effective_manifest_rows(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in effective_rows),
        encoding="utf-8",
    )
    statistics = manifest_sample_statistics(rows)
    counts = {
        state: {
            "raw": statistics["raw_counts"][state],
            "effective": statistics["effective_counts"][state],
        }
        for state in STATES
    }
    print(
        json.dumps(
            {
                "total": statistics["raw_total"],
                "raw_total": statistics["raw_total"],
                "effective_total": statistics["effective_total"],
                "counts": counts,
                "raw_counts": statistics["raw_counts"],
                "effective_counts": statistics["effective_counts"],
                "label_conflict_count": statistics["label_conflict_count"],
                "invalid_sample_count": len(issues),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    if issues:
        print("已跳过异常评测样本：" + "；".join(issues) + "。")
    failures = manifest_requirement_failures(
        rows,
        minimum_total=args.minimum,
        minimum_per_stable_state=args.minimum_per_stable_state,
    )
    if failures:
        print("评测集尚未达到正式门槛：" + "；".join(failures) + "。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
