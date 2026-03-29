let audioContext = null;
let websocket = null;
let queuedChunks = [];
let activeSources = new Set();
let scheduledUntilTime = 0;
let latestMark = null;
let completeWhenDrained = null;

let playbackState = {
  status: "idle",
  message: "Ready",
  activeStreamId: null,
  sampleRateHz: 24000,
  channels: 1,
  bufferedMs: 0,
  underrunCount: 0,
  lastEvent: null,
};

chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
  (async () => {
    if (message?.type === "tts-extension:start-stream") {
      await startStream(message.payload);
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "tts-extension:stop-stream") {
      await stopStream({ notifyServer: true });
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "tts-extension:get-playback-state") {
      sendResponse(snapshotState());
      return;
    }

    sendResponse({ ok: false, message: "Unknown offscreen message." });
  })().catch(async (error) => {
    await setState({
      status: "error",
      message: error.message,
      lastEvent: "error",
    });
    sendResponse({ ok: false, message: error.message });
  });

  return true;
});

async function startStream(config) {
  await stopStream({ notifyServer: false });

  if (!config?.text?.trim()) {
    throw new Error("No text was provided for playback.");
  }
  if (!config.token) {
    throw new Error("No token configured for extension playback.");
  }

  await ensureAudioContext();
  queuedChunks = [];
  activeSources = new Set();
  scheduledUntilTime = audioContext.currentTime;
  latestMark = null;
  completeWhenDrained = null;

  await setState({
    status: "connecting",
    message: "Connecting to local service",
    activeStreamId: null,
    bufferedMs: 0,
    underrunCount: 0,
    lastEvent: "connect",
    prebufferMs: config.prebufferMs,
    lowWatermarkMs: config.lowWatermarkMs,
    highWatermarkMs: config.highWatermarkMs,
  });

  const wsUrl = toWsUrl(config.baseUrl) + "/v1/tts/stream";
  websocket = new WebSocket(wsUrl);
  websocket.binaryType = "arraybuffer";

  websocket.onopen = async () => {
    websocket.send(
      JSON.stringify({
        type: "start",
        auth_token: config.token,
        payload: {
          text: config.text,
          voice: config.voice || undefined,
        },
      })
    );
  };

  websocket.onmessage = async (event) => {
    if (typeof event.data === "string") {
      await handleJsonEvent(JSON.parse(event.data), config);
      return;
    }

    await handleBinaryChunk(event.data, config);
  };

  websocket.onerror = async () => {
    await setState({
      status: "error",
      message: "WebSocket playback error",
      lastEvent: "ws-error",
    });
  };

  websocket.onclose = async () => {
    if (playbackState.status === "streaming" || playbackState.status === "connecting") {
      completeWhenDrained = "done";
      finalizeIfDrained();
    }
  };
}

async function handleJsonEvent(event, config) {
  if (event.type === "started") {
    await setState({
      status: "streaming",
      message: "Streaming audio",
      activeStreamId: event.job_id,
      sampleRateHz: event.sample_rate_hz,
      channels: event.channels,
      lastEvent: "started",
    });
    return;
  }

  if (event.type === "mark") {
    latestMark = event;
    await setState({
      lastEvent: "mark",
      bufferedMs: estimateBufferedMs(),
    });
    return;
  }

  if (event.type === "done") {
    completeWhenDrained = "done";
    await setState({
      status: "draining",
      message: "Finishing queued audio",
      lastEvent: "done",
    });
    finalizeIfDrained();
    return;
  }

  if (event.type === "cancelled") {
    completeWhenDrained = "cancelled";
    await setState({
      status: "cancelled",
      message: "Playback cancelled",
      lastEvent: "cancelled",
    });
    await stopAudioSources();
    return;
  }

  if (event.type === "error") {
    const message = event.error?.message || "Streaming error";
    await setState({
      status: "error",
      message,
      lastEvent: "error",
    });
    await stopAudioSources();
  }
}

async function handleBinaryChunk(arrayBuffer, config) {
  const int16 = new Int16Array(arrayBuffer);
  const float32 = pcm16ToFloat32(int16);
  const durationMs =
    latestMark?.duration_ms ??
    Math.max(
      1,
      Math.round((float32.length / playbackState.sampleRateHz) * 1000)
    );

  queuedChunks.push({
    float32,
    durationMs,
  });

  const bufferedMs = estimateBufferedMs();
  if (
    playbackState.status === "streaming" &&
    bufferedMs < config.lowWatermarkMs
  ) {
    playbackState.underrunCount += 1;
  }

  await setState({
    bufferedMs,
    lastEvent: "audio-frame",
  });
  flushQueue(config);
}

function flushQueue(config) {
  if (!audioContext) {
    return;
  }

  if (scheduledUntilTime < audioContext.currentTime) {
    scheduledUntilTime = audioContext.currentTime;
  }

  if (
    queuedChunks.length &&
    estimateBufferedMs() >= config.prebufferMs &&
    scheduledUntilTime === audioContext.currentTime
  ) {
    scheduledUntilTime = audioContext.currentTime + 0.05;
  }

  while (queuedChunks.length && scheduledUntilTime > audioContext.currentTime) {
    const chunk = queuedChunks.shift();
    const buffer = audioContext.createBuffer(
      playbackState.channels,
      chunk.float32.length,
      playbackState.sampleRateHz
    );
    buffer.copyToChannel(chunk.float32, 0);

    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    source.start(scheduledUntilTime);
    scheduledUntilTime += buffer.duration;
    activeSources.add(source);
    source.onended = () => {
      activeSources.delete(source);
      finalizeIfDrained();
    };
  }
}

function finalizeIfDrained() {
  if (!completeWhenDrained) {
    return;
  }
  if (queuedChunks.length > 0 || activeSources.size > 0) {
    return;
  }
  const finalStatus = completeWhenDrained;
  completeWhenDrained = null;
  setState({
    status: finalStatus,
    message: finalStatus === "done" ? "Playback finished" : "Playback cancelled",
    activeStreamId: null,
    bufferedMs: 0,
    lastEvent: finalStatus,
  });
}

async function stopStream({ notifyServer }) {
  completeWhenDrained = null;
  queuedChunks = [];
  latestMark = null;
  if (notifyServer && websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send(JSON.stringify({ type: "cancel" }));
  }
  if (websocket) {
    websocket.close();
    websocket = null;
  }
  scheduledUntilTime = audioContext ? audioContext.currentTime : 0;
  await stopAudioSources();
  await setState({
    status: "idle",
    message: "Ready",
    activeStreamId: null,
    bufferedMs: 0,
    lastEvent: "stop",
  });
}

async function stopAudioSources() {
  for (const source of activeSources) {
    try {
      source.stop();
    } catch (error) {
      void error;
    }
  }
  activeSources.clear();
}

async function ensureAudioContext() {
  if (!audioContext) {
    audioContext = new AudioContext({
      latencyHint: "interactive",
    });
  }
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }
}

function estimateBufferedMs() {
  const queuedDurationMs = queuedChunks.reduce(
    (total, chunk) => total + chunk.durationMs,
    0
  );
  const scheduledMs = audioContext
    ? Math.max(0, (scheduledUntilTime - audioContext.currentTime) * 1000)
    : 0;
  return Math.round(queuedDurationMs + scheduledMs);
}

function pcm16ToFloat32(samples) {
  const float32 = new Float32Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    float32[index] = Math.max(-1, Math.min(1, samples[index] / 32768));
  }
  return float32;
}

function toWsUrl(baseUrl) {
  if (baseUrl.startsWith("https://")) {
    return "wss://" + baseUrl.slice("https://".length);
  }
  if (baseUrl.startsWith("http://")) {
    return "ws://" + baseUrl.slice("http://".length);
  }
  return baseUrl;
}

async function setState(partialState) {
  playbackState = {
    ...playbackState,
    ...partialState,
  };
  await chrome.runtime.sendMessage({
    type: "tts-extension:playback-state",
    state: snapshotState(),
  });
}

function snapshotState() {
  return {
    ...playbackState,
    bufferedMs: estimateBufferedMs(),
  };
}
