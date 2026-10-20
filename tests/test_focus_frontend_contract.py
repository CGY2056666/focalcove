"""专注页终止态、共享状态与自然文案的前端契约。"""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _focus_script() -> str:
    return (PROJECT_ROOT / "static" / "focus.js").read_text(encoding="utf-8")


def test_terminal_session_errors_stop_capture_and_offer_home_action():
    script = _focus_script()

    assert 'new Set(["session_not_found", "session_not_running"])' in script
    assert "(status === 404 || status === 409)" in script
    assert "stopCaptureClock();" in script
    assert 'elements.stopButton.textContent = "返回首页";' in script
    assert 'if (state.terminal) {' in script
    assert 'window.location.assign("/");' in script


def test_unscorable_reason_is_plain_language_and_not_described_as_review_workflow():
    script = _focus_script()

    assert "item.decision_reason || item.reason || item.fallback_reason || item.warning" in script
    assert "本次没有得到结果，系统会在下一次截图时继续尝试。" in script
    assert "本次没有在时限内得到可靠结果" not in script
    assert 'review: "本次没有结果"' in script
    assert 'itemWasTimedOut(item, reason) ? "本次判断超时" : "本次没有结果"' in script
    assert "待复核" not in script
    assert 'focusState !== "unscorable"' in script


def test_browser_capture_and_deadline_match_runtime_budget():
    script = _focus_script()

    assert "const CAPTURE_INTERVAL_MS = 20_000;" in script
    assert "const REQUEST_TIMEOUT_MS = 18_000;" in script
    assert "本次判断超过 18 秒，没有得到结果" in script


def test_screen_share_is_user_triggered_and_controls_action_dock():
    script = _focus_script()

    assert 'elements.screenShareButton?.addEventListener("click", () => void initScreenShare())' in script
    assert "await initScreenShare();" not in script
    assert "window.showPermissionModal" not in script
    assert 'elements.actionDock?.classList.toggle("hidden", !active)' in script
    assert 'elements.permissionAlert?.classList.toggle("hidden", active)' in script
    assert 'setLivePhase("waiting", "请选择共享范围")' in script
    assert "state.stream?.getTracks().forEach(track => track.stop())" in script
    assert "elements.captureVideo.srcObject = null" in script


def test_capture_status_copy_matches_user_facing_states():
    script = _focus_script()

    for copy in ("正在截图", "正在判断画面", "画面没有明显变化", "本次已跳过", "本次没有结果"):
        assert copy in script


def test_sound_toggle_persists_preference_and_uses_shared_audio_context():
    focus_script = _focus_script()
    app_script = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'settings.sound_alert = elements.soundAlertToggle.checked ? "enabled" : "disabled"' in focus_script
    assert 'localStorage.setItem("focus_settings", JSON.stringify(settings))' in focus_script
    assert "window.initAlertAudio?.();" in focus_script
    assert "let alertAudioContext = null;" in app_script
    assert 'window.getFocusSettings().sound_alert === "disabled"' in app_script
