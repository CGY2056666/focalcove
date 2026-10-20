(() => {
  "use strict";

  const CAPTURE_INTERVAL_MS = 20_000;
  const REQUEST_TIMEOUT_MS = 18_000;
  const MAX_PREVIEW_EDGE = 1024;
  const JPEG_QUALITY = 0.72;
  const TERMINAL_SESSION_ERRORS = new Set(["session_not_found", "session_not_running"]);

  let elements = {};
  let state = {};

  const STATE_META = {
    focused: { label: "画面与目标相关", className: "focus", icon: "✓" },
    uncertain: { label: "暂时无法判断", className: "warn", icon: "?" },
    distracted: { label: "画面可能偏离目标", className: "danger", icon: "!" },
    unscorable: { label: "本次未能分析", className: "muted", icon: "×" },
  };

  function normaliseState(item) {
    const raw = String(item?.state || item?.focus_state || item?.status_code || item?.status || "").toLowerCase();
    if (["focused", "focus", "专注"].includes(raw)) return "focused";
    if (["distracted", "distract", "分心"].includes(raw)) return "distracted";
    if (["unscorable", "review_required", "error", "\u5f85\u590d\u6838"].includes(raw)) return "unscorable";
    if (["uncertain", "neutral", "slightly_distracted", "轻微偏离", "待确认"].includes(raw)) return "uncertain";
    return item ? "uncertain" : "unscorable";
  }

  function getLatestItem(payload) {
    if (payload?.latest_item) return payload.latest_item;
    if (payload?.frame_result) return payload.frame_result;
    if (Array.isArray(payload?.items) && payload.items.length) return payload.items[payload.items.length - 1];
    return null;
  }

  function setLivePhase(phase, message) {
    if (!elements.captureState) return;
    const labels = {
      waiting: "等待下一次截图",
      capturing: "正在截图",
      analysing: "正在判断画面",
      reused: "画面没有明显变化",
      complete: "本次判断完成",
      review: "本次没有结果",
      network: "本次没有结果",
      stopped: "专注已结束",
    };
    elements.captureState.className = `capture-state ${phase}`;
    elements.captureState.textContent = message || labels[phase] || labels.waiting;
  }

  function announce(message) {
    if (!elements.liveAnnouncement || !message || elements.liveAnnouncement.textContent === message) return;
    elements.liveAnnouncement.textContent = message;
  }

  function setPermissionFeedback(message, tone = "info") {
    if (!elements.permissionFeedback) return;
    elements.permissionFeedback.textContent = message;
    elements.permissionFeedback.className = `permission-feedback ${tone}`;
  }

  function setSharingActive(active) {
    elements.permissionAlert?.classList.toggle("hidden", active);
    elements.actionDock?.classList.toggle("hidden", !active);
    elements.actionDock?.setAttribute("aria-hidden", String(!active));
    elements.sessionShell?.classList.toggle("sharing-active", active);
  }

  function refreshGoalToggle() {
    if (!elements.goalTitle || !elements.goalToggleButton) return;
    const wasExpanded = elements.goalTitle.classList.contains("expanded");
    elements.goalTitle.classList.remove("is-collapsible", "expanded");
    elements.goalToggleButton.classList.add("hidden");
    elements.goalToggleButton.setAttribute("aria-expanded", "false");

    if (!window.matchMedia("(max-width: 700px)").matches) return;
    const lineHeight = Number.parseFloat(getComputedStyle(elements.goalTitle).lineHeight) || 32;
    const needsToggle = elements.goalTitle.scrollHeight > lineHeight * 2 + 1;
    if (!needsToggle) return;

    elements.goalTitle.classList.add("is-collapsible");
    elements.goalTitle.classList.toggle("expanded", wasExpanded);
    elements.goalToggleButton.classList.remove("hidden");
    elements.goalToggleButton.setAttribute("aria-expanded", String(wasExpanded));
    elements.goalToggleButton.textContent = wasExpanded ? "收起目标" : "展开目标";
  }

  function queueGoalToggleRefresh() {
    window.requestAnimationFrame(refreshGoalToggle);
  }

  function isTerminalSessionResponse(response, payload) {
    const status = Number(response?.status || 0);
    return (status === 404 || status === 409) && TERMINAL_SESSION_ERRORS.has(String(payload?.error || ""));
  }

  function terminalSessionMessage(errorCode) {
    if (errorCode === "session_not_running") {
      return "这轮专注已经结束，无法继续提交截图。请返回首页开始新一轮。";
    }
    return "这轮专注已失效或不存在。请返回首页重新开始。";
  }

  function enterTerminalSessionState(errorCode) {
    const message = terminalSessionMessage(errorCode);
    state.terminal = true;
    state.running = false;
    state.finishing = false;
    stopCaptureClock();
    clearInterval(state.tickerIntervalId);
    clearTimeout(state.alertHideTimerId);
    state.stream?.getTracks().forEach(track => track.stop());
    state.stream = null;
    elements.focusAlert?.classList.add("hidden");
    setSharingActive(true);

    setLivePhase("stopped", "会话已结束");
    elements.latestStatusLabel.textContent = "会话已结束";
    if (elements.latestStatusIcon) elements.latestStatusIcon.textContent = "×";
    if (elements.latestStatusPanel) elements.latestStatusPanel.className = "focus-current-status state-unscorable";
    elements.latestReason.textContent = message;
    if (elements.stopButton) {
      elements.stopButton.disabled = false;
      elements.stopButton.textContent = "返回首页";
    }
    announce(message);
    window.setMessage("error", message);
  }

  function itemWasTimedOut(item, reason) {
    if (item?.timed_out === true || item?.timeout === true) return true;
    const errorCode = String(item?.error_code || item?.error_type || "").toLowerCase();
    if (["timeout", "timed_out", "deadline_exceeded"].includes(errorCode)) return true;
    return /(?:超时|超过\s*\d+(?:\.\d+)?\s*秒|timed?\s*out|timeout|deadline)/i.test(String(reason || ""));
  }

  function formatDimension(value, unitInterval = false) {
    if (value == null || value === "") return "--";
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    const normalized = unitInterval && number <= 1 ? number * 100 : number;
    return `${Math.round(Math.max(0, Math.min(100, normalized)))}/100`;
  }

  function renderDimensions(item) {
    const scoreVersion = String(item?.score_version || "");
    if (elements.latestScoreVersion) {
      elements.latestScoreVersion.textContent = scoreVersion === "multidim-v1"
        ? "评分明细"
        : scoreVersion
          ? "旧版记录"
          : "暂无明细";
    }
    if (elements.latestGoalRelevance) {
      elements.latestGoalRelevance.textContent = formatDimension(item?.goal_relevance_score);
    }
    if (elements.latestTaskEvidence) {
      elements.latestTaskEvidence.textContent = formatDimension(item?.task_evidence_score);
    }
    if (elements.latestContextFit) {
      elements.latestContextFit.textContent = formatDimension(item?.context_fit_score);
    }
    if (elements.latestDistractionLevel) {
      elements.latestDistractionLevel.textContent = formatDimension(item?.distraction_score, true);
    }
  }

  function updateRuntimeClock() {
    if (!elements.elapsedTime || !state.localStartedAt) return;
    const elapsedSeconds = Math.floor((Date.now() - state.localStartedAt) / 1000);
    const session = state.latestPayload?.session || {};
    const durationSeconds = Number(session.duration_seconds || state.durationSeconds || 0);
    state.durationSeconds = durationSeconds;
    state.maxPossiblePoints = Math.ceil(durationSeconds / 60) * 3;

    const remainingSeconds = Math.max(0, durationSeconds - elapsedSeconds);
    const progress = durationSeconds > 0 ? Math.min(100, (elapsedSeconds / durationSeconds) * 100) : 0;
    elements.elapsedTime.textContent = window.formatClock(elapsedSeconds);
    if (elements.remainingTime) elements.remainingTime.textContent = window.formatClock(remainingSeconds);
    if (elements.progressPercent) elements.progressPercent.textContent = `${progress.toFixed(0)}%`;
    if (elements.sessionProgressBar) elements.sessionProgressBar.style.width = `${progress.toFixed(1)}%`;
    if (elements.sessionProgress) elements.sessionProgress.setAttribute("aria-valuenow", String(Math.round(progress)));
    if (elements.maxPoints) elements.maxPoints.textContent = String(state.maxPossiblePoints);

    if (durationSeconds > 0 && remainingSeconds <= 0 && !state.finishing) void window.completeSession("finished");
  }

  function syncRuntimeClock(session) {
    const elapsedSeconds = Number(session?.elapsed_seconds);
    if (Number.isFinite(elapsedSeconds) && elapsedSeconds >= 0) {
      state.localStartedAt = Date.now() - elapsedSeconds * 1000;
      state.clockSynced = true;
      return;
    }
    const createdAt = Number(session?.created_at);
    if (Number.isFinite(createdAt) && createdAt > 0) {
      state.localStartedAt = createdAt * 1000;
      state.clockSynced = true;
    }
  }

  function waitForVideoReady(timeoutMs = 3000) {
    return new Promise((resolve, reject) => {
      const video = elements.captureVideo;
      if (!video) {
        reject(new Error("屏幕采集组件未就绪"));
        return;
      }
      let timer = 0;
      const cleanup = () => {
        video.removeEventListener("loadedmetadata", checkReady);
        video.removeEventListener("loadeddata", checkReady);
        video.removeEventListener("playing", checkReady);
        clearTimeout(timer);
      };
      const checkReady = () => {
        if (video.readyState >= 2 && video.videoWidth > 1 && video.videoHeight > 1) {
          cleanup();
          resolve();
        }
      };
      timer = window.setTimeout(() => {
        cleanup();
        reject(new Error("屏幕画面尚未准备好"));
      }, timeoutMs);
      video.addEventListener("loadedmetadata", checkReady);
      video.addEventListener("loadeddata", checkReady);
      video.addEventListener("playing", checkReady);
      checkReady();
    });
  }

  async function captureBlob(filename) {
    const video = elements.captureVideo;
    const canvas = elements.captureCanvas;
    if (!video || !canvas) throw new Error("截图组件不可用");
    if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) await waitForVideoReady();

    const scale = Math.min(1, MAX_PREVIEW_EDGE / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("浏览器无法创建截图画布");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob((value) => value ? resolve(value) : reject(new Error("截图压缩失败")), "image/jpeg", JPEG_QUALITY);
    });
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = URL.createObjectURL(blob);
    if (elements.previewImage) {
      elements.previewImage.src = state.previewUrl;
      elements.previewImage.classList.remove("hidden");
    }
    elements.previewPlaceholder?.classList.add("hidden");
    if (elements.previewLabel) elements.previewLabel.textContent = `最新截图 · ${canvas.width}×${canvas.height}`;
    return blob;
  }

  function renderLatestItem(item) {
    if (!item) return;
    const focusState = normaliseState(item);
    const meta = STATE_META[focusState];
    const score = item.focus_score ?? item.score;
    const numericScore = Number(score);
    const scoreDisplayable = focusState !== "unscorable" && score != null && Number.isFinite(numericScore);
    const processingMs = Number(item.processing_ms ?? item.latency_ms ?? 0);
    const source = String(item.source || item.scoring_source || "").toLowerCase();
    const reused = Boolean(item.reused) || ["cache", "cached", "reuse", "reused", "duplicate"].some(value => source.includes(value));

    elements.latestStatusLabel.textContent = meta.label;
    if (elements.latestStatusIcon) elements.latestStatusIcon.textContent = meta.icon;
    elements.latestScore.textContent = scoreDisplayable ? String(Math.round(numericScore)) : "--";
    elements.latestScore.className = `score-badge ${meta.className}`;
    renderDimensions(item);
    elements.latestProcessing.textContent = processingMs > 0 ? `${Math.round(processingMs)} ms` : "--";
    const confidenceValue = item.confidence ?? item.score_confidence;
    const confidenceRaw = confidenceValue == null ? null : Number(confidenceValue);
    const confidence = confidenceRaw == null || !Number.isFinite(confidenceRaw)
      ? ""
      : ` · 置信 ${Math.round((confidenceRaw <= 1 ? confidenceRaw * 100 : confidenceRaw))}%`;
    elements.latestContext.textContent = `${item.category_label || item.category || meta.label}${confidence}`;
    const serverReason = item.decision_reason || item.reason || item.fallback_reason || item.warning;
    const reason = serverReason || (focusState === "unscorable"
      ? "本次没有得到结果，系统会在下一次截图时继续尝试。"
      : "已完成本次画面分析。");
    elements.latestReason.textContent = reason;
    if (elements.latestStatusPanel) {
      elements.latestStatusPanel.className = `focus-current-status state-${focusState}`;
    }

    if (focusState === "unscorable") {
      setLivePhase("review", itemWasTimedOut(item, reason) ? "本次判断超时" : "本次没有结果");
    }
    else if (reused) setLivePhase("reused");
    else setLivePhase("complete");
    announce(`${meta.label}。${reason}`);
  }

  function renderSummary(payload) {
    const summary = payload?.summary || {};
    const session = payload?.session || state.latestPayload?.session || {};
    const capturedFrames = Number(payload?.session?.captured_frames ?? summary.total_frames ?? state.localCaptureCount ?? 0);
    const distractedFrames = Number(summary.distracted_frames ?? summary.distract_count ?? 0);
    const alertCount = Number(summary.alert_count ?? state.alertCount ?? 0);
    state.alertCount = Math.max(state.alertCount, alertCount);
    window.distractCount = distractedFrames;
    const goal = payload?.goal || session.goal;
    if (elements.sessionGoal && goal) {
      elements.sessionGoal.textContent = String(goal);
      queueGoalToggleRefresh();
    }
    if (elements.capturedCount) elements.capturedCount.textContent = String(Math.max(0, capturedFrames));
    if (elements.distractCount) elements.distractCount.textContent = String(distractedFrames);
    if (elements.alertCount) elements.alertCount.textContent = String(state.alertCount);
  }

  function renderSessionPayload(payload) {
    if (!payload) return;
    state.latestPayload = { ...state.latestPayload, ...payload };
    syncRuntimeClock(payload.session);
    updateRuntimeClock();
    renderLatestItem(getLatestItem(payload));
    renderSummary(payload);
  }

  function showAlert(alertEvent) {
    if (!alertEvent) return;
    const eventId = String(alertEvent.event_id || alertEvent.id || `${alertEvent.triggered_at || Date.now()}-${alertEvent.reason || "alert"}`);
    if (state.seenAlertIds.has(eventId)) return;
    state.seenAlertIds.add(eventId);
    if (state.seenAlertIds.size > 100) state.seenAlertIds.delete(state.seenAlertIds.values().next().value);
    state.alertCount += 1;
    if (elements.alertCount) elements.alertCount.textContent = String(state.alertCount);
    window.playAlertSound?.();

    const reason = alertEvent.reason || "共享画面可能偏离了当前目标，请把注意力带回来。";
    if (elements.focusAlert) {
      elements.focusAlertText.textContent = reason;
      elements.focusAlert.classList.remove("hidden");
      clearTimeout(state.alertHideTimerId);
      state.alertHideTimerId = window.setTimeout(() => elements.focusAlert?.classList.add("hidden"), 8000);
    }
    if (elements.distractionList) {
      const item = document.createElement("div");
      item.className = "distraction-item";
      const timestamp = Number(alertEvent.triggered_at || 0);
      const time = timestamp
        ? new Date(timestamp * (timestamp < 1e12 ? 1000 : 1)).toLocaleTimeString()
        : new Date().toLocaleTimeString();
      item.innerHTML = `<span>${window.escapeHtml(time)}</span><span>${window.escapeHtml(reason)}</span>`;
      elements.distractionList.querySelector(".empty-text")?.remove();
      elements.distractionList.prepend(item);
    }
  }

  function normaliseAlert(payload) {
    if (payload?.alert_event) return payload.alert_event;
    if (!payload?.should_alert) return null;
    const item = getLatestItem(payload);
    return {
      event_id: item?.frame_id || `legacy-${state.localCaptureCount}`,
      triggered_at: Date.now() / 1000,
      reason: item?.decision_reason || "共享画面可能偏离了当前目标，请回到当前任务。",
      mode: payload?.session?.monitoring_mode,
    };
  }

  async function captureAndUpload() {
    if (!state.running || state.finishing || state.inFlight) return;
    state.inFlight = true;
    state.localCaptureCount += 1;
    const frameId = `frame-${Date.now()}-${state.localCaptureCount}`;
    const filename = `${frameId}.jpg`;
    const capturedAt = Date.now() / 1000;
    let controller = null;
    let abortTimerId = 0;

    try {
      setLivePhase("capturing");
      elements.latestStatusLabel.textContent = "正在采集";
      if (elements.latestStatusIcon) elements.latestStatusIcon.textContent = "·";
      if (elements.latestStatusPanel) elements.latestStatusPanel.className = "focus-current-status state-waiting";
      elements.latestScore.textContent = "--";
      elements.latestScore.className = "score-badge muted";
      const blob = await captureBlob(filename);
      if (!state.running || state.finishing) return;
      setLivePhase("analysing");
      elements.latestStatusLabel.textContent = "正在分析";

      const formData = new FormData();
      formData.append("screenshot", blob, filename);
      formData.append("frame_id", frameId);
      formData.append("captured_at", String(capturedAt));
      controller = new AbortController();
      state.requestController = controller;
      abortTimerId = window.setTimeout(() => controller.abort("frame-timeout"), REQUEST_TIMEOUT_MS);
      const response = await fetch(`/api/session/${state.sessionId}/frame`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (isTerminalSessionResponse(response, payload)) {
        enterTerminalSessionState(payload.error);
        return;
      }
      if (!response.ok) throw new Error(payload.error || `服务器返回 ${response.status}`);
      if (!state.running || state.finishing) return;
      showAlert(normaliseAlert(payload));
      renderSessionPayload(payload);
    } catch (error) {
      if (!state.running || state.finishing) return;
      const timedOut = error?.name === "AbortError" || controller?.signal?.aborted;
      if (timedOut) {
        renderLatestItem({ state: "unscorable", reason: "本次判断超过 18 秒，没有得到结果，不影响下一次截图。" });
      } else {
        console.warn("截图上传失败", error);
        setLivePhase("network");
        elements.latestStatusLabel.textContent = "网络异常";
        if (elements.latestStatusIcon) elements.latestStatusIcon.textContent = "×";
        elements.latestScore.textContent = "--";
        elements.latestScore.className = "score-badge muted";
        elements.latestReason.textContent = "本次截图未成功送达，系统会在下一个采集点继续尝试。";
        if (elements.latestStatusPanel) elements.latestStatusPanel.className = "focus-current-status state-unscorable";
        announce("本次截图发送失败，系统会在下一个采集点继续尝试。");
      }
    } finally {
      clearTimeout(abortTimerId);
      if (state.requestController === controller) state.requestController = null;
      state.inFlight = false;
    }
  }

  function scheduleNextCapture() {
    if (!state.running || state.finishing || !state.started) return;
    const now = performance.now();
    const delay = Math.max(0, state.nextCaptureAt - now);
    clearTimeout(state.captureTimerId);
    state.captureTimerId = window.setTimeout(() => {
      if (!state.running || state.finishing || !state.started) return;
      const tickAt = performance.now();
      do state.nextCaptureAt += CAPTURE_INTERVAL_MS;
      while (state.nextCaptureAt <= tickAt);
      scheduleNextCapture();
      if (state.inFlight) {
        setLivePhase("waiting", "本次已跳过");
        return;
      }
      void captureAndUpload();
    }, delay);
  }

  function startCaptureClock() {
    if (state.started || !state.running || state.finishing) return;
    state.started = true;
    state.nextCaptureAt = performance.now();
    scheduleNextCapture();
  }

  function stopCaptureClock() {
    state.started = false;
    clearTimeout(state.captureTimerId);
    state.captureTimerId = 0;
    state.requestController?.abort("session-ending");
    state.requestController = null;
  }

  async function saveMonitoringPermission(granted) {
    try {
      await fetch("/api/user/permission", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monitoring_permission: granted }),
      });
    } catch (_error) {
      // Permission persistence is non-critical for the prototype.
    }
  }

  async function initScreenShare() {
    if (state.stream || state.shareRequestPending || !state.running || state.finishing || state.terminal) return;
    state.shareRequestPending = true;
    if (elements.screenShareButton) {
      elements.screenShareButton.disabled = true;
      elements.screenShareButton.setAttribute("aria-busy", "true");
      elements.screenShareButton.textContent = "正在打开选择器…";
    }
    setPermissionFeedback("请在浏览器弹出的窗口中选择要共享的标签页、窗口或屏幕。", "info");
    try {
      window.initAlertAudio?.();
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 3, max: 6 } },
        audio: false,
      });
      state.stream = stream;
      elements.captureVideo.srcObject = stream;
      await elements.captureVideo.play();
      await waitForVideoReady();
      void saveMonitoringPermission(true);
      stream.getVideoTracks()[0]?.addEventListener("ended", () => {
        if (state.running && !state.finishing) void window.completeSession("screen-ended");
      }, { once: true });
      setSharingActive(true);
      window.setMessage("success", "屏幕共享已启动，每 20 秒分析一次画面。");
      setLivePhase("waiting", "屏幕已就绪，等待下一次截图");
      startCaptureClock();
    } catch (error) {
      state.stream?.getTracks().forEach(track => track.stop());
      state.stream = null;
      if (elements.captureVideo) elements.captureVideo.srcObject = null;
      setSharingActive(false);
      setPermissionFeedback("没有开始共享。请重新选择一个标签页、窗口或屏幕后再试。", "error");
      setLivePhase("waiting", "请选择共享范围");
      announce("没有开始共享，请重新选择共享范围。");
    } finally {
      state.shareRequestPending = false;
      if (elements.screenShareButton) {
        elements.screenShareButton.disabled = false;
        elements.screenShareButton.setAttribute("aria-busy", "false");
        elements.screenShareButton.textContent = state.stream ? "共享已开始" : "重新选择共享范围";
      }
    }
  }

  async function completeSession(reason = "manual") {
    if (state.terminal) {
      window.location.assign("/");
      return;
    }
    if (state.finishing) return;
    state.finishing = true;
    state.running = false;
    stopCaptureClock();
    clearInterval(state.tickerIntervalId);
    clearTimeout(state.alertHideTimerId);
    if (state.stream) {
      state.stream.getTracks().forEach(track => track.stop());
      state.stream = null;
    }
    if (state.previewUrl) {
      URL.revokeObjectURL(state.previewUrl);
      state.previewUrl = "";
    }
    if (elements.stopButton) {
      elements.stopButton.disabled = true;
      elements.stopButton.textContent = "正在保存…";
    }
    setLivePhase("stopped", "正在保存本次记录");
    elements.latestStatusLabel.textContent = "正在结束";
    if (elements.latestStatusIcon) elements.latestStatusIcon.textContent = "·";
    if (elements.latestStatusPanel) elements.latestStatusPanel.className = "focus-current-status state-waiting";
    elements.latestReason.textContent = "正在保存记录，完成后将进入本轮报告。";

    try {
      const response = await fetch(`/api/session/${state.sessionId}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      const payload = await response.json().catch(() => ({}));
      if (isTerminalSessionResponse(response, payload)) {
        enterTerminalSessionState(payload.error);
        return;
      }
      if (!response.ok) throw new Error(payload.error || "保存会话失败");
      if (payload.success_url) {
        window.location.assign(payload.success_url);
        return;
      }
      window.location.assign("/report");
    } catch (error) {
      console.warn("会话保存失败", error);
      state.finishing = false;
      if (elements.stopButton) {
        elements.stopButton.disabled = false;
        elements.stopButton.textContent = "重试保存并查看报告";
      }
      setLivePhase("network", "记录保存失败，可点击重试");
      elements.latestStatusLabel.textContent = "保存失败";
      if (elements.latestStatusIcon) elements.latestStatusIcon.textContent = "×";
      if (elements.latestStatusPanel) elements.latestStatusPanel.className = "focus-current-status state-unscorable";
      elements.latestReason.textContent = "记录暂时没有保存成功，请检查网络后重试。";
      announce("记录暂时没有保存成功，请检查网络后重试。");
      window.setMessage("error", "本次记录尚未保存，请点击“重试保存并查看报告”。");
    }
  }

  async function initSession() {
    try {
      const response = await fetch(`/api/session/${state.sessionId}`);
      const payload = await response.json().catch(() => ({}));
      if (isTerminalSessionResponse(response, payload)) {
        enterTerminalSessionState(payload.error);
        return;
      }
      if (!response.ok) throw new Error(payload.error || "无法读取会话");
      state.latestPayload = payload;
      syncRuntimeClock(payload.session);
      renderSessionPayload(payload);
      state.tickerIntervalId = window.setInterval(updateRuntimeClock, 1000);
      updateRuntimeClock();
      setLivePhase("waiting", "请选择共享范围");
      if (elements.latestStatusLabel) elements.latestStatusLabel.textContent = "等待共享";
      queueGoalToggleRefresh();
    } catch (error) {
      console.error("获取会话数据失败", error);
      state.running = false;
      setLivePhase("network", "会话加载失败");
      if (elements.screenShareButton) elements.screenShareButton.disabled = true;
      setPermissionFeedback("无法读取这轮专注，请放弃本轮并返回首页后重试。", "error");
      window.setMessage("error", "获取会话数据失败，请返回首页重新开始。");
    }
  }

  window.initFocusPage = function initFocusPage() {
    elements = {
      elapsedTime: document.getElementById("elapsedTime"), remainingTime: document.getElementById("remainingTime"),
      progressPercent: document.getElementById("progressPercent"), sessionProgressBar: document.getElementById("sessionProgressBar"),
      sessionProgress: document.getElementById("sessionProgress"),
      maxPoints: document.getElementById("maxPoints"), currentPoints: document.getElementById("currentPoints"),
      sessionGoal: document.getElementById("sessionGoal"), capturedCount: document.getElementById("capturedCount"),
      distractCount: document.getElementById("distractCount"),
      alertCount: document.getElementById("alertCount"), latestStatusLabel: document.getElementById("latestStatusLabel"),
      latestStatusIcon: document.getElementById("latestStatusIcon"),
      latestStatusPanel: document.getElementById("latestStatusPanel"), liveAnnouncement: document.getElementById("focusLiveAnnouncement"),
      latestScore: document.getElementById("latestScore"), latestProcessing: document.getElementById("latestProcessing"),
      latestContext: document.getElementById("latestContext"), latestReason: document.getElementById("latestReason"),
      latestScoreVersion: document.getElementById("latestScoreVersion"),
      latestGoalRelevance: document.getElementById("latestGoalRelevance"),
      latestTaskEvidence: document.getElementById("latestTaskEvidence"),
      latestContextFit: document.getElementById("latestContextFit"),
      latestDistractionLevel: document.getElementById("latestDistractionLevel"),
      captureState: document.getElementById("captureState"), previewLabel: document.getElementById("previewLabel"),
      previewImage: document.getElementById("capturePreview"), previewPlaceholder: document.getElementById("previewPlaceholder"),
      captureVideo: document.getElementById("captureVideo"), captureCanvas: document.getElementById("captureCanvas"),
      stopButton: document.getElementById("stopSessionButton"), distractionList: document.getElementById("distractionList"),
      focusAlert: document.getElementById("focusAlert"), focusAlertText: document.getElementById("focusAlertText"),
      soundAlertToggle: document.getElementById("soundAlertToggle"),
      sessionShell: document.querySelector(".focus-session-shell"),
      goalTitle: document.getElementById("focusPageTitle"), goalToggleButton: document.getElementById("goalToggleButton"),
      permissionAlert: document.getElementById("permissionAlert"), permissionFeedback: document.getElementById("permissionFeedback"),
      screenShareButton: document.getElementById("screenShareButton"), exitFocusButton: document.getElementById("exitFocusButton"),
      actionDock: document.getElementById("focusActionDock"),
    };
    if (!elements.captureVideo || !elements.captureCanvas || !elements.stopButton) {
      console.error("专注页关键组件缺失");
      return;
    }

    state = {
      stream: null, running: true, started: false, inFlight: false, finishing: false, terminal: false,
      sessionId: window.currentSessionId, localStartedAt: Date.now(), durationSeconds: 0,
      maxPossiblePoints: 0, localCaptureCount: 0, alertCount: 0, clockSynced: false,
      captureTimerId: 0, tickerIntervalId: 0, alertHideTimerId: 0, nextCaptureAt: 0,
      requestController: null, previewUrl: "", latestPayload: null, seenAlertIds: new Set(), shareRequestPending: false,
    };

    window.completeSession = completeSession;
    window.initScreenShare = initScreenShare;
    setSharingActive(false);
    elements.stopButton.addEventListener("click", () => void completeSession("manual"));
    elements.screenShareButton?.addEventListener("click", () => void initScreenShare());
    elements.exitFocusButton?.addEventListener("click", () => void window.exitFocusWithoutPermission());
    elements.goalToggleButton?.addEventListener("click", () => {
      const expanded = !elements.goalTitle?.classList.contains("expanded");
      elements.goalTitle?.classList.toggle("expanded", expanded);
      elements.goalToggleButton.setAttribute("aria-expanded", String(expanded));
      elements.goalToggleButton.textContent = expanded ? "收起目标" : "展开目标";
    });
    elements.focusAlert?.querySelector("button")?.addEventListener("click", () => elements.focusAlert.classList.add("hidden"));
    if (elements.soundAlertToggle) {
      elements.soundAlertToggle.checked = window.getFocusSettings?.().sound_alert !== "disabled";
      elements.soundAlertToggle.addEventListener("change", () => {
        const settings = window.getFocusSettings?.() || {};
        settings.sound_alert = elements.soundAlertToggle.checked ? "enabled" : "disabled";
        localStorage.setItem("focus_settings", JSON.stringify(settings));
        if (elements.soundAlertToggle.checked) window.initAlertAudio?.();
      });
    }
    window.addEventListener("pagehide", () => {
      stopCaptureClock();
      clearInterval(state.tickerIntervalId);
      if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    }, { once: true });
    window.addEventListener("resize", queueGoalToggleRefresh);
    void initSession();
  };
})();
