from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.smoke_mobile_api import (
    SmokeFailure,
    assert_den_payload,
    assert_error_envelope,
    bootstrap_path,
    normalize_base_url,
)


def test_smoke_url_requires_https_and_normalizes_trailing_slash() -> None:
    assert normalize_base_url(" https://your-domain.example ") == "https://your-domain.example/"
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://your-domain.example/")


def test_smoke_url_rejects_credentials_query_and_fragment() -> None:
    for value in (
        "https://user:pass@your-domain.example/",
        "https://your-domain.example/?token=secret",
        "https://your-domain.example/#mobile",
    ):
        with pytest.raises(ValueError):
            normalize_base_url(value)


def test_smoke_error_envelope_validation() -> None:
    assert_error_envelope(
        {
            "error": {
                "code": "invalid_token",
                "message": "expired",
                "retryable": False,
            }
        },
        "invalid_token",
    )
    with pytest.raises(SmokeFailure):
        assert_error_envelope({"error": "invalid_token"})


def test_bootstrap_path_percent_encodes_chinese_goal() -> None:
    path = bootstrap_path("上线冒烟检查")

    assert "上线冒烟检查" not in path
    assert parse_qs(urlsplit(path).query) == {"goal": ["上线冒烟检查"]}


def test_smoke_den_payload_only_accepts_real_room_catalog() -> None:
    items = [
        {
            "id": item_id,
            "name": item_id,
            "price": 0,
            "description": "",
            "scene_group": "decoration",
            "scene_slot": "",
            "owned": item_id in {"base_floor", "base_wall"},
        }
        for item_id in (
            "base_floor",
            "base_wall",
            "wood_floor",
            "star_wall",
            "study_desk",
            "bookshelf",
            "cat_nest",
            "desk_lamp",
            "window_curtain",
            "plant_pot",
            "cushion",
            "wall_clock",
        )
    ]
    assert_den_payload(
        {
            "points": 0,
            "items": items,
            "config": {
                "floor": "base_floor",
                "wall": "base_wall",
                "decoration": [],
                "ambience": "day",
            },
        }
    )

    with pytest.raises(SmokeFailure, match="12 real"):
        assert_den_payload({"points": 0, "items": items[:-1], "config": {}})
