const fields = {
  baseUrl: document.querySelector("#base-url"),
  token: document.querySelector("#token"),
  voice: document.querySelector("#voice"),
  prebufferMs: document.querySelector("#prebuffer-ms"),
  lowWatermarkMs: document.querySelector("#low-watermark-ms"),
  highWatermarkMs: document.querySelector("#high-watermark-ms"),
  maxChars: document.querySelector("#max-chars"),
};

const statusText = document.querySelector("#status-text");
const extensionOrigin = document.querySelector("#extension-origin");
const serviceStatus = document.querySelector("#service-status");
const onboardingStatus = document.querySelector("#onboarding-status");
const originCommand = document.querySelector("#origin-command");
const originSnippet = document.querySelector("#origin-snippet");
const voiceHint = document.querySelector("#voice-hint");
const actionMessage = document.querySelector("#action-message");
const readerActionButtons = {
  resumePage: document.querySelector("#resume-page"),
  continuePage: document.querySelector("#continue-page"),
  focusSourceTab: document.querySelector("#focus-source-tab"),
  previousSection: document.querySelector("#previous-section"),
  nextSection: document.querySelector("#next-section"),
  stopPlayback: document.querySelector("#stop-playback"),
};

async function loadPopup() {
  const config = await sendMessage({ type: "tts-extension:get-config" });
  extensionOrigin.textContent = config.extensionOrigin;
  fields.baseUrl.value = config.baseUrl;
  fields.token.value = config.token;
  fields.prebufferMs.value = config.prebufferMs;
  fields.lowWatermarkMs.value = config.lowWatermarkMs;
  fields.highWatermarkMs.value = config.highWatermarkMs;
  fields.maxChars.value = config.maxChars;
  await refreshServiceSnapshot(config.voice);
  await refreshState();
}

async function refreshState() {
  const state = await sendMessage({ type: "tts-extension:get-state" });
  statusText.textContent = formatPlaybackState(state);
  updateReaderActionState(state);
}

async function refreshServiceSnapshot(configuredVoice = fields.voice.value) {
  const snapshot = await sendMessage({ type: "tts-extension:get-service-snapshot" });
  serviceStatus.textContent = formatServiceSnapshot(snapshot);
  onboardingStatus.textContent = formatOnboardingStatus(snapshot);
  originCommand.textContent = snapshot.originCliCommand;
  originSnippet.textContent = snapshot.originConfigSnippet;
  populateVoiceOptions({
    voices: snapshot.voices,
    configuredVoice,
    defaultVoice: snapshot.defaultVoice,
  });
}

function populateVoiceOptions({ voices, configuredVoice, defaultVoice }) {
  fields.voice.replaceChildren();

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = defaultVoice
    ? `Use service default (${defaultVoice})`
    : "Use service default";
  fields.voice.append(defaultOption);

  let matchedConfiguredVoice = configuredVoice === "";
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.id;
    option.textContent = `${voice.name} (${voice.id})`;
    fields.voice.append(option);
    if (voice.id === configuredVoice) {
      matchedConfiguredVoice = true;
    }
  }

  if (configuredVoice && !matchedConfiguredVoice) {
    const configuredOption = document.createElement("option");
    configuredOption.value = configuredVoice;
    configuredOption.textContent = `Configured voice (${configuredVoice})`;
    fields.voice.append(configuredOption);
  }

  fields.voice.value = configuredVoice || "";
  if (voices.length) {
    const defaultText = defaultVoice ? ` Service default: ${defaultVoice}.` : "";
    voiceHint.textContent =
      `Discovered ${voices.length} voice(s) from the local service.` + defaultText;
  } else {
    voiceHint.textContent =
      "No voices were discovered yet. Check the base URL and local service startup.";
  }
}

document.querySelector("#save-config").addEventListener("click", async () => {
  try {
    const config = {
      baseUrl: fields.baseUrl.value.trim(),
      token: fields.token.value.trim(),
      voice: fields.voice.value.trim(),
      prebufferMs: Number(fields.prebufferMs.value),
      lowWatermarkMs: Number(fields.lowWatermarkMs.value),
      highWatermarkMs: Number(fields.highWatermarkMs.value),
      maxChars: Number(fields.maxChars.value),
    };
    await sendMessage({
      type: "tts-extension:save-config",
      config,
    });
    await refreshServiceSnapshot(config.voice);
    await refreshState();
    setActionMessage("Settings saved.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

document.querySelector("#refresh-service").addEventListener("click", async () => {
  try {
    await refreshServiceSnapshot();
    await refreshState();
    setActionMessage("Service snapshot refreshed.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

document.querySelector("#speak-selection").addEventListener("click", async () => {
  await runAction("tts-extension:speak-selection");
});

document.querySelector("#speak-page").addEventListener("click", async () => {
  await runAction("tts-extension:speak-page");
});

document.querySelector("#resume-page").addEventListener("click", async () => {
  await runAction("tts-extension:resume-page");
});

document.querySelector("#continue-page").addEventListener("click", async () => {
  await runAction("tts-extension:continue-page");
});

document.querySelector("#focus-source-tab").addEventListener("click", async () => {
  await runAction("tts-extension:focus-source-tab");
});

document.querySelector("#previous-section").addEventListener("click", async () => {
  await runAction("tts-extension:previous-section");
});

document.querySelector("#next-section").addEventListener("click", async () => {
  await runAction("tts-extension:next-section");
});

document.querySelector("#stop-playback").addEventListener("click", async () => {
  await runAction("tts-extension:stop");
});

document.querySelector("#copy-origin").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(extensionOrigin.textContent);
    setActionMessage("Extension origin copied.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

document.querySelector("#copy-command").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(originCommand.textContent);
    setActionMessage("Allow-list command copied.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

document.querySelector("#copy-snippet").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(originSnippet.textContent);
    setActionMessage("Allow-list snippet copied.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

setInterval(() => {
  refreshState().catch(() => undefined);
}, 1000);

loadPopup().catch((error) => {
  statusText.textContent = error.message;
  serviceStatus.textContent = error.message;
  onboardingStatus.textContent = error.message;
  setActionMessage(error.message, "error");
});

function sendMessage(message) {
  return chrome.runtime.sendMessage(message);
}

async function runAction(type) {
  try {
    const result = await sendMessage({ type });
    await refreshState();
    setActionMessage(result.message || "Action completed.", result.ok ? "success" : "error");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

function setActionMessage(message, kind = "info") {
  actionMessage.textContent = message;
  actionMessage.dataset.kind = kind;
}

function updateReaderActionState(state) {
  const baseCapabilities = resolveReaderBaseCapabilities(state);
  const capabilities = applySourceTabGuard(baseCapabilities, state);
  setActionButtonState(
    readerActionButtons.resumePage,
    capabilities.resumePage,
    pageActionUnavailableTitle(
      state,
      baseCapabilities.resumePage,
      "No resumable page progress is available."
    )
  );
  setActionButtonState(
    readerActionButtons.continuePage,
    capabilities.continuePage,
    pageActionUnavailableTitle(
      state,
      baseCapabilities.continuePage,
      "No truncated page continuation is available."
    )
  );
  setActionButtonState(
    readerActionButtons.previousSection,
    capabilities.previousSection,
    pageActionUnavailableTitle(
      state,
      baseCapabilities.previousSection,
      "No previous page section is available."
    )
  );
  setActionButtonState(
    readerActionButtons.nextSection,
    capabilities.nextSection,
    pageActionUnavailableTitle(
      state,
      baseCapabilities.nextSection,
      "No next page section is available."
    )
  );
  setActionButtonState(
    readerActionButtons.focusSourceTab,
    capabilities.focusSourceTab,
    focusSourceTabUnavailableTitle(state)
  );
  setActionButtonState(
    readerActionButtons.stopPlayback,
    capabilities.stopPlayback,
    "No active playback is running."
  );
}

function setActionButtonState(button, enabled, unavailableTitle) {
  button.disabled = !enabled;
  button.title = enabled ? "" : unavailableTitle;
  button.dataset.available = String(Boolean(enabled));
}

function resolveReaderCapabilities(state) {
  return applySourceTabGuard(resolveReaderBaseCapabilities(state), state);
}

function resolveReaderBaseCapabilities(state) {
  return {
    resumePage: canResumePage(state.readerProgress),
    continuePage: canContinuePage(state.pageCapture),
    previousSection: resolvePreviousSectionIndex(state) != null,
    nextSection: resolveNextSectionIndex(state) != null,
    focusSourceTab: canFocusSourceTab(state),
    stopPlayback: isActivePlaybackStatus(state.status),
  };
}

function applySourceTabGuard(capabilities, state) {
  const sourceTabReady = state.sourceTabActive !== false;
  return {
    ...capabilities,
    resumePage: capabilities.resumePage && sourceTabReady,
    continuePage: capabilities.continuePage && sourceTabReady,
    previousSection: capabilities.previousSection && sourceTabReady,
    nextSection: capabilities.nextSection && sourceTabReady,
    focusSourceTab: capabilities.focusSourceTab,
  };
}

function pageActionUnavailableTitle(state, baseCapability, fallbackTitle) {
  if (baseCapability && state.sourceTabActive === false) {
    return state.sourceTabMessage || "Switch back to the original page tab.";
  }
  return fallbackTitle;
}

function focusSourceTabUnavailableTitle(state) {
  const sourceTabId = Number(state.tabId);
  if (!Number.isFinite(sourceTabId) || sourceTabId <= 0) {
    return "No original page tab is available.";
  }
  if (state.sourceTabActive === true) {
    return "Original page tab is already active.";
  }
  return "No original page tab needs focus.";
}

function canFocusSourceTab(state) {
  const sourceTabId = Number(state.tabId);
  return Number.isFinite(sourceTabId) && sourceTabId > 0 && state.sourceTabActive === false;
}

function canResumePage(progress) {
  if (!progress) {
    return false;
  }
  const chunkIndex = Number(progress.text_chunk_index);
  const chunkCount = Number(progress.text_chunk_count);
  const percent = Number(progress.percent);
  if (!Number.isFinite(chunkIndex) || !Number.isFinite(chunkCount) || chunkCount <= 0) {
    return false;
  }
  if (Number.isFinite(percent) && percent >= 1) {
    return false;
  }
  return chunkIndex >= 0 && chunkIndex < chunkCount;
}

function canContinuePage(pageCapture) {
  if (!pageCapture?.truncated) {
    return false;
  }
  const nextTextCharStart = Number(pageCapture?.structure?.nextTextCharStart);
  const currentTextCharStart = Number(pageCapture?.structure?.startTextChar ?? 0);
  if (!Number.isFinite(nextTextCharStart) || nextTextCharStart <= 0) {
    return false;
  }
  return !Number.isFinite(currentTextCharStart) || nextTextCharStart > currentTextCharStart;
}

function resolveNextSectionIndex(state) {
  const structure = state.pageCapture?.structure ?? {};
  const sections = pageSections(structure);
  const completedTextChars = completedReaderTextChars(state.readerProgress);
  const nextSection = sections.find((section) => {
    const textCharStart = Number(section?.textCharStart ?? 0);
    return Number.isFinite(textCharStart) && textCharStart > completedTextChars;
  });
  if (nextSection) {
    const sectionIndex = Number(nextSection.index);
    return Number.isFinite(sectionIndex) && sectionIndex >= 0 ? Math.floor(sectionIndex) : null;
  }
  return resolveNextUncapturedSectionIndex(state, structure, sections);
}

function resolvePreviousSectionIndex(state) {
  const structure = state.pageCapture?.structure ?? {};
  const sections = pageSections(structure);
  const currentSectionIndex = resolveCurrentSectionIndex(state, structure, sections);
  if (currentSectionIndex == null || currentSectionIndex <= 0) {
    return null;
  }
  return currentSectionIndex - 1;
}

function resolveCurrentSectionIndex(state, structure, sections) {
  const completedTextChars = completedReaderTextChars(state.readerProgress);
  const sortedSections = sections
    .slice()
    .sort((left, right) => Number(left?.textCharStart ?? 0) - Number(right?.textCharStart ?? 0));
  let currentSectionIndex = null;
  for (const section of sortedSections) {
    const textCharStart = Number(section?.textCharStart ?? 0);
    const sectionIndex = Number(section?.index);
    if (
      Number.isFinite(textCharStart) &&
      Number.isFinite(sectionIndex) &&
      textCharStart <= completedTextChars
    ) {
      currentSectionIndex = Math.floor(sectionIndex);
    }
  }
  if (currentSectionIndex == null) {
    const startSectionIndex = Number(structure.startSectionIndex ?? 0);
    currentSectionIndex = Number.isFinite(startSectionIndex) ? Math.floor(startSectionIndex) : 0;
  }
  return currentSectionIndex;
}

function resolveNextUncapturedSectionIndex(state, structure, sections) {
  if (!state.pageCapture?.truncated) {
    return null;
  }
  const nextSectionIndex = Number(structure.nextSectionIndex);
  if (!Number.isFinite(nextSectionIndex) || nextSectionIndex < 0) {
    return null;
  }
  const currentSectionIndex = resolveCurrentSectionIndex(state, structure, sections);
  if (currentSectionIndex != null && nextSectionIndex <= currentSectionIndex) {
    return null;
  }
  return Math.floor(nextSectionIndex);
}

function completedReaderTextChars(progress) {
  const completedTextChars = Number(progress?.completed_text_chars ?? progress?.text_char_end ?? 0);
  return Number.isFinite(completedTextChars) ? Math.max(0, completedTextChars) : 0;
}

function pageSections(structure) {
  return Array.isArray(structure.sections) ? structure.sections : [];
}

function isActivePlaybackStatus(status) {
  return new Set(["connecting", "buffering", "streaming", "draining"]).has(status);
}

function formatPlaybackState(state) {
  const lines = [
    `Status: ${state.status}`,
    `Message: ${state.message}`,
    state.source ? `Source: ${state.source}` : null,
    state.activeStreamId ? `Stream: ${state.activeStreamId}` : null,
    state.readerProgress ? `Progress: ${formatReaderProgress(state.readerProgress)}` : null,
    state.pageCapture ? `Page Capture: ${formatPageCapture(state.pageCapture)}` : null,
    state.pageCapture ? formatLongPageStatus(state) : null,
    state.sourceTabMessage ? `Source Tab: ${state.sourceTabMessage}` : null,
    state.bufferedMs != null ? `Buffered: ${state.bufferedMs} ms` : null,
    state.underrunCount != null ? `Underruns: ${state.underrunCount}` : null,
    state.offscreenReady != null ? `Offscreen Ready: ${state.offscreenReady}` : null,
    state.lastEvent ? `Last Event: ${state.lastEvent}` : null,
  ];
  return lines.filter(Boolean).join("\n");
}

function formatReaderProgress(progress) {
  const chunkIndex = Number(progress.text_chunk_index ?? 0);
  const chunkCount = Number(progress.text_chunk_count ?? 0);
  const percent = Math.round(Number(progress.percent ?? 0) * 100);
  if (chunkCount > 0) {
    return `${Math.min(chunkIndex + 1, chunkCount)}/${chunkCount} chunks (${percent}%)`;
  }
  return `${percent}%`;
}

function formatPageCapture(capture) {
  const textChars = Number(capture.textChars ?? 0);
  const maxChars = Number(capture.maxChars ?? 0);
  const readableBlocks = Number(capture.readableBlocks ?? 0);
  const source = capture.source || "unknown";
  const status = capture.truncated ? "truncated" : "complete";
  const blocks = readableBlocks > 0 ? `, ${readableBlocks} blocks` : "";
  const structure = formatPageStructure(capture.structure);
  return `${textChars}/${maxChars} chars, ${status}, ${source}${blocks}${structure}`;
}

function formatLongPageStatus(state) {
  const capture = state.pageCapture;
  const structure = capture?.structure;
  if (!structure) {
    return null;
  }
  const startTextChar = Number(structure.startTextChar ?? 0);
  const nextTextCharStart =
    structure.nextTextCharStart == null ? null : Number(structure.nextTextCharStart);
  const nextSectionIndex =
    structure.nextSectionIndex == null ? null : Number(structure.nextSectionIndex);
  const hasContinuation =
    Boolean(capture.truncated) && Number.isFinite(nextTextCharStart) && nextTextCharStart > 0;
  const hasLongPageSignal =
    hasContinuation ||
    (Number.isFinite(startTextChar) && startTextChar > 0) ||
    Number.isFinite(nextSectionIndex);
  if (!hasLongPageSignal) {
    return null;
  }

  const continuationLabel =
    state.status === "done" ? "auto-continue ready" : "next continuation char";
  const details = [
    Number.isFinite(startTextChar) && startTextChar > 0
      ? `segment starts at char ${startTextChar}`
      : "first page segment",
    state.source === "page-auto-continue" ? "automatic continuation active" : null,
    hasContinuation ? `${continuationLabel} ${nextTextCharStart}` : null,
    Number.isFinite(nextSectionIndex) ? `next known section ${nextSectionIndex + 1}` : null,
  ].filter(Boolean);
  return `Long Page: ${details.join(", ")}`;
}

function formatPageStructure(structure) {
  if (!structure) {
    return "";
  }
  const headingCount = Number(structure.headingCount ?? 0);
  const capturedHeadingCount = Number(structure.capturedHeadingCount ?? 0);
  const bodyBlockCount = Number(structure.bodyBlockCount ?? 0);
  const listItemCount = Number(structure.listItemCount ?? 0);
  const quoteBlockCount = Number(structure.quoteBlockCount ?? 0);
  const startSectionIndex = Number(structure.startSectionIndex ?? 0);
  const startTextChar = Number(structure.startTextChar ?? 0);
  const nextTextCharStart =
    structure.nextTextCharStart == null ? null : Number(structure.nextTextCharStart);
  const nextSectionIndex =
    structure.nextSectionIndex == null ? null : Number(structure.nextSectionIndex);
  const details = [
    startSectionIndex > 0 ? `from section ${startSectionIndex + 1}` : null,
    startTextChar > 0 ? `from char ${startTextChar}` : null,
    Number.isFinite(nextTextCharStart) ? `continue char ${nextTextCharStart}` : null,
    Number.isFinite(nextSectionIndex) ? `next section ${nextSectionIndex + 1}` : null,
    headingCount > 0 ? `${capturedHeadingCount}/${headingCount} headings` : null,
    bodyBlockCount > 0 ? `${bodyBlockCount} body` : null,
    listItemCount > 0 ? `${listItemCount} list` : null,
    quoteBlockCount > 0 ? `${quoteBlockCount} quote` : null,
  ].filter(Boolean);
  return details.length ? `, ${details.join(", ")}` : "";
}

function formatServiceSnapshot(snapshot) {
  const checks = snapshot.health?.checks ?? {};
  const lines = [
    `Reachable: ${snapshot.reachable}`,
    `Message: ${snapshot.message}`,
    `Health: ${snapshot.health?.status ?? "unavailable"}`,
    `Backend Ready: ${formatReadinessCheck(checks.backend_ready)}`,
    `Default Voice Loaded: ${formatReadinessCheck(checks.default_voice_loaded)}`,
    `Default Voice: ${snapshot.defaultVoice || "none"}`,
    `Voices Discovered: ${snapshot.voices.length}`,
    `Auth Enabled: ${snapshot.authEnabled}`,
    Object.keys(checks).length ? `Checks: ${JSON.stringify(checks)}` : null,
  ];
  return lines.filter(Boolean).join("\n");
}

function formatOnboardingStatus(snapshot) {
  const checks = snapshot.health?.checks ?? {};
  const checklist = [
    checklistLine("Service reachable", snapshot.reachable, snapshot.message),
    checklistLine("Token saved", Boolean(fields.token.value.trim()), "Paste config/token.txt"),
    checklistLine(
      "Allow-list command ready",
      Boolean(snapshot.originCliCommand),
      snapshot.originCliCommand
    ),
    checklistLine(
      "Allow-list snippet ready",
      Boolean(snapshot.originConfigSnippet),
      snapshot.extensionOrigin
    ),
    checklistLine(
      "Voice available",
      snapshot.voices.length > 0,
      `${snapshot.voices.length} voice(s) discovered`
    ),
    checklistLine(
      "Backend ready",
      checks.backend_ready === true,
      formatReadinessCheck(checks.backend_ready)
    ),
    checklistLine(
      "Default voice loaded",
      checks.default_voice_loaded === true,
      formatReadinessCheck(checks.default_voice_loaded)
    ),
    checklistLine(
      "Health ok",
      snapshot.health?.status === "ok",
      snapshot.health?.status ?? "unavailable"
    ),
  ];
  return checklist.join("\n");
}

function formatReadinessCheck(value) {
  if (value === true) {
    return "true";
  }
  if (value === false) {
    return "false";
  }
  return "unknown";
}

function checklistLine(label, ok, detail) {
  const marker = ok ? "[ok]" : "[todo]";
  return `${marker} ${label}: ${detail || "pending"}`;
}
