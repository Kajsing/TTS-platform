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
const originSnippet = document.querySelector("#origin-snippet");
const voiceHint = document.querySelector("#voice-hint");
const actionMessage = document.querySelector("#action-message");

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
}

async function refreshServiceSnapshot(configuredVoice = fields.voice.value) {
  const snapshot = await sendMessage({ type: "tts-extension:get-service-snapshot" });
  serviceStatus.textContent = formatServiceSnapshot(snapshot);
  onboardingStatus.textContent = formatOnboardingStatus(snapshot);
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
  voiceHint.textContent = voices.length
    ? `Discovered ${voices.length} voice(s) from the local service.`
    : "No voices were discovered yet. Check the base URL and local service startup.";
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

function formatPlaybackState(state) {
  const lines = [
    `Status: ${state.status}`,
    `Message: ${state.message}`,
    state.source ? `Source: ${state.source}` : null,
    state.activeStreamId ? `Stream: ${state.activeStreamId}` : null,
    state.readerProgress ? `Progress: ${formatReaderProgress(state.readerProgress)}` : null,
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

function formatServiceSnapshot(snapshot) {
  const checks = snapshot.health?.checks ?? {};
  const lines = [
    `Reachable: ${snapshot.reachable}`,
    `Message: ${snapshot.message}`,
    `Health: ${snapshot.health?.status ?? "unavailable"}`,
    `Default Voice: ${snapshot.defaultVoice || "none"}`,
    `Voices Discovered: ${snapshot.voices.length}`,
    `Auth Enabled: ${snapshot.authEnabled}`,
    Object.keys(checks).length ? `Checks: ${JSON.stringify(checks)}` : null,
  ];
  return lines.filter(Boolean).join("\n");
}

function formatOnboardingStatus(snapshot) {
  const checklist = [
    checklistLine("Service reachable", snapshot.reachable, snapshot.message),
    checklistLine("Token saved", Boolean(fields.token.value.trim()), "Paste config/token.txt"),
    checklistLine(
      "Origin snippet ready",
      Boolean(snapshot.originConfigSnippet),
      snapshot.extensionOrigin
    ),
    checklistLine(
      "Voice available",
      snapshot.voices.length > 0,
      `${snapshot.voices.length} voice(s) discovered`
    ),
    checklistLine(
      "Health ok",
      snapshot.health?.status === "ok",
      snapshot.health?.status ?? "unavailable"
    ),
  ];
  return checklist.join("\n");
}

function checklistLine(label, ok, detail) {
  const marker = ok ? "[ok]" : "[todo]";
  return `${marker} ${label}: ${detail || "pending"}`;
}
