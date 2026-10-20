"""OCR 文本清洗和质量评估"""
from __future__ import annotations

import re

from .utils import clamp, normalize_spaces

OCR_REPLACEMENTS = {
    "1earn": "learn",
    "w0rd": "word",
    "examp1e": "example",
    "translatlon": "translation",
    "transiation": "translation",
    "defination": "definition",
    "definitlon": "definition",
    "meanlng": "meaning",
    "pronunciatlon": "pronunciation",
    "sentencc": "sentence",
    "gramrnar": "grammar",
    "1istening": "listening",
    "0f": "of",
    "th1s": "this",
}


def clean_ocr_text(text: str) -> str:
    text = normalize_spaces(text.replace("\r", "\n"))
    lines: list[str] = []
    seen: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 2:
            continue
        if re.fullmatch(r"[\W_]+", line):
            continue
        for source, target in OCR_REPLACEMENTS.items():
            line = re.sub(source, target, line, flags=re.IGNORECASE)
        line = re.sub(r"[^\S\n]{2,}", " ", line)
        if len(re.findall(r"[一-鿿A-Za-z0-9]", line)) < 2:
            continue
        if line not in seen:
            seen.add(line)
            lines.append(line)

    merged: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if len(line) <= 6 and len(lines) > 1:
            buffer.append(line)
            continue
        if buffer:
            merged.append(" ".join(buffer + [line]).strip())
            buffer = []
        else:
            merged.append(line)
    if buffer:
        merged.append(" ".join(buffer).strip())

    return "\n".join(item for item in merged if item)


def score_ocr_quality(text: str) -> float:
    if not text:
        return 0.0

    meaningful_chars = len(re.findall(r"[一-鿿A-Za-z0-9]", text))
    total_chars = max(len(text), 1)
    meaningful_ratio = meaningful_chars / total_chars
    symbol_ratio = len(re.findall(r"[^\w\s一-鿿]", text)) / total_chars
    useful_lines = sum(1 for line in text.splitlines() if len(line.strip()) >= 4)
    duplicate_lines = len(text.splitlines()) - len(
        {line.strip() for line in text.splitlines() if line.strip()}
    )

    score = (
        0.33 * clamp(meaningful_chars / 90.0)
        + 0.33 * clamp(meaningful_ratio)
        + 0.22 * clamp(useful_lines / 4.0)
        + 0.12 * clamp(1 - symbol_ratio - min(duplicate_lines / 6.0, 0.2))
    )
    return round(clamp(score), 3)
