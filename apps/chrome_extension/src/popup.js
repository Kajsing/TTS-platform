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

async function loadPopup() {
  const config = await sendMessage({ type: "tts-extension:get-config" });
  extensionOrigin.textContent = config.extensionOrigin;
  fields.baseUrl.value = config.baseUrl;
  fields.token.value = config.token;
  fields.voice.value = config.voice;
  fields.prebufferMs.value = config.prebufferMs;
  fields.lowWatermarkMs.value = config.lowWatermarkMs;
  fields.highWatermarkMs.value = config.highWatermarkMs;
  fields.maxChars.value = config.maxChars;
  await refreshState();
}

async function refreshState() {
  const state = await sendMessage({ type: "tts-extension:get-state" });
  statusText.textContent = JSON.stringify(state, null, 2);
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
});

function sendMessage(message) {
  return chrome.runtime.sendMessage(message);
}
