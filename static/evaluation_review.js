(() => {
  "use strict";

  const samples = Array.isArray(window.evaluationReviewSamples)
    ? [...window.evaluationReviewSamples]
    : [];
  const labelNames = {
    focused: "目标相关",
    uncertain: "不确定",
    distracted: "目标无关",
    unscorable: "无法评分",
  };
  const hotkeys = { "1": "focused", "2": "uncertain", "3": "distracted", "4": "unscorable" };
  const SCORING_RUBRIC_VERSION = "multidim-v1";

  const elements = {
    workspace: document.getElementById("reviewWorkspace"),
    empty: document.getElementById("reviewEmpty"),
    message: document.getElementById("reviewMessage"),
    pendingCount: document.getElementById("pendingCount"),
    image: document.getElementById("reviewImage"),
    samplePosition: document.getElementById("samplePosition"),
    sampleId: document.getElementById("sampleId"),
    goal: document.getElementById("reviewGoal"),
    discard: document.getElementById("discardSample"),
  };
  const actionButtons = Array.from(document.querySelectorAll(".review-label-button"));
  const scoreInputs = Array.from(document.querySelectorAll(".human-score-input"));
  let busy = false;
  let imageReady = false;
  let focusWhenReady = false;

  function currentSample() {
    return samples[0] || null;
  }

  function showMessage(type, text) {
    if (!elements.message) return;
    elements.message.textContent = text || "";
    elements.message.classList.toggle("hidden", !text);
    elements.message.classList.remove("success", "error", "info");
    if (text) elements.message.classList.add(type);
  }

  function updateActionAvailability() {
    if (elements.workspace) elements.workspace.setAttribute("aria-busy", String(busy));
    actionButtons.forEach(button => { button.disabled = busy || !imageReady; });
    scoreInputs.forEach(input => { input.disabled = busy; });
    if (elements.discard) elements.discard.disabled = busy;
  }

  function setBusy(value) {
    busy = value;
    if (elements.workspace) elements.workspace.setAttribute("aria-busy", String(value));
    updateActionAvailability();
  }

  function render() {
    const sample = currentSample();
    if (elements.pendingCount) elements.pendingCount.textContent = String(samples.length);
    elements.workspace?.classList.toggle("hidden", !sample);
    elements.empty?.classList.toggle("hidden", Boolean(sample));
    imageReady = false;
    if (!sample) {
      updateActionAvailability();
      return;
    }

    if (elements.image) {
      elements.image.classList.add("hidden");
      elements.image.dataset.sampleId = sample.sample_id;
      elements.image.src = sample.image_url;
      elements.image.alt = `待复核截图，专注目标：${sample.goal || "未提供"}`;
      if (elements.image.complete && elements.image.naturalWidth > 0) {
        imageReady = true;
        elements.image.classList.remove("hidden");
      }
    }
    if (elements.samplePosition) elements.samplePosition.textContent = `当前第 1 张，共 ${samples.length} 张`;
    if (elements.sampleId) elements.sampleId.textContent = sample.sample_id;
    if (elements.goal) elements.goal.textContent = sample.goal || "未提供目标";
    updateActionAvailability();
  }

  function focusAfterAdvance() {
    if (currentSample()) {
      if (imageReady) actionButtons[0]?.focus();
      else focusWhenReady = true;
    } else {
      elements.empty?.querySelector("a")?.focus();
    }
  }

  async function postAction(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      // A generic message below is more useful than exposing an HTML error page.
    }
    if (!response.ok) throw new Error(payload.message || payload.error || `请求失败（${response.status}）`);
    return payload;
  }

  function resetHumanScores() {
    scoreInputs.forEach(input => { input.value = ""; });
  }

  function buildHumanAnnotation(label) {
    if (label === "unscorable") {
      return { scoring_rubric_version: SCORING_RUBRIC_VERSION };
    }
    const annotation = { scoring_rubric_version: SCORING_RUBRIC_VERSION };
    for (const input of scoreInputs) {
      const field = input.dataset.scoreField;
      if (!field || input.value === "") {
        input.focus();
        throw new Error("请先填写全部四项维度、总体证据分和标注把握；无法辨识的图片可直接选“无法评分”。");
      }
      const value = Number(input.value);
      if (!Number.isFinite(value)) {
        input.focus();
        throw new Error("人工评分包含无效数值，请重新选择。");
      }
      annotation[field] = value;
    }
    const integerFields = ["goal_relevance", "task_evidence", "context_fit", "distraction_level", "overall_score"];
    if (integerFields.some(field => !Number.isInteger(annotation[field]))) {
      throw new Error("四项维度和总体证据分必须是整数。");
    }
    return annotation;
  }

  async function submitLabel(label) {
    const sample = currentSample();
    if (!sample || busy || !imageReady || !labelNames[label]) return;
    let annotation;
    try {
      annotation = buildHumanAnnotation(label);
    } catch (error) {
      showMessage("error", error.message);
      return;
    }
    setBusy(true);
    showMessage("info", `正在保存“${labelNames[label]}”标签…`);
    let advanced = false;
    try {
      const response = await postAction(sample.label_url, { label, annotation });
      samples.shift();
      if (Number.isInteger(response.pending_count) && response.pending_count !== samples.length) {
        window.location.reload();
        return;
      }
      showMessage("success", `已由人工标记为“${labelNames[label]}”。`);
      resetHumanScores();
      render();
      advanced = true;
    } catch (error) {
      showMessage("error", `保存失败：${error.message}`);
    } finally {
      setBusy(false);
      if (advanced) focusAfterAdvance();
    }
  }

  async function discardCurrent() {
    const sample = currentSample();
    if (!sample || busy) return;
    const confirmed = window.confirm("确定删除这张候选截图吗？删除后不会进入评测集。");
    if (!confirmed) return;
    setBusy(true);
    showMessage("info", "正在删除含敏感信息或不适合评测的候选…");
    let advanced = false;
    try {
      const response = await postAction(sample.discard_url, { reason: "manual_privacy_review" });
      samples.shift();
      if (Number.isInteger(response.pending_count) && response.pending_count !== samples.length) {
        window.location.reload();
        return;
      }
      showMessage("success", "候选已删除，未写入人工标签。");
      render();
      advanced = true;
    } catch (error) {
      showMessage("error", `删除失败：${error.message}`);
    } finally {
      setBusy(false);
      if (advanced) focusAfterAdvance();
    }
  }

  actionButtons.forEach(button => {
    button.addEventListener("click", () => submitLabel(button.dataset.label));
  });
  elements.discard?.addEventListener("click", discardCurrent);
  document.addEventListener("keydown", event => {
    if (event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
    const label = hotkeys[event.key];
    if (!label || busy || !imageReady || !currentSample()) return;
    event.preventDefault();
    submitLabel(label);
  });
  elements.image?.addEventListener("load", () => {
    const sample = currentSample();
    if (!sample || elements.image?.dataset.sampleId !== sample.sample_id) return;
    imageReady = true;
    elements.image.classList.remove("hidden");
    updateActionAvailability();
    if (focusWhenReady) {
      focusWhenReady = false;
      actionButtons[0]?.focus();
    }
  });
  elements.image?.addEventListener("error", () => {
    imageReady = false;
    elements.image.classList.add("hidden");
    updateActionAvailability();
    showMessage("error", "截图读取失败；该样本可能已被移除，请刷新页面。");
  });

  render();
})();
