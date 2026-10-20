"""Shared shop and den operations for browser and native clients."""
from __future__ import annotations

from collections.abc import Mapping

from app.services.shop_catalog import DEN_ITEMS, SHOP_PRICES, normalise_den_config
from app.services.user_service import get_user, mutate_user


class DenOperationError(ValueError):
    """A stable business error that API layers can translate for their clients."""


def _serialize_state(data: dict) -> dict:
    owned = set(data.get("unlocked_items", []))
    return {
        "points": int(data.get("total_points", 0) or 0),
        "items": [
            {
                "id": str(item["id"]),
                "name": str(item["name"]),
                "price": int(item["price"]),
                "description": str(item["desc"]),
                "scene_group": str(item["scene_group"]),
                "scene_slot": str(item["scene_slot"]),
                "owned": item["id"] in owned,
            }
            for item in DEN_ITEMS
        ],
        "config": normalise_den_config(data.get("current_den"), owned),
    }


def get_den_state(username: str) -> dict:
    return _serialize_state(get_user(username))


def exchange_furniture(username: str, item_id: object) -> dict:
    if not isinstance(item_id, str) or item_id not in SHOP_PRICES:
        raise DenOperationError("invalid_item")

    price = SHOP_PRICES[item_id]

    def exchange(data: dict) -> None:
        if item_id in data["unlocked_items"]:
            raise DenOperationError("already_owned")
        if data["total_points"] < price:
            raise DenOperationError("insufficient_points")
        data["total_points"] -= price
        data["unlocked_items"].append(item_id)
        if item_id not in data["den_items"]:
            data["den_items"].append(item_id)

    saved, _ = mutate_user(username, exchange)
    return _serialize_state(saved)


def save_den_config(username: str, value: Mapping[str, object] | object) -> dict:
    def save(data: dict) -> None:
        data["current_den"] = normalise_den_config(
            value,
            data.get("unlocked_items", []),
        )

    saved, _ = mutate_user(username, save)
    return _serialize_state(saved)
