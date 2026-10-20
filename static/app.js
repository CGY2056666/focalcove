(() => {
  "use strict";
  window.isRunning = window.isRunning || false;
  let alertAudioContext = null;
  let modalReturnFocus = null;
  const modalInertTargets = new WeakMap();

  function modalActions(modal) {
    return [...modal.querySelectorAll('button, [href], input, select, textarea, [contenteditable="true"], [tabindex]:not([tabindex="-1"])')]
      .filter(element => !element.disabled && !element.hasAttribute('hidden') && element.getClientRects().length > 0);
  }

  function setModalBackgroundInert(modal, active) {
    if (!modal) return;
    if (!active) {
      (modalInertTargets.get(modal) || []).forEach(element => element.removeAttribute('inert'));
      modalInertTargets.delete(modal);
      return;
    }
    if (modalInertTargets.has(modal)) return;

    const changed = [];
    let branch = modal;
    while (branch.parentElement) {
      const parent = branch.parentElement;
      [...parent.children].forEach(sibling => {
        if (sibling === branch || /^(SCRIPT|STYLE)$/.test(sibling.tagName) || sibling.hasAttribute('inert')) return;
        sibling.setAttribute('inert', '');
        changed.push(sibling);
      });
      if (parent === document.body) break;
      branch = parent;
    }
    modalInertTargets.set(modal, changed);
  }

  function trapModalFocus(modal, event) {
    if (event.key !== 'Tab' || modal.getAttribute('aria-hidden') === 'true') return;
    const actions = modalActions(modal);
    if (!actions.length) {
      event.preventDefault();
      modal.focus();
      return;
    }
    const first = actions[0];
    const last = actions[actions.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  window.getFocusSettings = function() {
    try {
      return {
        default_duration: 25,
        default_monitoring: "medium",
        sound_alert: "enabled",
        ...JSON.parse(localStorage.getItem("focus_settings") || "{}"),
      };
    } catch (_error) {
      return { default_duration: 25, default_monitoring: "medium", sound_alert: "enabled" };
    }
  };

  // ========== 通用工具函数 ==========
  window.escapeHtml = function(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  window.formatClock = function(totalSeconds) {
    const seconds = Math.max(0, Number(totalSeconds || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;
    if (hours > 0) {
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
    }
    return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  };

  window.formatDate = function(timestampSeconds) {
    if (!timestampSeconds) return "--";
    const date = new Date(timestampSeconds * 1000);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  };

  window.formatMinutes = function(value) {
    const minutes = Number(value || 0);
    if (!Number.isFinite(minutes) || minutes <= 0) return "--";
    return `${Math.round(minutes)} 分钟`;
  };

  window.formatPercent = function(value) {
    const percent = Number(value || 0);
    if (!Number.isFinite(percent)) return "--";
    return `${percent.toFixed(percent % 1 === 0 ? 0 : 1)}%`;
  };

  // 清除会话的函数（用于用户被卡住时）
  window.abandonSession = async function() {
    if (!confirm("放弃后，本轮不会保存，也不会生成报告。确定放弃本轮吗？")) {
      return;
    }
    try {
      const res = await fetch('/api/session/reset', { method: 'POST' });
      if (res.ok) {
        window.location.href = '/';
      } else {
        alert('暂时无法放弃本轮，请稍后重试。');
      }
    } catch (err) {
      console.warn('放弃本轮失败', err);
      alert('暂时无法连接服务，请保持页面打开并稍后重试。');
    }
  };

  window.setMessage = function(type, text) {
    const messageEl = document.getElementById("liveMessage");
    if (!messageEl) return;
    if (!text) {
      messageEl.classList.add("hidden");
      messageEl.textContent = "";
      messageEl.classList.remove("error", "info", "success");
      return;
    }
    messageEl.textContent = text;
    messageEl.classList.remove("hidden", "error", "info", "success");
    messageEl.classList.add(type);
  };

  window.showPermissionModal = function() {
    const modal = document.getElementById('permissionModal');
    if (!modal) return;
    modalReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    modal.classList.remove('hidden');
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    setModalBackgroundInert(modal, true);
    const firstAction = modalActions(modal)[0];
    if (firstAction instanceof HTMLElement) requestAnimationFrame(() => firstAction.focus());
  };

  window.hidePermissionModal = function() {
    const modal = document.getElementById('permissionModal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
    setModalBackgroundInert(modal, false);
    if (modalReturnFocus?.isConnected) modalReturnFocus.focus();
    modalReturnFocus = null;
  };

  window.exitFocusWithoutPermission = async function() {
    try {
      await fetch('/api/session/reset', { method: 'POST' });
    } catch (_err) {
      // ignore errors, still navigate home
    }
    window.location.href = '/';
  };

  window.requestScreenPermission = function() {
    window.setMessage('info', '请允许屏幕权限，才能进行屏幕分析。');
    if (typeof window.initScreenShare === 'function') {
      window.initScreenShare();
    }
  };

  // One shared AudioContext avoids leaking a new context for every reminder.
  window.initAlertAudio = function() {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return null;
      if (!alertAudioContext || alertAudioContext.state === "closed") alertAudioContext = new AudioContext();
      if (alertAudioContext.state === "suspended") void alertAudioContext.resume();
      return alertAudioContext;
    } catch (error) {
      console.warn("音效初始化失败", error);
      return null;
    }
  };

  window.playAlertSound = function() {
    if (window.getFocusSettings().sound_alert === "disabled") return;
    try {
      const ctx = window.initAlertAudio();
      if (!ctx) return;
      const osc = ctx.createOscillator();
      const gainNode = ctx.createGain();
      osc.connect(gainNode);
      gainNode.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.setValueAtTime(600, ctx.currentTime);
      gainNode.gain.setValueAtTime(0.0001, ctx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.32);
      osc.start();
      osc.stop(ctx.currentTime + 0.34);
    } catch (error) {
      console.warn("音效播放失败", error);
    }
  };

  // ========== 快速目标标签点击事件 ==========
  document.addEventListener('DOMContentLoaded', () => {
    const navToggle = document.getElementById("navToggle");
    const navMenu = document.getElementById("primaryNavigation");
    if (navToggle && navMenu) {
      const toggleLabel = navToggle.querySelector('.sr-only');
      const closeMenu = () => {
        const wasOpen = navMenu.classList.contains("open");
        navMenu.classList.remove("open");
        navToggle.setAttribute("aria-expanded", "false");
        if (toggleLabel) toggleLabel.textContent = "打开导航菜单";
        return wasOpen;
      };
      navToggle.addEventListener("click", () => {
        const open = navMenu.classList.toggle("open");
        navToggle.setAttribute("aria-expanded", String(open));
        if (toggleLabel) toggleLabel.textContent = open ? "关闭导航菜单" : "打开导航菜单";
      });
      navMenu.addEventListener("click", event => {
        if (event.target.closest("a")) closeMenu();
      });
      document.addEventListener("pointerdown", event => {
        if (!navMenu.classList.contains("open")) return;
        if (navMenu.contains(event.target) || navToggle.contains(event.target)) return;
        closeMenu();
      });
      document.addEventListener("keydown", event => {
        if (event.key === "Escape" && closeMenu()) navToggle.focus();
      });
      window.addEventListener("resize", () => {
        if (window.innerWidth > 768) closeMenu();
      });
    }

    document.querySelectorAll('a.disabled-link').forEach(link => {
      link.setAttribute('aria-disabled', 'true');
      link.setAttribute('tabindex', '-1');
      link.addEventListener('click', event => event.preventDefault());
    });

    const permissionModal = document.getElementById('permissionModal');
    permissionModal?.addEventListener('keydown', event => trapModalFocus(permissionModal, event));

    const focusLockDialog = document.getElementById('focusLockDialog');
    if (focusLockDialog) {
      setModalBackgroundInert(focusLockDialog, true);
      focusLockDialog.addEventListener('keydown', event => trapModalFocus(focusLockDialog, event));
      document.addEventListener('focusin', event => {
        if (!focusLockDialog.contains(event.target)) (modalActions(focusLockDialog)[0] || focusLockDialog).focus();
      });
      requestAnimationFrame(() => (modalActions(focusLockDialog)[0] || focusLockDialog).focus());
    }

    const quickGoalTags = document.querySelectorAll('.quick-goal-tag');
    const goalInput = document.getElementById('liveGoal');
    if (quickGoalTags.length > 0 && goalInput) {
      quickGoalTags.forEach(tag => {
        tag.addEventListener('click', (e) => {
          const text = e.target.textContent;
          goalInput.value = text;
          goalInput.dispatchEvent(new Event("input", { bubbles: true }));
          goalInput.style.transition = "box-shadow 0.3s ease";
          goalInput.style.boxShadow = "0 0 0 3px rgba(31, 103, 98, 0.2)";
          setTimeout(() => {
            goalInput.style.boxShadow = "none";
          }, 400);
        });
      });
    }

    // 推荐时长应用按钮
    const applyBtn = document.getElementById('applyDurationRecommendation');
    const durationInput = document.getElementById('liveDuration');
    if (applyBtn && durationInput) {
      applyBtn.addEventListener('click', () => {
        const recommend = document.getElementById('durationRecommendBase')?.textContent;
        if (recommend && recommend !== '--') {
          durationInput.value = recommend.replace('分钟', '').trim();
          window.setMessage('info', `已应用推荐时长 ${recommend}`);
        }
      });
    }
  });
})();
