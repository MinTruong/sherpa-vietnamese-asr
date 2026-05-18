const SHERPA_BASE = "/vendor/sherpa-onnx-wasm/";

let runtimeResolve = null;
let runtimeReject = null;
const recognizers = new Map();

const runtimeReady = new Promise((resolve, reject) => {
  runtimeResolve = resolve;
  runtimeReject = reject;
});

function post(type, payload = {}) {
  self.postMessage({ type, ...payload });
}

function reportError(id, error) {
  post("error", {
    id,
    message: error?.message || String(error),
    stack: error?.stack || "",
  });
}

var Module = {
  locateFile(path) {
    return `${SHERPA_BASE}${path}`;
  },
  mainScriptUrlOrBlob: `${SHERPA_BASE}sherpa-onnx-wasm-main-vad-asr.js`,
  getPreloadedPackage() {
    return new ArrayBuffer(0);
  },
  setStatus(status) {
    if (status) post("status", { status });
  },
  print(message) {
    post("log", { message: String(message) });
  },
  printErr(message) {
    post("log", { message: String(message) });
  },
  onRuntimeInitialized() {
    post("runtime-ready");
    runtimeResolve(Module);
  },
};
self.Module = Module;

try {
  importScripts(
    `${SHERPA_BASE}sherpa-onnx-asr.js`,
    `${SHERPA_BASE}sherpa-onnx-wasm-main-vad-asr.js`
  );
} catch (error) {
  runtimeReject(error);
  reportError(null, error);
}

function safeName(value) {
  return String(value || "model").replace(/[^a-zA-Z0-9_.-]/g, "_");
}

function unlinkIfExists(path) {
  try {
    Module.FS_unlink(path);
  } catch (_) {
    // Missing file is fine.
  }
}

function mountFile(name, buffer) {
  const path = `/${name}`;
  unlinkIfExists(path);
  Module.FS_createDataFile("/", name, new Uint8Array(buffer), true, true, true);
  return path;
}

function mountTextFile(name, text) {
  const path = `/${name}`;
  unlinkIfExists(path);
  const data = new TextEncoder().encode(String(text || ""));
  Module.FS_createDataFile("/", name, data, true, true, true);
  return path;
}

async function initRecognizer(files, options = {}) {
  await runtimeReady;
  const modelId = options.modelId || "unknown";
  if (recognizers.has(modelId)) {
    return;
  }

  const prefix = safeName(modelId);
  const encoderPath = mountFile(`${prefix}.encoder.onnx`, files.encoder);
  const decoderPath = mountFile(`${prefix}.decoder.onnx`, files.decoder);
  const joinerPath = mountFile(`${prefix}.joiner.onnx`, files.joiner);
  const tokensPath = mountFile(`${prefix}.tokens.txt`, files.tokens);
  const hotwordsText = String(options.hotwordsText || "").trim();
  const hotwordsPath = hotwordsText
    ? mountTextFile(`${prefix}.hotwords.txt`, `${hotwordsText}\n`)
    : "";

  const recognizerConfig = {
    featConfig: {
      sampleRate: 16000,
      featureDim: 80,
    },
    modelConfig: {
      transducer: {
        encoder: encoderPath,
        decoder: decoderPath,
        joiner: joinerPath,
      },
      tokens: tokensPath,
      numThreads: Math.max(1, Math.min(8, options.numThreads || 1)),
      provider: "cpu",
      debug: 0,
      modelType: "transducer",
    },
    decodingMethod: options.decodingMethod || "modified_beam_search",
    maxActivePaths: Math.max(1, Math.min(16, options.maxActivePaths || 8)),
    hotwordsFile: hotwordsPath,
    hotwordsScore: Math.max(0, Math.min(8, Number(options.hotwordsScore) || 1.5)),
    blankPenalty: 0,
  };

  const recognizer = new OfflineRecognizer(recognizerConfig, Module);
  recognizers.set(modelId, { recognizer, recognizerConfig });
  const hotwordCount = hotwordsText ? hotwordsText.split(/\r?\n/).filter(Boolean).length : 0;
  post("log", {
    message: `Initialized ${options.modelLabel || modelId}${hotwordCount ? ` with ${hotwordCount} hotwords` : ""}.`,
  });
}

function decode(samples, modelId) {
  let entry = null;
  if (modelId) {
    entry = recognizers.get(modelId);
  } else if (recognizers.size === 1) {
    entry = recognizers.values().next().value;
  }
  if (!entry?.recognizer) {
    throw new Error(`ASR recognizer is not initialized${modelId ? ` for ${modelId}` : ""}.`);
  }
  const stream = entry.recognizer.createStream();
  try {
    stream.acceptWaveform(16000, samples);
    entry.recognizer.decode(stream);
    return entry.recognizer.getResult(stream);
  } finally {
    stream.free();
  }
}

self.onmessage = async (event) => {
  const { id, type } = event.data || {};
  try {
    if (type === "init") {
      await initRecognizer(event.data.files, {
        modelId: event.data.modelId,
        modelLabel: event.data.modelLabel,
        numThreads: event.data.numThreads,
        decodingMethod: event.data.decodingMethod,
        maxActivePaths: event.data.maxActivePaths,
        hotwordsText: event.data.hotwordsText,
        hotwordsScore: event.data.hotwordsScore,
      });
      post("ready", { id });
      return;
    }

    if (type === "decode") {
      const result = decode(event.data.samples, event.data.modelId);
      post("decoded", { id, result });
      return;
    }

    throw new Error(`Unknown ASR worker message: ${type}`);
  } catch (error) {
    reportError(id, error);
  }
};
