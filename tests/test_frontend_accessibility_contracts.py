"""轻量前端可访问性与文案契约。"""
from __future__ import annotations

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_duration_recommendation_announces_async_state(auth_client):
    html = auth_client.get("/").get_data(as_text=True)

    assert 'id="durationRecommendations"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-busy="false"' in html
    assert 'elements.recommendations.setAttribute("aria-busy", "true")' in html


def test_focus_lock_is_named_focus_managed_and_makes_background_inert():
    template = _read("templates/base.html")
    script = _read("static/app.js")

    assert 'id="focusLockDialog"' in template
    assert 'aria-describedby="focusLockDescription"' in template
    assert "setModalBackgroundInert(focusLockDialog, true)" in script
    assert "trapModalFocus(focusLockDialog, event)" in script
    assert "requestAnimationFrame(() => (modalActions(focusLockDialog)[0] || focusLockDialog).focus())" in script


def test_profile_export_waits_for_real_history_and_uses_score_units(auth_client):
    html = auth_client.get("/profile").get_data(as_text=True)

    assert "let historyPayload = null" in html
    assert "if (historyLoadPromise) return historyLoadPromise" in html
    assert "const payload = await fetchHistory()" in html
    assert "正在准备记录" in html
    assert "`${average} 分`" in html
    assert "`${average}%`" not in html


def test_secondary_pages_have_one_primary_heading_and_keep_rewards(auth_client):
    profile = auth_client.get("/profile").get_data(as_text=True)
    den = auth_client.get("/den").get_data(as_text=True)
    shop = auth_client.get("/shop").get_data(as_text=True)

    assert profile.count("<h1") == 1
    assert den.count("<h1") == 1
    assert shop.count("<h1") == 1
    assert "音乐会员（1 个月）" in shop
    assert "高级会员（1 个月）" in shop
    assert "study_desk" in den
    assert "cat_nest" in den


def test_manual_review_uses_goal_relationship_labels():
    template = _read("templates/evaluation_review.html")
    script = _read("static/evaluation_review.js")

    assert "目标相关" in template
    assert "目标无关" in template
    assert 'data-label="focused"' in template
    assert 'data-label="distracted"' in template
    assert 'focused: "目标相关"' in script
    assert 'distracted: "目标无关"' in script
    assert "这是盲标页面" in template
    assert "模型预测、置信度或理由" in template
    assert "接受模型建议" not in template
    assert "suggested_state" not in script
    assert "modelSuggestionDetails" not in script


def test_ordinary_user_pages_do_not_expose_internal_scoring_terms():
    ordinary_pages = (
        "templates/home.html",
        "templates/focus.html",
        "templates/report.html",
        "templates/analysis.html",
        "templates/profile.html",
        "templates/about.html",
        "templates/rules.html",
        "templates/den.html",
        "templates/shop.html",
    )
    page_text = "\n".join(_read(path) for path in ordinary_pages)

    for internal_term in (
        "评分可靠",
        "可靠会话",
        "可靠记录",
        "可靠历史",
        "待复核",
        "非复用明确画面",
        "独立明确画面",
        "独立的明确状态画面",
        "多维评分 v1",
    ):
        assert internal_term not in page_text


def test_stylesheets_do_not_use_unscoped_bare_button_selectors():
    selector_pattern = re.compile(r"(?m)^\s*button\s*[,\{:]|,\s*button\s*[,\{:]" )
    for stylesheet in (PROJECT_ROOT / "static").glob("*.css"):
        assert not selector_pattern.search(stylesheet.read_text(encoding="utf-8")), stylesheet.name
