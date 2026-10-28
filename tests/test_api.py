"""API 端点测试"""
from __future__ import annotations

import json


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert data["service"] == "focus-compass"
        assert data["api_version"] == "v1"
        assert data["app_version"] == "2.0"
        assert "runtime" not in data


class TestDurationRecommend:
    def test_recommend_no_auth(self, client):
        r = client.get("/api/duration/recommend?goal=学习Python")
        assert r.status_code == 401

    def test_recommend_with_auth(self, auth_client):
        r = auth_client.get("/api/duration/recommend?goal=学习Python")
        assert r.status_code == 200
        data = r.get_json()
        assert "goal" in data
        assert "recommendation" in data


class TestModeRecommend:
    def test_mode_recommend_requires_login(self, client):
        r = client.get("/api/mode/recommend?goal=学习")
        assert r.status_code == 401

    def test_mode_recommend(self, auth_client):
        r = auth_client.get("/api/mode/recommend?goal=学习")
        assert r.status_code == 200
        data = r.get_json()
        assert "recommended_mode" in data
        assert data["recommended_mode"] in ("regular", "deep")
        assert data["suggested_config"]["monitoring"] == "medium"
        assert data["stats"]["reliable_sessions"] == 0

    def test_mode_recommend_excludes_reliable_record_with_missing_score(
        self,
        auth_client,
        monkeypatch,
    ):
        from app.blueprints import api_bp

        monkeypatch.setattr(
            api_bp,
            "load_recent",
            lambda *args, **kwargs: [
                {"coverage_ratio": 0.9, "coverage_version": 2, "completion_score": None, "score_version": "multidim-v1", "score_reliable": False, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.5},
                {"coverage_ratio": 0.8, "coverage_version": 2, "completion_score": 82, "score_version": "multidim-v1", "score_reliable": True, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.5},
            ],
        )
        monkeypatch.setattr(
            api_bp,
            "build_duration_recommendation",
            lambda *args, **kwargs: {"base_recommend": 25},
        )

        response = auth_client.get("/api/mode/recommend?goal=学习")

        assert response.status_code == 200
        stats = response.get_json()["stats"]
        assert stats["reliable_sessions"] == 1
        assert stats["avg_focus_score"] == 82
        payload = response.get_json()
        assert payload["recommended_mode"] == "regular"
        assert payload["suggested_config"]["monitoring"] == "medium"

    def test_mode_recommend_excludes_explicitly_ineligible_and_legacy_records(
        self,
        auth_client,
        monkeypatch,
    ):
        from app.blueprints import api_bp

        monkeypatch.setattr(
            api_bp,
            "load_recent",
            lambda *args, **kwargs: [
                {
                    "coverage_ratio": 1.0,
                    "coverage_version": 2,
                    "completion_score": 100,
                    "recommendation_eligible": False,
                    "score_version": "multidim-v1",
                    "score_reliable": False,
                    "fresh_decisive_frames": 2,
                    "decisive_evidence_ratio": 0.4,
                },
                # 旧记录保留展示，但不进入新版模式推荐统计。
                {"coverage_ratio": 0.8, "coverage_version": 2, "completion_score": 82},
                {"coverage_ratio": 0.8, "coverage_version": 2, "completion_score": 78, "score_version": "multidim-v1", "score_reliable": True, "fresh_decisive_frames": 3, "decisive_evidence_ratio": 0.6},
            ],
        )
        monkeypatch.setattr(
            api_bp,
            "build_duration_recommendation",
            lambda *args, **kwargs: {"base_recommend": 25},
        )

        response = auth_client.get("/api/mode/recommend?goal=学习")

        assert response.status_code == 200
        stats = response.get_json()["stats"]
        assert stats["reliable_sessions"] == 1
        assert stats["avg_focus_score"] == 78


class TestHistoryEndpoints:
    def test_recent_history_requires_login(self, client):
        r = client.get("/api/history/recent")
        assert r.status_code == 401

    def test_all_history_requires_login(self, client):
        r = client.get("/api/history/all")
        assert r.status_code == 401

    def test_recent_history(self, auth_client):
        r = auth_client.get("/api/history/recent")
        assert r.status_code == 200
        data = r.get_json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_all_history(self, auth_client):
        r = auth_client.get("/api/history/all")
        assert r.status_code == 200
        data = r.get_json()
        assert "items" in data

    def test_all_history_reports_service_failure(self, auth_client, monkeypatch):
        from app.blueprints import api_bp

        def fail_load(*_args, **_kwargs):
            raise OSError("read failed")

        monkeypatch.setattr(api_bp, "load_all", fail_load)

        response = auth_client.get("/api/history/all")

        assert response.status_code == 503
        assert response.get_json() == {"error": "history_unavailable"}


class TestSessionLifecycle:
    def test_start_session_missing_goal(self, auth_client):
        r = auth_client.post("/api/session/start", json={})
        assert r.status_code == 400

    def test_start_session(self, auth_client):
        r = auth_client.post(
            "/api/session/start",
            json={"goal": "学习Python", "duration_minutes": 25, "monitoring_mode": "medium"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "session" in data
        assert "session_id" in data["session"]

    def test_reset_session(self, auth_client):
        r = auth_client.post("/api/session/reset")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True

    def test_snapshot_not_found(self, auth_client):
        r = auth_client.get("/api/session/deadbeef1234")
        assert r.status_code == 404


class TestShopExchange:
    def test_exchange_no_auth(self, client):
        r = client.post("/api/shop/exchange", json={"item_id": "cat_nest"})
        assert r.status_code == 401

    def test_exchange_invalid_item(self, auth_client):
        r = auth_client.post(
            "/api/shop/exchange",
            json={"item_id": "nonexistent_item"},
            content_type="application/json",
        )
        # 无效商品返回400
        assert r.status_code in (400, 401)

    def test_exchange_rejects_preview_only_reward(self, auth_client):
        r = auth_client.post(
            "/api/shop/exchange",
            json={"item_id": "premium_member_1m"},
            content_type="application/json",
        )
        assert r.status_code == 400


class TestUserPermission:
    def test_update_permission_requires_login(self, client):
        r = client.post(
            "/api/user/permission",
            json={"monitoring_permission": True},
        )
        assert r.status_code == 401

    def test_update_permission(self, auth_client):
        r = auth_client.post(
            "/api/user/permission",
            json={"monitoring_permission": True},
            content_type="application/json",
        )
        assert r.status_code == 200
        assert r.get_json() == {
            "success": True,
            "monitoring_permission": True,
        }
