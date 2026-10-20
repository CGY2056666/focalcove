from __future__ import annotations

from datetime import date, datetime

from app.blueprints.pages_bp import _build_analysis_view, _build_report_view


def _history_item(
    *,
    session_id: str,
    ended_at: datetime,
    actual: int = 25,
    plan: int = 25,
    coverage: float = 0.8,
    score: float | None = 80,
    goal: str = "阅读",
    goal_type: str = "学习",
) -> dict:
    return {
        "session_id": session_id,
        "goal": goal,
        "goal_type": goal_type,
        "actual_duration": actual,
        "plan_duration": plan,
        "coverage_ratio": coverage,
        "completion_score": score,
        "score_version": "multidim-v1",
        "score_reliable": True,
        "fresh_decisive_frames": 4,
        "decisive_evidence_ratio": 0.75,
        "avg_goal_relevance_score": 82,
        "avg_task_evidence_score": 76,
        "avg_context_fit_score": 80,
        "avg_distraction_risk_score": 20,
        "focus_ratio": 80,
        "distract_duration_seconds": 30,
        "distract_count": 2,
        "alert_count": 1,
        "captured_frames": 8,
        "valid_frames": 7,
        "started_at": ended_at.timestamp() - actual * 60,
        "end_time": ended_at.timestamp(),
        "current_summary": {
            "completion_rate": round(actual / plan * 100, 1) if plan else 0,
        },
    }


def test_report_view_uses_truthful_completion_and_coverage_titles():
    completed = _history_item(
        session_id="done",
        ended_at=datetime(2026, 8, 23, 12, 0),
    )
    completed_view = _build_report_view(completed)
    assert completed_view["title"] == "这一轮已按计划完成"
    assert completed_view["completion_rate"] == 100
    assert completed_view["focus_duration_label"] == "20 分钟"

    early = _history_item(
        session_id="early",
        ended_at=datetime(2026, 8, 23, 13, 0),
        actual=10,
        plan=25,
    )
    assert _build_report_view(early)["title"] == "这一轮已结束"

    almost_done = dict(
        completed,
        started_at=completed["end_time"] - (24 * 60 + 30),
    )
    almost_done_view = _build_report_view(almost_done)
    assert almost_done_view["title"] == "这一轮已结束"
    assert almost_done_view["actual_plan_value"] == "24.5 / 25"

    low_coverage = dict(completed, coverage_ratio=0.5)
    low_view = _build_report_view(low_coverage)
    assert low_view["title"] == "记录已保存，但可用分析数据不足"
    assert low_view["reliable"] is False
    assert low_view["expected_observations"] == 75
    assert low_view["capture_interval_seconds"] == 20
    assert low_view["capture_interval_recorded"] is False


def test_report_view_keeps_missing_score_null_and_accepts_epoch_start():
    item = {
        **_history_item(
            session_id="epoch",
            ended_at=datetime(2026, 8, 23, 12, 0),
            actual=25,
            plan=25,
            score=None,
        ),
        "started_at": 0,
        "end_time": 60,
        "expected_observations": 4,
    }

    view = _build_report_view(item)

    assert view["actual_minutes"] == 1
    assert view["completion_rate"] == 4
    assert view["relevance_score"] is None
    assert view["score_available"] is False
    assert view["expected_observations"] == 4
    assert view["title"] == "记录已保存，但缺少可用评分"


def test_report_uses_saved_state_durations_and_marks_short_evidence_low_confidence():
    item = {
        **_history_item(
            session_id="short-evidence",
            ended_at=datetime(2026, 8, 23, 12, 0),
            actual=1,
            plan=25,
            coverage=1.0,
            score=100,
        ),
        "recommendation_eligible": False,
        "score_reliable": False,
        "fresh_decisive_frames": 2,
        "decisive_evidence_ratio": 0.4,
        "focus_duration_seconds": 12,
        "distract_duration_seconds": 8,
        "uncertain_duration_seconds": 20,
        "unscorable_duration_seconds": 20,
    }

    view = _build_report_view(item)

    assert view["reliable"] is False
    assert view["title"] == "记录已保存，但有效证据不足"
    assert view["reference_score_visible"] is True
    assert view["relevance_score"] == 100
    assert view["decisive_evidence_percent"] == 40
    assert view["focus_duration_label"] == "12 秒"
    assert view["uncertain_duration_label"] == "20 秒"
    assert view["unscorable_duration_label"] == "20 秒"


def test_analysis_view_uses_local_dates_and_latest_ten_reliable_sessions():
    items = [
        _history_item(
            session_id=f"s{index}",
            ended_at=datetime(2026, 8, 23 - index, 23, 30),
            actual=10,
            score=70 + index,
            goal_type="学习" if index % 2 == 0 else "创作",
        )
        for index in range(12)
    ]
    view = _build_analysis_view(items, today=date(2026, 8, 23))

    assert len(view["daily"]) == 14
    assert view["daily"][-1] == {
        "date": "2026-08-23",
        "label": "08-23",
        "minutes": 10.0,
    }
    assert len(view["relevance"]) == 10
    assert view["relevance"][0]["score"] == 79
    assert view["relevance"][-1]["score"] == 70
    assert sum(row["minutes"] for row in view["goals"]) == 120


def test_analysis_trend_excludes_missing_score_even_with_reliable_coverage():
    scored = _history_item(
        session_id="scored",
        ended_at=datetime(2026, 8, 23, 12, 0),
        score=82,
    )
    missing = _history_item(
        session_id="missing",
        ended_at=datetime(2026, 8, 23, 13, 0),
        score=None,
        coverage=0.9,
    )

    view = _build_analysis_view([missing, scored], today=date(2026, 8, 23))

    assert [row["score"] for row in view["relevance"]] == [82]
    assert "只有 1 次数据较完整的记录" in view["relevance_summary"]


def test_analysis_trend_does_not_mix_legacy_and_multidimensional_scores():
    current = _history_item(
        session_id="current",
        ended_at=datetime(2026, 8, 23, 12, 0),
        score=82,
    )
    legacy = {
        **_history_item(
            session_id="legacy",
            ended_at=datetime(2026, 8, 23, 13, 0),
            score=100,
        ),
        "score_version": "legacy-v1",
        "score_reliable": False,
    }

    view = _build_analysis_view([legacy, current], today=date(2026, 8, 23))

    assert [row["score"] for row in view["relevance"]] == [82]


def test_analysis_trend_excludes_explicitly_ineligible_short_session():
    eligible = _history_item(
        session_id="eligible",
        ended_at=datetime(2026, 8, 23, 12, 0),
        score=82,
    )
    short = {
        **_history_item(
            session_id="short",
            ended_at=datetime(2026, 8, 23, 13, 0),
            actual=1,
            score=100,
        ),
        "recommendation_eligible": False,
        "score_reliable": False,
        "fresh_decisive_frames": 2,
        "decisive_evidence_ratio": 0.4,
    }

    view = _build_analysis_view([short, eligible], today=date(2026, 8, 23))

    assert [row["score"] for row in view["relevance"]] == [82]


def test_success_route_redirects_directly_to_report(client, monkeypatch):
    from app.blueprints import pages_bp

    monkeypatch.setattr(
        pages_bp,
        "runtime_snapshot",
        lambda *args, **kwargs: {"user_points": 0},
    )
    with client.session_transaction() as sess:
        sess["username"] = "routeuser"
        sess["running_session_id"] = "old-session"

    response = client.get("/success")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/report")
    with client.session_transaction() as sess:
        assert "running_session_id" not in sess


def test_report_and_analysis_render_new_metrics_and_newest_first(client, monkeypatch):
    from app.blueprints import pages_bp

    newest = _history_item(
        session_id="new",
        ended_at=datetime(2026, 8, 23, 18, 0),
        goal="最新目标",
    )
    oldest = _history_item(
        session_id="old",
        ended_at=datetime(2026, 8, 22, 18, 0),
        goal="较早目标",
    )
    monkeypatch.setattr(
        pages_bp,
        "runtime_snapshot",
        lambda *args, **kwargs: {"user_points": 0},
    )
    monkeypatch.setattr(pages_bp, "get_user", lambda username: {})
    monkeypatch.setattr(
        pages_bp,
        "load_all_history_snapshot",
        lambda username: [newest, oldest],
    )
    with client.session_transaction() as sess:
        sess["username"] = "routeuser"
        sess.pop("running_session_id", None)

    report = client.get("/report")
    assert report.status_code == 200
    assert "这一轮已按计划完成".encode() in report.data
    assert "画面任务相关度".encode() in report.data
    assert "目标内容相关度".encode() in report.data
    assert "明确判断占比".encode() in report.data
    assert "可能偏离".encode() in report.data
    assert "数据完整性详情".encode() in report.data

    analysis = client.get("/analysis")
    assert analysis.status_code == 200
    assert "最近 14 天".encode() in analysis.data
    assert "各目标类型累计时长".encode() in analysis.data
    assert analysis.data.index("最新目标".encode()) < analysis.data.index("较早目标".encode())


def test_report_uses_saved_capture_interval_and_generic_legacy_copy(client, monkeypatch):
    from app.blueprints import pages_bp

    recorded = _history_item(
        session_id="with-interval",
        ended_at=datetime(2026, 8, 23, 18, 0),
    )
    recorded["capture_interval_seconds"] = 20
    monkeypatch.setattr(
        pages_bp,
        "runtime_snapshot",
        lambda *args, **kwargs: {"user_points": 0},
    )
    monkeypatch.setattr(pages_bp, "get_user", lambda username: {})
    monkeypatch.setattr(
        pages_bp,
        "load_all_history_snapshot",
        lambda username: [recorded],
    )
    with client.session_transaction() as sess:
        sess["username"] = "routeuser"

    saved_response = client.get("/report")
    assert saved_response.status_code == 200
    assert "按本轮 20 秒采集节奏估算".encode() in saved_response.data

    legacy_interval = dict(recorded)
    legacy_interval.pop("capture_interval_seconds")
    monkeypatch.setattr(
        pages_bp,
        "load_all_history_snapshot",
        lambda username: [legacy_interval],
    )
    legacy_response = client.get("/report")
    assert legacy_response.status_code == 200
    assert "按本轮采集节奏估算".encode() in legacy_response.data
    assert "按本轮 20 秒采集节奏估算".encode() not in legacy_response.data


def test_report_and_analysis_render_legacy_record_without_score(client, monkeypatch):
    from app.blueprints import pages_bp

    legacy = _history_item(
        session_id="legacy",
        ended_at=datetime(2026, 8, 23, 18, 0),
        coverage=0.9,
        score=None,
    )
    legacy["expected_observations"] = 100
    legacy["score_version"] = "legacy-v1"
    legacy["score_reliable"] = False
    monkeypatch.setattr(
        pages_bp,
        "runtime_snapshot",
        lambda *args, **kwargs: {"user_points": 0},
    )
    monkeypatch.setattr(pages_bp, "get_user", lambda username: {})
    monkeypatch.setattr(
        pages_bp,
        "load_all_history_snapshot",
        lambda username: [legacy],
    )
    with client.session_transaction() as sess:
        sess["username"] = "routeuser"

    report = client.get("/report")
    analysis = client.get("/analysis")

    assert report.status_code == 200
    assert "这是一条旧版评分记录".encode() in report.data
    assert "旧版记录说明".encode() in report.data
    assert "旧版原始分".encode() in report.data
    assert analysis.status_code == 200
    assert "旧版评分只供回看，不参与新版趋势和推荐".encode() in analysis.data


def test_analysis_marks_explicitly_ineligible_record_as_low_confidence(client, monkeypatch):
    from app.blueprints import pages_bp

    short_record = {
        **_history_item(
            session_id="short",
            ended_at=datetime(2026, 8, 23, 18, 0),
            coverage=1.0,
            score=100,
        ),
        "recommendation_eligible": False,
        "score_reliable": False,
        "fresh_decisive_frames": 2,
        "decisive_evidence_ratio": 0.4,
    }
    monkeypatch.setattr(
        pages_bp,
        "runtime_snapshot",
        lambda *args, **kwargs: {"user_points": 0},
    )
    monkeypatch.setattr(pages_bp, "get_user", lambda username: {})
    monkeypatch.setattr(
        pages_bp,
        "load_all_history_snapshot",
        lambda username: [short_record],
    )
    with client.session_transaction() as sess:
        sess["username"] = "routeuser"

    response = client.get("/analysis")

    assert response.status_code == 200
    assert "参考 100 分".encode() in response.data
    assert "明确判断占比不足 50% 或有效判断画面少于 3 张".encode() in response.data
    assert "1/1 次数据较完整记录".encode() not in response.data
