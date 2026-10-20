"""核心首页与专注页的前端契约。"""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_home_uses_one_non_mutating_duration_recommendation(auth_client):
    response = auth_client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.index("这段时间要做什么？") < html.index("准备专注多久？") < html.index("希望怎样提醒？")
    assert "/api/duration/recommend" in html
    assert "/api/mode/recommend" not in html
    assert 'id="applyDurationRecommendation"' in html
    assert "开始并选择共享范围" in html
    assert 'aria-busy="false"' in html
    assert 'elements.startButton.setAttribute("aria-busy", "true")' in html
    assert "recommendation.display_reason || recommendation.reason" in html
    assert "约每 20 秒" in html
    assert "待复核" not in html
    template = (PROJECT_ROOT / "templates" / "home.html").read_text(encoding="utf-8")
    assert "供后续人工检查" in template
    assert "待复核" not in template
    assert "elements.focusDuration.value = String(currentRecommendation.minutes)" in html
    assert 'const initialGoal = "";' in html


def test_home_keeps_recommendation_visible_while_refreshing_and_waits_for_ime(auth_client):
    html = auth_client.get("/").get_data(as_text=True)

    loading_helper = html[html.index("function showRecommendationLoading()") : html.index("async function updateDurationRecommendation()")]
    assert "hasVisibleRecommendation" in loading_helper
    assert "if (!hasVisibleRecommendation)" in loading_helper
    assert 'clearRecommendation("正在根据近期记录计算…")' in loading_helper
    assert 'elements.customGoal.addEventListener("compositionstart"' in html
    assert 'elements.customGoal.addEventListener("compositionend"' in html
    assert "if (!customGoalComposing) scheduleCustomGoalRecommendation();" in html
    assert "recommendationController?.abort();" in html


def test_focus_page_prioritises_goal_timer_status_and_hides_report_clutter(auth_client):
    started = auth_client.post(
        "/api/session/start",
        json={"goal": "完成课程报告", "duration_minutes": 25, "monitoring_mode": "medium"},
    )
    assert started.status_code == 200

    response = auth_client.get("/focus")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for element_id in ("sessionGoal", "remainingTime", "latestStatusLabel", "captureState", "stopSessionButton"):
        assert f'id="{element_id}"' in html
    for element_id in (
        "latestScore",
        "latestGoalRelevance",
        "latestTaskEvidence",
        "latestContextFit",
        "latestDistractionLevel",
    ):
        assert f'id="{element_id}"' in html
    assert "画面任务相关度" in html
    assert "结束并查看报告" in html
    assert "<details class=\"focus-analysis-details\">" in html
    assert 'id="focusActionDock" class="focus-action-dock hidden"' in html
    assert 'id="screenShareButton"' in html
    assert 'id="exitFocusButton"' in html
    assert 'id="permissionModal"' not in html
    assert html.index('<details class="focus-analysis-details">') < html.index('class="focus-quiet-stats"')
    assert "AI 专注寄语" not in html
    assert "关键词提取" not in html
    assert "实时报告" not in html


def test_focus_script_uses_friendly_errors_and_no_removed_widgets():
    script = (PROJECT_ROOT / "static" / "focus.js").read_text(encoding="utf-8")

    assert "没有开始共享。请重新选择一个标签页、窗口或屏幕后再试。" in script
    assert "记录暂时没有保存成功，请检查网络后重试。" in script
    assert "await initScreenShare();" not in script
    assert "window.showPermissionModal" not in script
    assert 'setSharingActive(true);' in script
    assert 'setSharingActive(false);' in script
    assert "liveReportMeta" not in script
    assert "liveKeywords" not in script
    assert "aiAdviceCard" not in script


def test_about_restores_complete_manual_and_marks_planned_features(auth_client):
    response = auth_client.get("/about")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count("<h1") == 1
    for heading in (
        "前言与手册定位",
        "产品概述与设计思路",
        "账号注册、登录与个人设置",
        "开始一轮专注",
        "屏幕分析、状态与三档提醒",
        "结束会话、报告与数据记录",
        "积分、装扮商店与我的小窝",
        "隐私、截图与数据边界",
        "场景搭配与使用技巧",
        "开发中功能与原型限制",
        "常见问题（FAQ）",
        "版本更新与开发反馈",
    ):
        assert heading in html

    assert "音乐会员、平台会员、咖啡券" in html
    assert "当前按钮不可兑换" in html
    assert "手机号或邮箱验证码" in html
    assert "周报、月报和年报，PDF 导出" in html
    assert "准确度超99%" not in html
    assert "不会上传至公开服务器" not in html


def test_about_groups_complete_manual_for_desktop_and_mobile(auth_client):
    html = auth_client.get("/about").get_data(as_text=True)

    group_ids = (
        'id="manualQuick"',
        'id="manualResults"',
        'id="manualFaq"',
        'id="manualPrivacy"',
        'id="manualDeveloper"',
    )
    assert html.count('<details id="manual') == 5
    assert all(group_id in html for group_id in group_ids)
    assert html.index(group_ids[0]) < html.index(group_ids[1]) < html.index(group_ids[2]) < html.index(group_ids[3]) < html.index(group_ids[4])
    assert 'id="manualQuick" class="manual-group" open' in html
    assert "syncManualGroups(desktopManual.matches)" in html
    assert "manual-chapter-toggle" in html
    assert "heading.id === 'guideStart'" in html
    assert "syncManualChapters(desktopManual.matches)" in html


def test_profile_has_two_primary_cards_and_async_stats_state(auth_client):
    html = auth_client.get("/profile").get_data(as_text=True)

    assert html.count('class="profile-card"') == 2
    assert 'id="profileStats" class="mini-metrics profile-metrics" aria-busy="true"' in html
    assert 'id="total-duration">--<' in html
    assert "暂时无法读取专注记录，偏好仍可正常保存。" in html
    assert "数据较完整记录的平均相关度" in html


def test_auth_pages_use_plain_titles_and_consistent_username_rule(client):
    login = client.get("/login").get_data(as_text=True)
    register = client.get("/register").get_data(as_text=True)

    assert "继续你的专注" in login
    assert "保存记录和小窝装扮" in register
    username_rule = "1–32 个中文、字母、数字、下划线或连字符。"
    assert username_rule in login
    assert username_rule in register


def test_shop_keeps_preview_rewards_without_enabling_fake_exchange(auth_client):
    response = auth_client.get("/shop")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "高级会员（1 个月）" in html
    assert "音乐会员（1 个月）" in html
    assert "奖励预览" in html
    assert "暂未开放" in html
    assert 'data-item-id="music_membership_1m"' in html
    assert html.count("暂未开放") == 1
    assert "window.location.reload" not in html
    assert 'id="rewardPreviewTrack"' in html


def test_profile_average_uses_only_reliable_multidim_sessions(auth_client):
    response = auth_client.get("/profile")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "item.score_version === 'multidim-v1'" in html
    assert "item.score_reliable === true" in html
