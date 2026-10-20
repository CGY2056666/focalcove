from __future__ import annotations

import json

import pytest


PNG_BYTES = b"\x89PNG\r\n\x1a\nlocal-review-fixture"


class FakeEvaluationCollector:
    def __init__(self, *, enabled: bool = True):
        self.enabled = enabled
        self.samples = {
            "sample-1": {
                "sample_id": "sample-1",
                "goal": "完成 Python 单元测试",
                "raw_state": "distracted",
                "raw_confidence": 0.87,
                "reason": "页面内容与目标无关",
            }
        }
        self.labels: list[tuple[str, str]] = []
        self.annotations: list[dict | None] = []
        self.discarded: list[str] = []
        self.image_requests: list[str] = []

    def list_pending(self):
        return list(self.samples.values())

    def label_sample(self, sample_id: str, label: str, *, annotation=None):
        if sample_id not in self.samples:
            raise KeyError(sample_id)
        self.labels.append((sample_id, label))
        self.annotations.append(annotation)
        self.samples.pop(sample_id)
        return True

    def discard_sample(self, sample_id: str):
        if sample_id not in self.samples:
            raise KeyError(sample_id)
        self.discarded.append(sample_id)
        self.samples.pop(sample_id)
        return True

    def get_image(self, sample_id: str):
        self.image_requests.append(sample_id)
        if sample_id not in self.samples:
            return None
        return PNG_BYTES, "image/png"


def _install(app, collector: FakeEvaluationCollector) -> FakeEvaluationCollector:
    app.extensions["evaluation_collector"] = collector
    return collector


def _annotation() -> dict:
    return {
        "goal_relevance": 4,
        "task_evidence": 3,
        "context_fit": 4,
        "distraction_level": 0,
        "overall_score": 9,
        "annotation_confidence": 0.75,
        "scoring_rubric_version": "multidim-v1",
    }


def test_review_routes_are_hidden_when_collection_is_disabled(app, auth_client):
    collector = FakeEvaluationCollector(enabled=False)
    collector.samples.clear()
    _install(app, collector)

    assert auth_client.get("/evaluation/review").status_code == 404
    assert auth_client.get("/evaluation/review/image/sample-1").status_code == 404
    assert auth_client.post(
        "/evaluation/review/sample-1/label", json={"label": "focused"}
    ).status_code == 404


def test_disabled_collection_can_finish_existing_pending_review(app, auth_client):
    collector = _install(app, FakeEvaluationCollector(enabled=False))

    response = auth_client.get("/evaluation/review")

    assert response.status_code == 200
    assert "完成 Python 单元测试" in response.get_data(as_text=True)


def test_review_requires_existing_login_session(app, client):
    _install(app, FakeEvaluationCollector())

    page = client.get("/evaluation/review")

    assert page.status_code == 302
    assert "/login" in page.headers["Location"]
    assert client.get("/evaluation/review/image/sample-1").status_code == 404
    assert client.post(
        "/evaluation/review/sample-1/label", json={"label": "focused"}
    ).status_code == 404


def test_review_is_not_exposed_to_non_loopback_clients(app, auth_client):
    _install(app, FakeEvaluationCollector())

    response = auth_client.get(
        "/evaluation/review",
        environ_overrides={"REMOTE_ADDR": "192.168.1.24"},
    )

    assert response.status_code == 404


def test_review_page_shows_pending_sample_without_auto_labelling(app, auth_client):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.get("/evaluation/review")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "完成 Python 单元测试" in html
    assert "这是盲标页面" in html
    assert "页面内容与目标无关" not in html
    assert "87%" not in html
    assert '"suggested_state"' not in html
    assert '"raw_state"' not in html
    assert '"confidence"' not in html
    assert '"reason"' not in html
    assert "自动采集不等于已经脱敏" in html
    assert "删除候选" in html
    assert 'aria-keyshortcuts="1"' in html
    assert 'aria-keyshortcuts="4"' in html
    assert 'data-score-field="goal_relevance"' in html
    assert 'data-score-field="task_evidence"' in html
    assert 'data-score-field="context_fit"' in html
    assert 'data-score-field="distraction_level"' in html
    assert 'data-score-field="overall_score"' in html
    assert 'data-score-field="annotation_confidence"' in html
    assert "multidim-v1" in html
    assert "标注单位是“这张截图 + 上方这个具体目标”" in html
    assert "不推测使用者此刻是否走神" in html
    assert "截图正常但不知道是否相关，应选“不确定”" in html
    assert "接受模型建议" not in html
    assert 'id="modelSuggestionDetails"' not in html
    assert collector.labels == []


def test_review_image_comes_only_from_collector_lookup(app, auth_client):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.get("/evaluation/review/image/sample-1")
    traversal = auth_client.get("/evaluation/review/image/..%2F..%2F.env")

    assert response.status_code == 200
    assert response.data == PNG_BYTES
    assert response.mimetype == "image/png"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert traversal.status_code == 404
    assert collector.image_requests == ["sample-1", "../../.env"]


@pytest.mark.parametrize("label", ["focused", "uncertain", "distracted", "unscorable"])
def test_review_accepts_exactly_the_four_manual_labels(app, auth_client, label):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.post(
        "/evaluation/review/sample-1/label",
        json={"label": label, "annotation": _annotation()} if label != "unscorable" else {"label": label},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "sample_id": "sample-1",
        "label": label,
        "pending_count": 0,
    }
    assert collector.labels == [("sample-1", label)]
    assert collector.annotations[-1]["scoring_rubric_version"] == "multidim-v1"


def test_review_requires_complete_scores_for_scorable_label(app, auth_client):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.post(
        "/evaluation/review/sample-1/label",
        json={"label": "focused"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "incomplete_human_annotation"
    assert collector.labels == []


def test_review_rejects_invalid_label_without_mutating_collector(app, auth_client):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.post(
        "/evaluation/review/sample-1/label",
        json={"label": "accept_model_automatically"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_label"
    assert collector.labels == []
    assert "sample-1" in collector.samples


@pytest.mark.parametrize("payload", [[], "focused", 1, None])
def test_review_rejects_non_object_json_without_server_error(app, auth_client, payload):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.post(
        "/evaluation/review/sample-1/label",
        json=payload,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_label"
    assert collector.labels == []


def test_review_can_discard_sensitive_candidate_without_labelling(app, auth_client):
    collector = _install(app, FakeEvaluationCollector())

    response = auth_client.post(
        "/evaluation/review/sample-1/discard",
        json={"reason": "manual_privacy_review"},
    )

    assert response.status_code == 200
    assert response.get_json()["discarded"] is True
    assert response.get_json()["pending_count"] == 0
    assert collector.discarded == ["sample-1"]
    assert collector.labels == []


def test_review_routes_match_real_collector_contract(app, auth_client, tmp_path):
    from app.services.evaluation_sample_collector import EvaluationSampleCollector

    collector = EvaluationSampleCollector(tmp_path / "inbox", enabled=True)
    metadata = collector.collect(
        image_bytes=PNG_BYTES,
        filename="capture.png",
        session_id="local-session",
        goal="核对真实采集器契约",
        captured_at=123.0,
        frame_result={
            "raw_state": "focused",
            "raw_confidence": 0.91,
            "focus_score": 88,
            "distraction_score": 0.04,
            "decision_reason": "截图正在核对采集器契约",
        },
    )
    assert metadata is not None
    sample_id = metadata["sample_id"]
    _install(app, collector)

    page = auth_client.get("/evaluation/review")
    image = auth_client.get(f"/evaluation/review/image/{sample_id}")
    labelled = auth_client.post(
        f"/evaluation/review/{sample_id}/label",
        json={"label": "focused", "annotation": _annotation()},
    )

    assert page.status_code == 200
    assert "核对真实采集器契约" in page.get_data(as_text=True)
    assert "截图正在核对采集器契约" not in page.get_data(as_text=True)
    assert '"raw_confidence"' not in page.get_data(as_text=True)
    assert '"suggested_state"' not in page.get_data(as_text=True)
    assert image.status_code == 200
    assert image.data == PNG_BYTES
    assert labelled.status_code == 200
    assert collector.list_pending() == []
    sidecar = collector.screenshots_dir / "focused" / f"{sample_id}.json"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["human_annotation_complete"] is True
