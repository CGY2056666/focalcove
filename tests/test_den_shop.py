from __future__ import annotations

from app.services.shop_catalog import (
    DECORATION_ITEM_IDS,
    SHOP_ITEMS,
    SHOP_PRICES,
    list_den_items,
    normalise_den_config,
)
from app.services.user_service import get_user, save_user


def test_catalog_keeps_all_decor_and_preview_rewards_with_layout_metadata():
    furniture = [item for item in SHOP_ITEMS if item["type"] == "furniture"]
    rewards = [item for item in SHOP_ITEMS if item["type"] == "utility"]

    assert len(furniture) == 10
    assert len(rewards) == 10
    assert {item["id"] for item in furniture} == set(SHOP_PRICES)
    assert "desk_lamp" in DECORATION_ITEM_IDS
    assert next(item for item in furniture if item["id"] == "desk_lamp")["name"] == "阅读落地灯"
    assert all(item.get("scene_group") for item in SHOP_ITEMS)
    assert all(item.get("scene_slot") for item in SHOP_ITEMS)
    assert all(isinstance(item.get("thumbnail_scale"), float) for item in SHOP_ITEMS)
    assert len(list_den_items()) == 12


def test_old_den_config_gets_day_ambience_and_unowned_items_are_removed():
    result = normalise_den_config(
        {
            "floor": "wood_floor",
            "wall": "star_wall",
            "decoration": ["cushion", "study_desk", "cushion", "unknown"],
        },
        ["base_floor", "base_wall", "wood_floor", "cushion"],
    )

    assert result == {
        "floor": "wood_floor",
        "wall": "base_wall",
        "decoration": ["cushion"],
        "ambience": "day",
    }


def test_den_update_only_saves_owned_valid_items_and_returns_canonical_config(app, auth_client):
    with app.app_context():
        data = get_user("testuser")
        data["unlocked_items"].extend(["wood_floor", "cushion"])
        save_user("testuser", data)

    response = auth_client.post(
        "/api/den/update",
        json={
            "den_config": {
                "floor": "wood_floor",
                "wall": "star_wall",
                "decoration": ["study_desk", "cushion", "cushion", "made_up"],
                "ambience": "night",
                "unexpected": "discarded",
            }
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "den_config": {
            "floor": "wood_floor",
            "wall": "base_wall",
            "decoration": ["cushion"],
            "ambience": "night",
        },
    }
    with app.app_context():
        assert get_user("testuser")["current_den"] == response.get_json()["den_config"]


def test_den_and_shop_reject_non_object_json_without_internal_error(auth_client):
    den_response = auth_client.post("/api/den/update", json=["not", "an", "object"])
    shop_response = auth_client.post("/api/shop/exchange", json=["desk_lamp"])

    assert den_response.status_code == 400
    assert den_response.get_json() == {"error": "小窝配置无效"}
    assert shop_response.status_code == 400
    assert shop_response.get_json() == {"error": "无效的商品"}


def test_exchange_adds_item_to_both_owned_lists_and_cannot_charge_twice(app, auth_client):
    with app.app_context():
        data = get_user("testuser")
        data["total_points"] = 1000
        save_user("testuser", data)

    first = auth_client.post("/api/shop/exchange", json={"item_id": "desk_lamp"})
    second = auth_client.post("/api/shop/exchange", json={"item_id": "desk_lamp"})

    assert first.status_code == 200
    assert first.get_json()["remaining_points"] == 650
    assert second.status_code == 400
    with app.app_context():
        saved = get_user("testuser")
        assert saved["total_points"] == 650
        assert "desk_lamp" in saved["unlocked_items"]
        assert "desk_lamp" in saved["den_items"]


def test_den_and_shop_pages_expose_new_interactions_without_removing_rewards(auth_client):
    den_html = auth_client.get("/den").get_data(as_text=True)
    shop_html = auth_client.get("/shop").get_data(as_text=True)

    assert 'data-ambience="day"' in den_html
    assert 'data-ambience="night"' in den_html
    assert 'data-scene-slot="desk-side"' in den_html
    assert "保存失败，已恢复原搭配" in den_html
    assert "0 件家具 · 2 种基础样式" in den_html

    reward_ids = {item["id"] for item in SHOP_ITEMS if item["type"] == "utility"}
    assert all(f'data-item-id="{item_id}"' in shop_html for item_id in reward_ids)
    assert shop_html.count("暂未开放") == 1
    assert "window.location.reload" not in shop_html
    assert "👑" not in shop_html
    assert 'id="rewardPrevious"' in shop_html
    assert 'id="rewardNext"' in shop_html
