let audioContext = null;
let websocket = null;
let queuedChunks = [];
let queuedAudioBytes = 0;
let activeSources = new Set();
let scheduledUntilTime = 0;
let latestMark = null;
let completeWhenDrained = null;
let needsPrebuffer = true;

const MAX_QUEUED_AUDIO_BYTES = 64 * 1024 * 1024;
const MAX_QUEUED_AUDIO_CHUNKS = 4096;
const MAX_QUEUED_AUDIO_MS = 10 * 60 * 1000;

let playbackState = {
  status: "idle",
  message: "Ready",
  activeStreamId: null,
  sampleRateHz: 24000,
  channels: 1,
  bufferedMs: 0,
  underrunCount: 0,
  readerProgress: null,
  lastEvent: null,
  audioContextState: null,
};

chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
  if (!isOffscreenMessage(message)) {
    return false;
  }

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

function isOffscreenMessage(message) {
  return new Set([
    "tts-extension:start-stream",
    "tts-extension:stop-stream",
    "tts-extension:get-playback-state",
  ]).has(message?.type);
}

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
  queuedAudioBytes = 0;
  activeSources = new Set();
  scheduledUntilTime = audioContext.currentTime;
  latestMark = null;
  completeWhenDrained = null;
  needsPrebuffer = true;

  await setState({
    status: "connecting",
    message: "Connecting to local service",
    activeStreamId: null,
    bufferedMs: 0,
    underrunCount: 0,
    readerProgress: null,
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
        start_text_chunk_index: config.startTextChunkIndex || undefined,
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

  websocket.onclose = async (event) => {
    websocket = null;
    if (completeWhenDrained || ["done", "cancelled", "error", "stop"].includes(playbackState.lastEvent)) {
      finalizeIfDrained();
      return;
    }

    if (isActivePlaybackStatus(playbackState.status)) {
      completeWhenDrained = event.wasClean ? "done" : "interrupted";
      if (completeWhenDrained === "interrupted") {
        await setState({
          status: "interrupted",
          message: "Stream connection closed unexpectedly",
          lastEvent: "interrupted",
        });
      }
      finalizeIfDrained();
    }
  };
}

async function handleJsonEvent(event, config) {
  if (event.type === "started") {
    await setState({
      status: "buffering",
      message: "Buffering audio",
      activeStreamId: event.job_id,
      sampleRateHz: event.sample_rate_hz,
      channels: event.channels,
      readerProgress: event.progress || null,
      lastEvent: "started",
    });
    return;
  }

  if (event.type === "mark") {
    latestMark = event;
    await setState({
      lastEvent: "mark",
      bufferedMs: estimateBufferedMs(),
      readerProgress: event.progress || playbackState.readerProgress,
    });
    return;
  }

  if (event.type === "done") {
    completeWhenDrained = "done";
    needsPrebuffer = false;
    await setState({
      status: "draining",
      message: "Finishing queued audio",
      lastEvent: "done",
      readerProgress: event.progress || playbackState.readerProgress,
    });
    await flushQueue(config);
    finalizeIfDrained();
    return;
  }

  if (event.type === "cancelled") {
    completeWhenDrained = "cancelled";
    await setState({
      status: "cancelled",
      message: "Playback cancelled",
      lastEvent: "cancelled",
      readerProgress: event.progress || playbackState.readerProgress,
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
  if (!canQueueAudioChunk(float32, durationMs)) {
    await failPlaybackBufferLimit();
    return;
  }

  queuedChunks.push({
    float32,
    durationMs,
  });
  queuedAudioBytes += float32.byteLength;

  const bufferedMs = estimateBufferedMs();
  await setState({
    bufferedMs,
    lastEvent: "audio-frame",
  });
  await flushQueue(config);
}

async function flushQueue(config) {
  if (!audioContext) {
    return;
  }

  if (scheduledUntilTime < audioContext.currentTime) {
    scheduledUntilTime = audioContext.currentTime;
  }

  const bufferedMs = estimateBufferedMs();
  if (needsPrebuffer) {
    if (bufferedMs < config.prebufferMs) {
      if (playbackState.status !== "buffering" && !completeWhenDrained) {
        await setState({
          status: "buffering",
          message: "Buffering audio",
          bufferedMs,
          lastEvent: "buffering",
        });
      }
      return;
    }

    needsPrebuffer = false;
    scheduledUntilTime = Math.max(scheduledUntilTime, audioContext.currentTime + 0.05);
    if (!completeWhenDrained) {
      await setState({
        status: "streaming",
        message: "Streaming audio",
        bufferedMs,
        lastEvent: "buffer-ready",
      });
    }
  }

  while (queuedChunks.length && estimateScheduledMs() < config.highWatermarkMs) {
    if (scheduledUntilTime < audioContext.currentTime) {
      scheduledUntilTime = audioContext.currentTime;
    }
    const chunk = queuedChunks.shift();
    queuedAudioBytes = Math.max(0, queuedAudioBytes - chunk.float32.byteLength);
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
      if (
        !completeWhenDrained &&
        websocket &&
        websocket.readyState === WebSocket.OPEN &&
        estimateBufferedMs() <= 0
      ) {
        needsPrebuffer = true;
        playbackState.underrunCount += 1;
        void setState({
          status: "buffering",
          message: "Rebuffering after underrun",
          bufferedMs: 0,
          lastEvent: "underrun",
        });
      }
      void flushQueue(config);
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
    message: finalStatusMessage(finalStatus),
    activeStreamId: null,
    bufferedMs: 0,
    lastEvent: finalStatus,
  });
}

async function stopStream({ notifyServer }) {
  completeWhenDrained = null;
  queuedChunks = [];
  queuedAudioBytes = 0;
  latestMark = null;
  needsPrebuffer = true;
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
    readerProgress: playbackState.readerProgress,
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

function canQueueAudioChunk(float32, durationMs) {
  if (queuedChunks.length >= MAX_QUEUED_AUDIO_CHUNKS) {
    return false;
  }
  if (queuedAudioBytes + float32.byteLength > MAX_QUEUED_AUDIO_BYTES) {
    return false;
  }
  if (estimateQueuedMs() + durationMs > MAX_QUEUED_AUDIO_MS) {
    return false;
  }
  return true;
}

async function failPlaybackBufferLimit() {
  completeWhenDrained = null;
  queuedChunks = [];
  queuedAudioBytes = 0;
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send(JSON.stringify({ type: "cancel" }));
    websocket.close();
  }
  websocket = null;
  await stopAudioSources();
  await setState({
    status: "error",
    message: "Playback buffer exceeded safety limit",
    activeStreamId: null,
    bufferedMs: 0,
    lastEvent: "buffer-limit",
  });
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
  return Math.round(estimateQueuedMs() + estimateScheduledMs());
}

function estimateQueuedMs() {
  return queuedChunks.reduce((total, chunk) => total + chunk.durationMs, 0);
}

function estimateScheduledMs() {
  if (!audioContext) {
    return 0;
  }
  return Math.max(
    0,
    Math.round((scheduledUntilTime - audioContext.currentTime) * 1000)
  );
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
    audioContextState: audioContext?.state ?? null,
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

function isActivePlaybackStatus(status) {
  return new Set(["connecting", "buffering", "streaming", "draining"]).has(status);
}

function finalStatusMessage(status) {
  if (status === "done") {
    return "Playback finished";
  }
  if (status === "cancelled") {
    return "Playback cancelled";
  }
  if (status === "interrupted") {
    return "Playback interrupted";
  }
  return "Playback stopped";
}
