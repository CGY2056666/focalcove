from __future__ import annotations

import io
import time

from focus_engine.models import FrameAnalysis


def test_frame_complete_retry_and_late_frame_contract(app, auth_client, monkeypatch) -> None:
    analyzer = app.extensions["analyzer"]
    manager = app.extensions["session_manager"]

    def fake_analyze(profile, filename, file_bytes, **kwargs):
        return FrameAnalysis(
            index=0,
            filename=filename,
            image_valid=True,
            frame_id=str(kwargs.get("frame_id") or ""),
            captured_at=float(kwargs.get("captured_at") or time.time()),
            processed_at=time.time(),
            state="uncertain",
            source="fake",
            category_type="focus",
            category_label="代码编辑器",
            focus_score=85.0,
            focus_probability=0.85,
            relevance_score=0.85,
            base_relevance_score=0.85,
            score_confidence=0.9,
            distraction_score=0.05,
            scoring_source="siliconflow",
            decision_reason="正在编辑 Python 代码",
            base_decision_reason="正在编辑 Python 代码",
        )

    monkeypatch.setattr(analyzer, "analyze_frame", fake_analyze)
    try:
        started = auth_client.post(
            "/api/session/start",
            json={"goal": "学习 Python", "duration_minutes": 25, "monitoring_mode": "low"},
        )
        assert started.status_code == 200
        session_id = started.get_json()["session"]["session_id"]

        frame_response = auth_client.post(
            f"/api/session/{session_id}/frame",
            data={
                "screenshot": (io.BytesIO(b"fake-image"), "screen.jpg"),
                "frame_id": "frame-1",
                "captured_at": str(time.time()),
            },
            content_type="multipart/form-data",
        )
        assert frame_response.status_code == 200
        live = frame_response.get_json()
        assert live["latest_item"]["state"] == "focused"
        assert live["latest_item"]["confidence"] == 0.9
        assert "items" not in live

        first_complete = auth_client.post(f"/api/session/{session_id}/complete")
        second_complete = auth_client.post(f"/api/session/{session_id}/complete")
        assert first_complete.status_code == second_complete.status_code == 200
        first_payload = first_complete.get_json()
        second_payload = second_complete.get_json()
        assert len(first_payload["items"]) == 1
        assert second_payload["history_entry"] == first_payload["history_entry"]

        late_frame = auth_client.post(
            f"/api/session/{session_id}/frame",
            data={"screenshot": (io.BytesIO(b"late"), "late.jpg")},
            content_type="multipart/form-data",
        )
        assert late_frame.status_code == 404
    finally:
        manager._frame_executor.shutdown(wait=True)
