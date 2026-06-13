const DEFAULT_CONFIG = {
  baseUrl: "http://127.0.0.1:7777",
  token: "",
  voice: "",
  prebufferMs: 180,
  lowWatermarkMs: 100,
  highWatermarkMs: 600,
  maxChars: 24000,
};

let playbackState = {
  status: "idle",
  message: "Ready",
  activeStreamId: null,
};

void initializeExtensionState();

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({
    id: "tts-platform-speak-selection",
    title: "Speak selected text",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "tts-platform-speak-selection") {
    return;
  }
  const text = (info.selectionText || "").trim();
  if (!text) {
    return;
  }
  await startPlayback({
    text,
    source: "context-menu",
    tabId: tab?.id ?? null,
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    switch (message?.type) {
      case "tts-extension:get-config":
        sendResponse(await getConfig());
        return;
      case "tts-extension:save-config":
        await chrome.storage.local.set(sanitizeConfig(message.config ?? {}));
        sendResponse(await getConfig());
        return;
      case "tts-extension:get-state":
        sendResponse(await getPlaybackState());
        return;
      case "tts-extension:get-service-snapshot":
        sendResponse(await getServiceSnapshot());
        return;
      case "tts-extension:speak-selection":
        sendResponse(await speakSelection());
        return;
      case "tts-extension:speak-page":
        sendResponse(await speakPage());
        return;
      case "tts-extension:resume-page":
        sendResponse(await resumePage());
        return;
      case "tts-extension:stop":
        await stopPlayback();
        sendResponse({ ok: true });
        return;
      case "tts-extension:playback-state":
        await setPlaybackState({
          ...playbackState,
          ...(message.state ?? {}),
        });
        sendResponse({ ok: true });
        return;
      default:
        sendResponse({ ok: false, message: "Unknown extension message." });
    }
  })().catch((error) => {
    void setPlaybackState({
      status: "error",
      message: error.message,
      activeStreamId: null,
      readerProgress: playbackState.readerProgress ?? null,
      pageCapture: playbackState.pageCapture ?? null,
    });
    sendResponse({ ok: false, message: error.message });
  });

  return true;
});

async function speakSelection() {
  const tab = await getActiveTab();
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "tts-extension:get-selection",
  });
  const text = (response?.text || "").trim();
  if (!text) {
    return { ok: false, message: "No selected text found." };
  }
  await startPlayback({ text, source: "selection", tabId: tab.id });
  return { ok: true, message: "Started speaking selection." };
}

async function speakPage() {
  const tab = await getActiveTab();
  const config = await getConfig();
  const capture = await getPageCapture(tab.id, config.maxChars);
  if (!capture.text) {
    return { ok: false, message: "No page text found." };
  }
  await startPlayback({
    text: capture.text,
    source: "page",
    tabId: tab.id,
    pageCapture: capture.meta,
  });
  return {
    ok: true,
    message: `Started speaking page text.${formatCaptureSuffix(capture.meta)}`,
  };
}

async function resumePage() {
  const currentState = await getPlaybackState();
  const startTextChunkIndex = resolveResumeTextChunkIndex(currentState.readerProgress);
  if (startTextChunkIndex == null) {
    return { ok: false, message: "No resumable page progress is available." };
  }

  const tab = await getActiveTab();
  const config = await getConfig();
  const capture = await getPageCapture(tab.id, config.maxChars);
  if (!capture.text) {
    return { ok: false, message: "No page text found." };
  }

  await startPlayback({
    text: capture.text,
    source: "page-resume",
    tabId: tab.id,
    startTextChunkIndex,
    pageCapture: capture.meta,
  });
  return {
    ok: true,
    message: `Resumed page playback from chunk ${
      startTextChunkIndex + 1
    }.${formatCaptureSuffix(capture.meta)}`,
  };
}

async function getPageCapture(tabId, maxChars) {
  const response = await chrome.tabs.sendMessage(tabId, {
    type: "tts-extension:get-page-text",
    maxChars,
  });
  const text = (response?.text || "").trim();
  return {
    text,
    meta: sanitizePageCaptureMeta(response?.meta, {
      textChars: text.length,
      maxChars,
    }),
  };
}

async function startPlayback({
  text,
  source,
  tabId,
  startTextChunkIndex = 0,
  pageCapture = null,
}) {
  const config = await getConfig();
  if (!config.token) {
    throw new Error("Missing token. Open the popup and save a service token first.");
  }
  await setPlaybackState({
    status: "connecting",
    message: `Starting ${source} playback`,
    activeStreamId: null,
    source,
    tabId,
    readerProgress: null,
    startTextChunkIndex,
    pageCapture,
  });
  const response = await sendOffscreenMessage({
    type: "tts-extension:start-stream",
    payload: {
      ...config,
      text,
      startTextChunkIndex,
      extensionOrigin: config.extensionOrigin,
    },
  });
  if (!response?.ok) {
    throw new Error(response?.message || "Failed to start offscreen playback.");
  }
}

async function stopPlayback() {
  const currentState = await getPlaybackState();
  if (await hasOffscreenDocument()) {
    await sendOffscreenMessage({
      type: "tts-extension:stop-stream",
    });
    return;
  }

  await setPlaybackState({
    ...currentState,
    status: "idle",
    message: "Ready",
    activeStreamId: null,
  });
}

async function getConfig() {
  const stored = await chrome.storage.local.get(DEFAULT_CONFIG);
  const sanitized = sanitizeConfig(stored);
  return {
    ...DEFAULT_CONFIG,
    ...sanitized,
    extensionOrigin: new URL(chrome.runtime.getURL("")).origin,
  };
}

async function getPlaybackState() {
  const stored = await chrome.storage.session.get({ playbackState });
  playbackState = {
    ...playbackState,
    ...(stored.playbackState ?? {}),
  };

  const offscreenReady = await hasOffscreenDocument();
  if (!offscreenReady && isActivePlaybackStatus(playbackState.status)) {
    return {
      ...playbackState,
      offscreenReady,
      status: "interrupted",
      message: "Playback was interrupted because the offscreen document is unavailable.",
    };
  }

  return {
    ...playbackState,
    offscreenReady,
  };
}

async function getServiceSnapshot() {
  const config = await getConfig();
  const snapshot = {
    baseUrl: config.baseUrl,
    extensionOrigin: config.extensionOrigin,
    originConfigSnippet: buildOriginConfigSnippet(config.extensionOrigin),
    reachable: false,
    health: null,
    voices: [],
    defaultVoice: config.voice || "",
    authEnabled: true,
    message: "Service has not been contacted yet.",
  };

  try {
    const [healthResponse, voicesResponse] = await Promise.all([
      fetchJson(config.baseUrl + "/v1/health"),
      fetchJson(config.baseUrl + "/v1/voices"),
    ]);

    return {
      ...snapshot,
      reachable: true,
      health: healthResponse,
      voices: voicesResponse.voices ?? [],
      defaultVoice: voicesResponse.default_voice ?? "",
      authEnabled: Boolean(healthResponse.auth_enabled),
      message: `Connected to local service (${healthResponse.status}).`,
    };
  } catch (error) {
    return {
      ...snapshot,
      message: error.message,
    };
  }
}

function sanitizeConfig(config) {
  const prebufferMs = sanitizeNumber(config.prebufferMs, DEFAULT_CONFIG.prebufferMs, 50);
  const lowWatermarkMs = sanitizeNumber(
    config.lowWatermarkMs,
    DEFAULT_CONFIG.lowWatermarkMs,
    20
  );
  const highWatermarkMs = Math.max(
    sanitizeNumber(config.highWatermarkMs, DEFAULT_CONFIG.highWatermarkMs, 100),
    prebufferMs
  );
  const maxChars = sanitizeNumber(config.maxChars, DEFAULT_CONFIG.maxChars, 200, 48000);

  return {
    baseUrl: String(config.baseUrl || DEFAULT_CONFIG.baseUrl).trim() || DEFAULT_CONFIG.baseUrl,
    token: String(config.token || "").trim(),
    voice: String(config.voice || "").trim(),
    prebufferMs,
    lowWatermarkMs: Math.min(lowWatermarkMs, prebufferMs),
    highWatermarkMs,
    maxChars,
  };
}

function sanitizeNumber(value, fallback, minimum, maximum = Number.POSITIVE_INFINITY) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(minimum, Math.min(maximum, Math.round(parsed)));
}

function resolveResumeTextChunkIndex(progress) {
  if (!progress) {
    return null;
  }
  const chunkCount = Number(progress.text_chunk_count ?? 0);
  const chunkIndex = Number(progress.text_chunk_index ?? 0);
  const percent = Number(progress.percent ?? 0);
  if (!Number.isFinite(chunkCount) || chunkCount <= 0) {
    return null;
  }
  if (!Number.isFinite(chunkIndex) || chunkIndex < 0) {
    return null;
  }
  if (Number.isFinite(percent) && percent >= 1) {
    return null;
  }
  return Math.min(Math.floor(chunkIndex), Math.floor(chunkCount) - 1);
}

function sanitizePageCaptureMeta(meta, fallback) {
  const textChars = sanitizeNumber(meta?.textChars, fallback.textChars, 0);
  const maxChars = sanitizeNumber(meta?.maxChars, fallback.maxChars, 200, 48000);
  return {
    source: String(meta?.source || "unknown"),
    textChars,
    maxChars,
    truncated: Boolean(meta?.truncated),
    readableBlocks: sanitizeNumber(meta?.readableBlocks, 0, 0),
  };
}

function formatCaptureSuffix(capture) {
  if (!capture) {
    return "";
  }
  const textChars = Number(capture.textChars ?? 0);
  const maxChars = Number(capture.maxChars ?? 0);
  const status = capture.truncated ? " truncated" : "";
  return ` Captured ${textChars} chars${status} at limit ${maxChars}.`;
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab?.id) {
    throw new Error("No active tab is available.");
  }
  return tab;
}

async function ensureOffscreenDocument() {
  const offscreenUrl = "offscreen/offscreen.html";
  if (await hasOffscreenDocument()) {
    return;
  }
  await chrome.offscreen.createDocument({
    url: offscreenUrl,
    reasons: [chrome.offscreen.Reason.AUDIO_PLAYBACK],
    justification: "Play streamed PCM audio from the local TTS platform.",
  });
}

async function hasOffscreenDocument() {
  if (!chrome.offscreen?.hasDocument) {
    return false;
  }
  return chrome.offscreen.hasDocument();
}

async function persistPlaybackState(nextState) {
  await chrome.storage.session.set({
    playbackState: nextState,
  });
}

async function sendOffscreenMessage(message, allowRetry = true) {
  await ensureOffscreenDocument();
  try {
    return await chrome.runtime.sendMessage(message);
  } catch (error) {
    if (!allowRetry || !shouldRetryOffscreenMessage(error)) {
      throw error;
    }
    await recreateOffscreenDocument();
    return chrome.runtime.sendMessage(message);
  }
}

async function recreateOffscreenDocument() {
  if (await hasOffscreenDocument()) {
    await closeOffscreenDocument();
  }
  await ensureOffscreenDocument();
}

async function closeOffscreenDocument() {
  if (!chrome.offscreen?.closeDocument) {
    return;
  }
  await chrome.offscreen.closeDocument();
}

function shouldRetryOffscreenMessage(error) {
  return String(error?.message || "").includes("Receiving end does not exist");
}

async function setPlaybackState(nextState) {
  playbackState = nextState;
  await persistPlaybackState(playbackState);
  await updateBadge();
}

async function fetchJson(url) {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`Service request failed with ${response.status} ${response.statusText}.`);
  }
  return response.json();
}

function buildOriginConfigSnippet(extensionOrigin) {
  return [
    "[security]",
    `allowed_origins = ["${extensionOrigin}"]`,
  ].join("\n");
}

function isActivePlaybackStatus(status) {
  return new Set(["connecting", "buffering", "streaming", "draining"]).has(status);
}

async function initializeExtensionState() {
  const restoredState = await getPlaybackState();
  if (!restoredState.offscreenReady && isActivePlaybackStatus(restoredState.status)) {
    await setPlaybackState({
      status: "interrupted",
      message: "Recovered after background restart, but playback was no longer active.",
      activeStreamId: null,
      source: restoredState.source,
      tabId: restoredState.tabId,
      readerProgress: restoredState.readerProgress ?? null,
      pageCapture: restoredState.pageCapture ?? null,
      lastEvent: "recovered",
    });
    return;
  }

  playbackState = restoredState;
  await updateBadge();
}

async function updateBadge() {
  const badgeText = {
    idle: "",
    connecting: "...",
    buffering: "...",
    streaming: "ON",
    draining: "ON",
    done: "",
    cancelled: "",
    interrupted: "ERR",
    error: "ERR",
  }[playbackState.status] ?? "";

  await chrome.action.setBadgeText({ text: badgeText });
  await chrome.action.setBadgeBackgroundColor({
    color: playbackState.status === "error" ? "#9f1d35" : "#165dff",
  });
}
