from __future__ import annotations

import cv2
import numpy as np

from focus_engine import DEFAULT_CONFIG, FocusAnalyzer
from focus_engine.goal_profiles import build_goal_profile
from focus_engine.image_utils import average_hash
from focus_engine.models import FrameAnalysis
from focus_engine.pipeline import is_protected_blank_image


def test_protected_blank_detector_is_conservative_for_dark_interfaces() -> None:
    black = np.zeros((160, 240, 3), dtype=np.uint8)
    compression_noise = np.random.default_rng(7).integers(
        0, 5, size=(160, 240, 3), dtype=np.uint8
    )
    dark_interface = np.full((160, 240, 3), 3, dtype=np.uint8)
    dark_interface[50:58, 35:205] = 120
    dark_interface[85:93, 55:185] = 80

    assert is_protected_blank_image(black) is True
    assert is_protected_blank_image(compression_noise) is True
    assert is_protected_blank_image(dark_interface) is False


def test_protected_blank_frame_never_reaches_vision_model(monkeypatch) -> None:
    analyzer = FocusAnalyzer(DEFAULT_CONFIG)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("protected frame reached the vision model")

    monkeypatch.setattr(analyzer.vlm, "analyze", fail_if_called)
    encoded, buffer = cv2.imencode(".jpg", np.zeros((120, 180, 3), dtype=np.uint8))
    assert encoded

    previous = FrameAnalysis(
        index=0,
        filename="previous.jpg",
        image_valid=True,
        state="focused",
        thumbnail_hash=average_hash(
            np.zeros((120, 180, 3), dtype=np.uint8),
            DEFAULT_CONFIG.thumbnail_hash_size,
        ),
        captured_at=100.0,
    )
    result = analyzer.analyze_frame(
        build_goal_profile("学习 Python"),
        "protected.jpg",
        buffer.tobytes(),
        frame_id="protected-1",
        captured_at=120.0,
        previous_frame=previous,
        last_model_analysis_at=100.0,
    )

    assert called is False
    assert result.state == "unscorable"
    assert result.review_required is True
    assert result.source == "protected_content"
    assert result.category_type == "neutral"
    assert result.focus_score == 0.0
    assert result.duplicate_of is None
