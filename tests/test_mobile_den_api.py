from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.services.den_service import exchange_furniture
from app.services.user_service import get_user, mutate_user, save_user


def _register(client, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "mobilepass123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.get_json()['access_token']}"}


def _set_points(app, username: str, points: int) -> None:
    with app.app_context():
        data = get_user(username)
        data["total_points"] = points
        save_user(username, data)


def test_mobile_den_requires_bearer_auth_and_returns_real_furniture_only(client):
    assert client.get("/api/v1/den").status_code == 401
    assert client.put("/api/v1/den", json={"den_config": {}}).status_code == 401
    assert client.post("/api/v1/shop/exchanges", json={"item_id": "cushion"}).status_code == 401

    headers = _register(client, "dencontract")
    response = client.get("/api/v1/den", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"points", "items", "config"}
    assert payload["points"] == 0
    assert len(payload["items"]) == 12
    assert {item["id"] for item in payload["items"] if item["owned"]} == {
        "base_floor",
        "base_wall",
    }
    assert "coffee_voucher" not in {item["id"] for item in payload["items"]}
    assert payload["config"] == {
        "floor": "base_floor",
        "wall": "base_wall",
        "decoration": [],
        "ambience": "day",
    }


def test_mobile_exchange_is_idempotent_and_never_charges_invalid_rewards(app, client):
    headers = _register(client, "exchangeuser")
    _set_points(app, "exchangeuser", 500)

    preview = client.post(
        "/api/v1/shop/exchanges",
        headers=headers,
        json={"item_id": "coffee_voucher"},
    )
    assert preview.status_code == 400
    assert preview.get_json()["error"]["code"] == "invalid_item"
    malformed = client.post(
        "/api/v1/shop/exchanges",
        headers=headers,
        json=["desk_lamp"],
    )
    assert malformed.status_code == 400
    assert malformed.get_json()["error"]["code"] == "invalid_item"

    first = client.post(
        "/api/v1/shop/exchanges",
        headers=headers,
        json={"item_id": "desk_lamp"},
    )
    retry = client.post(
        "/api/v1/shop/exchanges",
        headers=headers,
        json={"item_id": "desk_lamp"},
    )

    assert first.status_code == retry.status_code == 200
    assert first.get_json()["already_owned"] is False
    assert retry.get_json()["already_owned"] is True
    assert first.get_json()["points"] == retry.get_json()["points"] == 150
    assert next(item for item in retry.get_json()["items"] if item["id"] == "desk_lamp")["owned"]


def test_mobile_exchange_insufficient_points_and_user_ownership_are_isolated(app, client):
    alice_headers = _register(client, "denalice")
    bob_headers = _register(client, "denbob")
    _set_points(app, "denalice", 120)

    insufficient = client.post(
        "/api/v1/shop/exchanges",
        headers=alice_headers,
        json={"item_id": "plant_pot"},
    )
    assert insufficient.status_code == 409
    assert insufficient.get_json()["error"]["code"] == "insufficient_points"
    assert client.get("/api/v1/den", headers=alice_headers).get_json()["points"] == 120
    assert all(
        not item["owned"]
        for item in client.get("/api/v1/den", headers=bob_headers).get_json()["items"]
        if item["id"] not in {"base_floor", "base_wall"}
    )


def test_mobile_den_update_only_persists_owned_canonical_items(app, client):
    headers = _register(client, "denlayout")
    with app.app_context():
        data = get_user("denlayout")
        data["unlocked_items"].extend(["wood_floor", "cushion"])
        save_user("denlayout", data)

    response = client.put(
        "/api/v1/den",
        headers=headers,
        json={
            "den_config": {
                "floor": "wood_floor",
                "wall": "star_wall",
                "decoration": ["study_desk", "cushion", "cushion", "unknown"],
                "ambience": "night",
            }
        },
    )

    assert response.status_code == 200
    assert response.get_json()["config"] == {
        "floor": "wood_floor",
        "wall": "base_wall",
        "decoration": ["cushion"],
        "ambience": "night",
    }
    assert client.get("/api/v1/den", headers=headers).get_json()["config"] == response.get_json()["config"]


def test_concurrent_mobile_exchange_charges_once_and_keeps_both_purchases(app, client):
    headers = _register(client, "denconcurrent")
    _set_points(app, "denconcurrent", 620)

    def exchange(item_id: str):
        with app.test_client() as thread_client:
            return thread_client.post(
                "/api/v1/shop/exchanges",
                headers=headers,
                json={"item_id": item_id},
            )

    with ThreadPoolExecutor(max_workers=3) as executor:
        same_results = list(executor.map(exchange, ["plant_pot", "plant_pot"]))
    assert [result.status_code for result in same_results] == [200, 200]
    assert sorted(result.get_json()["already_owned"] for result in same_results) == [False, True]

    with ThreadPoolExecutor(max_workers=2) as executor:
        different_results = list(executor.map(exchange, ["desk_lamp", "cushion"]))
    assert [result.status_code for result in different_results] == [200, 200]

    state = client.get("/api/v1/den", headers=headers).get_json()
    assert state["points"] == 0
    owned = {item["id"] for item in state["items"] if item["owned"]}
    assert {"plant_pot", "desk_lamp", "cushion"} <= owned


def test_focus_reward_and_exchange_cannot_overwrite_each_other(app, client):
    _register(client, "denrewardrace")
    _set_points(app, "denrewardrace", 350)

    def award_focus_points():
        with app.app_context():
            mutate_user(
                "denrewardrace",
                lambda data: data.__setitem__(
                    "total_points",
                    data["total_points"] + 100,
                ),
            )

    def exchange_lamp():
        with app.app_context():
            exchange_furniture("denrewardrace", "desk_lamp")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(award_focus_points),
            executor.submit(exchange_lamp),
        ]
        for future in futures:
            future.result()

    with app.app_context():
        state = get_user("denrewardrace")
    assert state["total_points"] == 100
    assert "desk_lamp" in state["unlocked_items"]
