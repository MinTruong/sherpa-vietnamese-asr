import { FFmpeg } from "/vendor/ffmpeg/ffmpeg/classes.js";

const CORE_URL = "/vendor/ffmpeg/core/ffmpeg-core.js";
const WASM_URL = "/vendor/ffmpeg/core/ffmpeg-core.wasm";
const TARGET_RATE = 16000;
const DEFAULT_DECODE_TIMEOUT_MS = 180000;

let ffmpeg = null;
let ffmpegLoadPromise = null;
let lastLogLines = [];

function post(type, payload = {}, transfer = []) {
  self.postMessage({ type, ...payload }, transfer);
}

function errorMessage(error) {
  return error?.message || String(error);
}

function sanitizeName(name) {
  const clean = String(name || "input")
    .replace(/\\/g, "/")
    .split("/")
    .pop()
    .replace(/[^a-zA-Z0-9_.-]/g, "_");
  return clean || "input";
}

async function ensureFfmpeg() {
  if (ffmpegLoadPromise) return ffmpegLoadPromise;
  ffmpeg = new FFmpeg();
  ffmpeg.on("log", ({ type, message }) => {
    const line = `${type || "ffmpeg"}: ${message || ""}`.trim();
    if (line) {
      lastLogLines.push(line);
      if (lastLogLines.length > 60) lastLogLines = lastLogLines.slice(-60);
    }
  });
  ffmpeg.on("progress", ({ progress }) => {
    if (Number.isFinite(progress)) {
      post("progress", { progress: Math.max(0, Math.min(1, progress)) });
    }
  });
  ffmpegLoadPromise = ffmpeg.load({ coreURL: CORE_URL, wasmURL: WASM_URL });
  await ffmpegLoadPromise;
  post("log", { message: "FFmpeg WASM decoder loaded." });
  return ffmpegLoadPromise;
}

async function cleanup(paths) {
  for (const path of paths) {
    try {
      await ffmpeg.deleteFile(path);
    } catch (_) {
      // Best effort cleanup in MEMFS.
    }
  }
}

async function probeAudio(inputPath) {
  const probePath = "probe.json";
  try {
    const ret = await ffmpeg.ffprobe([
      "-v", "error",
      "-select_streams", "a:0",
      "-show_entries", "stream=sample_rate,channels,duration",
      "-of", "json",
      inputPath,
      "-o", probePath,
    ]);
    if (ret !== 0) return null;
    const data = await ffmpeg.readFile(probePath, "utf8");
    return JSON.parse(data);
  } catch (_) {
    return null;
  } finally {
    await cleanup([probePath]);
  }
}

function summarizeProbe(probe) {
  const stream = probe?.streams?.[0] || {};
  const sampleRate = Number.parseInt(stream.sample_rate, 10);
  const channels = Number.parseInt(stream.channels, 10);
  const duration = Number.parseFloat(stream.duration);
  return {
    sampleRate: Number.isFinite(sampleRate) ? sampleRate : null,
    channels: Number.isFinite(channels) ? channels : null,
    duration: Number.isFinite(duration) ? duration : null,
  };
}

function readFloat32Array(raw) {
  const buffer = raw.byteOffset === 0 && raw.byteLength === raw.buffer.byteLength
    ? raw.buffer
    : raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
  if (buffer.byteLength % 4 !== 0) {
    throw new Error(`FFmpeg returned invalid f32 byte count: ${buffer.byteLength}`);
  }
  return new Float32Array(buffer);
}

function monoResampleTo16k(samples, sourceRate, channels) {
  const srcRate = Number.isFinite(sourceRate) && sourceRate > 0 ? sourceRate : TARGET_RATE;
  const srcChannels = Number.isFinite(channels) && channels > 0 ? Math.floor(channels) : 1;
  const frames = Math.floor((samples?.length || 0) / srcChannels);
  const mono = new Float32Array(frames);
  if (srcChannels === 1) {
    mono.set(samples.subarray(0, frames));
  } else {
    for (let frame = 0; frame < frames; frame += 1) {
      let sum = 0;
      const offset = frame * srcChannels;
      for (let ch = 0; ch < srcChannels; ch += 1) sum += samples[offset + ch] || 0;
      mono[frame] = sum / srcChannels;
    }
  }

  if (srcRate === TARGET_RATE) return mono;
  const outLength = Math.max(1, Math.round(mono.length * TARGET_RATE / srcRate));
  const out = new Float32Array(outLength);
  const ratio = srcRate / TARGET_RATE;
  for (let i = 0; i < outLength; i += 1) {
    const pos = i * ratio;
    const left = Math.min(mono.length - 1, Math.floor(pos));
    const right = Math.min(mono.length - 1, left + 1);
    const frac = pos - left;
    out[i] = mono[left] * (1 - frac) + mono[right] * frac;
  }
  return out;
}

async function runDecodeAttempt(args, outputPath, timeoutMs = DEFAULT_DECODE_TIMEOUT_MS) {
  lastLogLines = [];
  const ret = await ffmpeg.exec(args, timeoutMs);
  if (ret !== 0) {
    const detail = lastLogLines.slice(-10).join("\n");
    const timeoutNote = ret === 1 ? ` after ${Math.round(timeoutMs / 1000)}s` : "";
    throw new Error(`ffmpeg decode failed with code ${ret}${timeoutNote}${detail ? `\n${detail}` : ""}`);
  }
  return ffmpeg.readFile(outputPath);
}

async function decodeWithFfmpeg({ fileName, bytes, timeoutMs }) {
  await ensureFfmpeg();
  lastLogLines = [];

  const inputPath = sanitizeName(fileName);
  const outputPath = "output.f32";
  const rawOutputPath = "output.raw.f32";
  await ffmpeg.writeFile(inputPath, new Uint8Array(bytes));
  try {
    const primaryArgs = [
      "-y",
      "-hide_banner",
      "-nostdin",
      "-loglevel", "error",
      "-i", inputPath,
      "-map", "0:a:0",
      "-vn",
      "-ac", "1",
      "-ar", String(TARGET_RATE),
      "-f", "f32le",
      "-acodec", "pcm_f32le",
      outputPath,
    ];
    const raw = await runDecodeAttempt(primaryArgs, outputPath, timeoutMs);
    const out = readFloat32Array(raw);
    const buffer = out.byteOffset === 0 && out.byteLength === out.buffer.byteLength
      ? out.buffer
      : out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);

    return {
      pcmBuffer: buffer,
      sampleRate: TARGET_RATE,
      originalSampleRate: null,
      channels: 1,
      duration: out.length / TARGET_RATE,
      decoder: "ffmpeg-wasm-default",
      resampler: "ffmpeg-default",
    };
  } catch (primaryError) {
    throw primaryError;
  } finally {
    await cleanup([inputPath, outputPath, rawOutputPath]);
  }
}

async function extractWithFfmpeg({ fileName, bytes, outputFormat, timeoutMs }) {
  await ensureFfmpeg();
  lastLogLines = [];

  const inputPath = sanitizeName(fileName);
  const format = outputFormat === "aac" ? "aac" : "mp3";
  const outputPath = `extracted.${format}`;
  await ffmpeg.writeFile(inputPath, new Uint8Array(bytes));

  const formatArgs = format === "aac"
    ? ["-c:a", "copy", "-f", "adts"]
    : ["-c:a", "copy", "-f", "mp3"];
  try {
    const args = [
      "-y",
      "-hide_banner",
      "-nostdin",
      "-loglevel", "error",
      "-i", inputPath,
      "-map", "0:a:0",
      "-vn",
      ...formatArgs,
      outputPath,
    ];
    const raw = await runDecodeAttempt(args, outputPath, timeoutMs);
    const buffer = raw.byteOffset === 0 && raw.byteLength === raw.buffer.byteLength
      ? raw.buffer
      : raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
    return { audioBuffer: buffer, outputFormat: format };
  } finally {
    await cleanup([inputPath, outputPath]);
  }
}

self.onmessage = async (event) => {
  const { id, type } = event.data || {};
  try {
    if (type === "decode") {
      const result = await decodeWithFfmpeg(event.data);
      post("decoded", { id, ...result }, [result.pcmBuffer]);
      return;
    }
    if (type === "extract") {
      const result = await extractWithFfmpeg(event.data);
      post("extracted", { id, ...result }, [result.audioBuffer]);
      return;
    }
    throw new Error(`Unknown FFmpeg decoder message: ${type}`);
  } catch (error) {
    post("error", {
      id,
      message: errorMessage(error),
      stack: error?.stack || "",
    });
  }
};
