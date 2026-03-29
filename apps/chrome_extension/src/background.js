const DEFAULT_CONFIG = {
  baseUrl: "http://127.0.0.1:7777",
  token: "",
  voice: "",
  prebufferMs: 180,
  lowWatermarkMs: 100,
  highWatermarkMs: 600,
  maxChars: 4000,
};

let playbackState = {
  status: "idle",
  message: "Ready",
  activeStreamId: null,
};

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
        sendResponse({ ...playbackState });
        return;
      case "tts-extension:speak-selection":
        sendResponse(await speakSelection());
        return;
      case "tts-extension:speak-page":
        sendResponse(await speakPage());
        return;
      case "tts-extension:stop":
        await stopPlayback();
        sendResponse({ ok: true });
        return;
      case "tts-extension:playback-state":
        playbackState = {
          ...playbackState,
          ...(message.state ?? {}),
        };
        await updateBadge();
        sendResponse({ ok: true });
        return;
      default:
        sendResponse({ ok: false, message: "Unknown extension message." });
    }
  })().catch((error) => {
    playbackState = {
      status: "error",
      message: error.message,
      activeStreamId: null,
    };
    updateBadge();
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
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "tts-extension:get-page-text",
    maxChars: config.maxChars,
  });
  const text = (response?.text || "").trim();
  if (!text) {
    return { ok: false, message: "No page text found." };
  }
  await startPlayback({ text, source: "page", tabId: tab.id });
  return { ok: true, message: "Started speaking page text." };
}

async function startPlayback({ text, source, tabId }) {
  const config = await getConfig();
  if (!config.token) {
    throw new Error("Missing token. Open the popup and save a service token first.");
  }
  await ensureOffscreenDocument();
  playbackState = {
    status: "connecting",
    message: `Starting ${source} playback`,
    activeStreamId: null,
    source,
    tabId,
  };
  await updateBadge();
  await chrome.runtime.sendMessage({
    type: "tts-extension:start-stream",
    payload: {
      ...config,
      text,
      extensionOrigin: config.extensionOrigin,
    },
  });
}

async function stopPlayback() {
  await ensureOffscreenDocument();
  await chrome.runtime.sendMessage({
    type: "tts-extension:stop-stream",
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
  const maxChars = sanitizeNumber(config.maxChars, DEFAULT_CONFIG.maxChars, 200, 12000);

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
  if (chrome.offscreen.hasDocument) {
    const hasDocument = await chrome.offscreen.hasDocument();
    if (hasDocument) {
      return;
    }
  }
  await chrome.offscreen.createDocument({
    url: offscreenUrl,
    reasons: [chrome.offscreen.Reason.AUDIO_PLAYBACK],
    justification: "Play streamed PCM audio from the local TTS platform.",
  });
}

async function updateBadge() {
  const badgeText = {
    idle: "",
    connecting: "...",
    streaming: "ON",
    draining: "ON",
    done: "",
    cancelled: "",
    error: "ERR",
  }[playbackState.status] ?? "";

  await chrome.action.setBadgeText({ text: badgeText });
  await chrome.action.setBadgeBackgroundColor({
    color: playbackState.status === "error" ? "#9f1d35" : "#165dff",
  });
}
