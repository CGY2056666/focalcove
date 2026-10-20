"""原型商城与小窝装扮的唯一目录。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping


BASE_DEN_ITEMS: tuple[dict[str, object], ...] = (
    {
        "id": "base_floor",
        "name": "奶杏地板",
        "price": 0,
        "type": "base",
        "desc": "小窝自带的奶杏色地板",
        "scene_group": "floor",
        "scene_slot": "floor-surface",
        "thumbnail_scale": 0.9,
    },
    {
        "id": "base_wall",
        "name": "暖白墙面",
        "price": 0,
        "type": "base",
        "desc": "小窝自带的暖白色墙面",
        "scene_group": "wall",
        "scene_slot": "wall-surface",
        "thumbnail_scale": 0.9,
    },
)


SHOP_ITEMS: tuple[dict[str, object], ...] = (
    {
        "id": "wood_floor", "name": "实木地板", "price": 200, "type": "furniture",
        "desc": "铺一层温暖木纹", "scene_group": "floor", "scene_slot": "floor-surface",
        "thumbnail_scale": 0.92,
    },
    {
        "id": "star_wall", "name": "星空墙面", "price": 300, "type": "furniture",
        "desc": "让墙面亮起星光", "scene_group": "wall", "scene_slot": "wall-surface",
        "thumbnail_scale": 0.92,
    },
    {
        "id": "study_desk", "name": "学习书桌", "price": 500, "type": "furniture",
        "desc": "给阅读和写作留张桌子", "scene_group": "decoration", "scene_slot": "furniture-center",
        "thumbnail_scale": 1.08,
    },
    {
        "id": "bookshelf", "name": "落地书架", "price": 400, "type": "furniture",
        "desc": "把常看的书摆在手边", "scene_group": "decoration", "scene_slot": "furniture-left",
        "thumbnail_scale": 0.9,
    },
    {
        "id": "cat_nest", "name": "猫咪窝", "price": 600, "type": "furniture",
        "desc": "小窝里的安静陪伴", "scene_group": "decoration", "scene_slot": "floor-right",
        "thumbnail_scale": 1.02,
    },
    {
        "id": "desk_lamp", "name": "阅读落地灯", "price": 350, "type": "furniture",
        "desc": "独立摆放在桌侧的暖光落地灯", "scene_group": "decoration", "scene_slot": "desk-side",
        "thumbnail_scale": 0.88,
    },
    {
        "id": "window_curtain", "name": "暖色窗帘", "price": 280, "type": "furniture",
        "desc": "给窗边添一层暖色", "scene_group": "decoration", "scene_slot": "wall-right",
        "thumbnail_scale": 0.84,
    },
    {
        "id": "plant_pot", "name": "绿植角", "price": 150, "type": "furniture",
        "desc": "在房间一角放一点绿意", "scene_group": "decoration", "scene_slot": "floor-left",
        "thumbnail_scale": 0.82,
    },
    {
        "id": "cushion", "name": "舒适靠垫", "price": 120, "type": "furniture",
        "desc": "一只柔软的小靠垫", "scene_group": "decoration", "scene_slot": "floor-center",
        "thumbnail_scale": 1.0,
    },
    {
        "id": "wall_clock", "name": "简洁挂钟", "price": 200, "type": "furniture",
        "desc": "墙上的简洁挂钟", "scene_group": "decoration", "scene_slot": "wall-left",
        "thumbnail_scale": 0.76,
    },
    {
        "id": "premium_member_1m", "name": "高级会员（1 个月）", "price": 1000, "type": "utility",
        "desc": "一个月会员权益", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.88,
    },
    {
        "id": "premium_member_3m", "name": "高级会员（3 个月）", "price": 2500, "type": "utility",
        "desc": "三个月会员权益", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.88,
    },
    {
        "id": "coffee_voucher", "name": "咖啡券", "price": 300, "type": "utility",
        "desc": "一杯热咖啡", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.84,
    },
    {
        "id": "snack_combo", "name": "能量零食包", "price": 250, "type": "utility",
        "desc": "曲奇和小零食", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.9,
    },
    {
        "id": "bubble_tea", "name": "奶茶礼券", "price": 280, "type": "utility",
        "desc": "一杯奶茶", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.84,
    },
    {
        "id": "energy_drink", "name": "能量饮料", "price": 180, "type": "utility",
        "desc": "能量饮料一份", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.8,
    },
    {
        "id": "coupon_50", "name": "50 元优惠券", "price": 800, "type": "utility",
        "desc": "50 元优惠券奖励", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.92,
    },
    {
        "id": "coupon_100", "name": "100 元优惠券", "price": 1500, "type": "utility",
        "desc": "100 元优惠券奖励", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.92,
    },
    {
        "id": "book_credit", "name": "100 元书券", "price": 900, "type": "utility",
        "desc": "100 元购书奖励", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.86,
    },
    {
        "id": "music_membership_1m", "name": "音乐会员（1 个月）", "price": 600, "type": "utility",
        "desc": "一个月音乐会员", "scene_group": "reward", "scene_slot": "display", "thumbnail_scale": 0.86,
    },
)

DEN_ITEMS: tuple[dict[str, object], ...] = BASE_DEN_ITEMS + tuple(
    item for item in SHOP_ITEMS if item["type"] == "furniture"
)
DEN_ITEM_BY_ID: dict[str, dict[str, object]] = {
    str(item["id"]): item for item in DEN_ITEMS
}
FLOOR_ITEM_IDS = frozenset(
    item_id for item_id, item in DEN_ITEM_BY_ID.items() if item["scene_group"] == "floor"
)
WALL_ITEM_IDS = frozenset(
    item_id for item_id, item in DEN_ITEM_BY_ID.items() if item["scene_group"] == "wall"
)
DECORATION_ITEM_IDS = frozenset(
    item_id for item_id, item in DEN_ITEM_BY_ID.items() if item["scene_group"] == "decoration"
)

SHOP_PRICES: dict[str, int] = {
    str(item["id"]): int(item["price"])
    for item in SHOP_ITEMS
    if item["type"] == "furniture"
}


def _unique_strings(values: Iterable[object] | object) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        return []
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value not in result:
            result.append(value)
    return result


def list_shop_items() -> list[dict[str, object]]:
    """返回可安全交给模板修改的商城商品副本。"""
    return [dict(item) for item in SHOP_ITEMS]


def list_den_items() -> list[dict[str, object]]:
    """返回包括基础样式在内的小窝装扮副本。"""
    return [dict(item) for item in DEN_ITEMS]


def normalise_den_config(
    value: Mapping[str, object] | object,
    owned_item_ids: Iterable[object] | object,
) -> dict[str, object]:
    """把任意输入收敛为当前用户可使用的最小小窝配置。"""
    raw = value if isinstance(value, Mapping) else {}
    owned = set(_unique_strings(owned_item_ids)) | {"base_floor", "base_wall"}

    floor = raw.get("floor")
    if not isinstance(floor, str) or floor not in FLOOR_ITEM_IDS or floor not in owned:
        floor = "base_floor"

    wall = raw.get("wall")
    if not isinstance(wall, str) or wall not in WALL_ITEM_IDS or wall not in owned:
        wall = "base_wall"

    requested_decoration = set(_unique_strings(raw.get("decoration", [])))
    decoration = [
        str(item["id"])
        for item in DEN_ITEMS
        if item["scene_group"] == "decoration"
        and item["id"] in requested_decoration
        and item["id"] in owned
    ]

    return {
        "floor": floor,
        "wall": wall,
        "decoration": decoration,
        "ambience": "night" if raw.get("ambience") == "night" else "day",
    }
