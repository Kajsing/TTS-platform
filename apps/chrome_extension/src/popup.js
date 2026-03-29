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
const originSnippet = document.querySelector("#origin-snippet");
const voiceHint = document.querySelector("#voice-hint");

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
  statusText.textContent = JSON.stringify(state, null, 2);
}

async function refreshServiceSnapshot(configuredVoice = fields.voice.value) {
  const snapshot = await sendMessage({ type: "tts-extension:get-service-snapshot" });
  serviceStatus.textContent = JSON.stringify(
    {
      reachable: snapshot.reachable,
      message: snapshot.message,
      healthStatus: snapshot.health?.status ?? null,
      defaultVoice: snapshot.defaultVoice || null,
      voicesDiscovered: snapshot.voices.length,
      authEnabled: snapshot.authEnabled,
      checks: snapshot.health?.checks ?? null,
    },
    null,
    2
  );
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
});

document.querySelector("#refresh-service").addEventListener("click", async () => {
  await refreshServiceSnapshot();
  await refreshState();
});

document.querySelector("#speak-selection").addEventListener("click", async () => {
  const result = await sendMessage({ type: "tts-extension:speak-selection" });
  statusText.textContent = JSON.stringify(result, null, 2);
});

document.querySelector("#speak-page").addEventListener("click", async () => {
  const result = await sendMessage({ type: "tts-extension:speak-page" });
  statusText.textContent = JSON.stringify(result, null, 2);
});

document.querySelector("#stop-playback").addEventListener("click", async () => {
  const result = await sendMessage({ type: "tts-extension:stop" });
  statusText.textContent = JSON.stringify(result, null, 2);
});

setInterval(() => {
  refreshState().catch(() => undefined);
}, 1000);

loadPopup().catch((error) => {
  statusText.textContent = error.message;
  serviceStatus.textContent = error.message;
});

function sendMessage(message) {
  return chrome.runtime.sendMessage(message);
}
