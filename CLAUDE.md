# CLAUDE.md — Sherpa Vietnamese ASR

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ứng dụng nhận dạng giọng nói tiếng Việt offline, chạy CPU trên Windows. Hai bản phân phối:
- **Desktop App** (`app.py`) — PyQt6 GUI, 1 user
- **Web Service** (`server_launcher.py`) — FastAPI + PWA, multi-user

## Key Commands

```bash
# === Run development ===
python app.py                                      # Desktop (PyQt6 GUI)
python server_launcher.py --no-gui                 # Web headless (FastAPI)
python server_launcher.py                          # Web admin GUI wrapper
python server_gui.py                               # Web admin GUI (standalone PyQt6)

# === CLI (created tool — run ASR from command line) ===
python asr_cli.py input.mp3 --text-only            # Basic transcript
python asr_cli.py input.mp3 --rover --text-only    # ROVER (2 models, best accuracy)
python asr_cli.py input.mp3 --model 30M --no-diarization -v  # Lightweight + verbose

# === Build portable (output: dist/) ===
python build-portable/setup_build_env.py           # Step 1: setup virtualenv
python build-portable/prepare_offline_build.py     # Step 2: download models
python build-portable/build_portable.py            # Desktop build (~1.2 GB)
python build-portable/build_portable_online.py     # Web service build (~1.7 GB)
python build-portable/build_gpu_addons.py directml intel-openvino  # GPU add-ons
python build-portable/build_gpu_models.py          # GPU-specific models

# === Versioning (SemVer from git tags) ===
git tag v2.6.3 -m "Description"                   # Release → build ra "2.6.3"
# Không tag → build ra "2.1.2+3.abc1234" (dev build, tự động)

# === Service installer (Windows Admin) ===
python service_installer.py install                # Install as Windows service
python service_installer.py remove                 # Remove Windows service
python service_installer.py start                  # Start service

# === Install missing deps (common gotchas) ===
pip install onnxruntime                            # Required for inference
pip install kaldi-native-fbank                     # Required by sherpa-onnx for fbank extraction
pip install websockets                             # Required by uvicorn WebSocket
pip install cryptography                           # Required for SSL cert generation

# === Sync to GitHub repo ===
# Copy code từ d:\App\asr-vn → D:\App\sherpa-vietnamese-asr rồi push
```

**Note:** There are no formal test suites in this project. Test/benchmark/experiment files go in `temp/` and are never committed. Audio datasets live in `dataset/raw_audio/`.

## Processing Pipeline

Audio flows through these stages serially — every stage runs via ONNX Runtime (no PyTorch at inference):

```text
Input file (MP3/WAV/...) → FFmpeg decode (16kHz mono SoXR) → [Preprocess: RMS norm + WPE dereverb] → [Overlap Separation] → VAD (Silero ONNX) → Chunking → ASR (Zipformer RNN-T ONNX) → [ROVER voting for 3-model mode] → Diarization → Punctuation (ViBERT-capu ONNX) → [Grammar correction (GEC BERT ONNX)] → JSON output
```

Preprocessing (RMS normalization, WPE dereverberation) and grammar correction are optional steps controlled by config flags.

1. **Audio decode** (`core/audio_decode.py`) — FFmpeg + SoXR HQ/VHQ resampling → mono float32 PCM 16kHz
2. **Audio preprocessing** (`core/audio_preprocessing.py`) — Per-segment RMS normalization (adaptive, Google AGC-style), adaptive peak limiter, WPE dereverberation (per-chunk, optional)
3. **Overlap separation** (`core/overlap_separator.py`) — Conv-TasNet ONNX tách 2 người nói chồng lấn
4. **VAD** (`core/vad_utils.py`) — Silero VAD ONNX (chung cho cả desktop ASR và audio_analyzer)
5. **ASR** (`core/asr_engine.py`) — Zipformer RNN-T (30M hoặc 68M); chunk+overlap+ROVER voting
6. **Diarization** (`core/speaker_diarization_*.py`) — Pyannote Community-1 (ResNet34+PLDA+VBx) hoặc Senko CAM++ (spectral/UMAP+HDBSCAN/clustering); dispatcher pattern
7. **Punctuation** (`core/punctuation_restorer_improved.py`) — ViBERT-capu ONNX, tích hợp grammar correction (GEC BERT ONNX) option
8. **Grammar correction** (`core/gec_model.py`) — Seq2Labels ONNX model, sửa lỗi ngữ pháp sau punctuation
9. **JSON output** (`core/asr_json.py`) — segments với speaker labels, timestamps

## Architecture

### Core modules (pure Python, dùng chung desktop & web — KHÔNG import PyQt6)

| Module | Chức năng |
|--------|-----------|
| `core/config.py` | Config, model registry, hotword config, theme colors (COLORS dict, source of truth cho mọi UI) |
| `core/asr_engine.py` | ASR pipeline chính: chunk + overlap resolution + ROVER voting |
| `core/speaker_diarization.py` | Dispatcher + NaturalTurn + model registry (DEPRECATED — dùng `_pure_ort` hoặc `_senko_campp`) |
| `core/speaker_diarization_pure_ort.py` | Pyannote Community-1: ResNet34-LM embedding + PLDA scoring + VBx clustering, pure ONNX |
| `core/speaker_diarization_senko_campp.py` | Senko CAM++ 192-dim: spectral/UMAP reduction + HDBSCAN clustering |
| `core/speaker_diarization_senko_campp_optimized.py` | Senko optimized: batch inference, ~2.5x faster |
| `core/punctuation_restorer_improved.py` | ViBERT-capu ONNX: dấu câu + viết hoa (desktop INT8, web FP32), tích hợp GEC |
| `core/gec_model.py` | Seq2Labels grammar error correction ONNX (wrapper, dùng transformers tokenizer) |
| `core/gec_utils.py` | GEC utilities: verb form vocabulary, edit labels, sentence decoding |
| `core/vocabulary.py` | AllenNLP-style vocabulary with namespaces, padding, OOV handling |
| `core/audio_preprocessing.py` | RMS normalization + adaptive peak limiter + WPE dereverberation |
| `core/utils.py` | Vietnamese text normalization (remove diacritics), fuzzy search |
| `core/vad_utils.py` | Silero VAD ONNX session + prediction |
| `core/overlap_separator.py` | Conv-TasNet ONNX 2-speaker separation |
| `core/audio_decode.py` | FFmpeg/SoXR decode/resample canoncial (mono 16kHz float32) |
| `core/audio_analyzer.py` | DNSMOS quality + ASR-Proxy confidence |
| `core/hardware_accel.py` | GPU provider detection, add-on paths, ORT session factory |
| `core/calibration.py` | Device calibration (GPU benchmark per stage, 10-min sample) |
| `core/hotword_context.py` | Aho-Corasick context graph for sherpa-onnx hotword boosting |
| `core/asr_json.py` | JSON serialize/deserialize ASR results |
| `core/log_config.py` | Centralized logging (RotatingFileHandler 50MB, TeeWriter for print()) |
| `core/version.py` | Auto-version từ `git describe --tags` (SemVer) — fallback read from `VERSION` file |

### Desktop app entry points

| File | Chức năng |
|------|-----------|
| `app.py` | PyQt6 main window, tab layout |
| `tab_file.py` | File processing tab — drag-drop audio, ASR config, editor với speaker timeline |
| `tab_live.py` | Live recording tab — microphone streaming, VAD trigger, real-time ASR |
| `transcriber.py` | `QThread` wrapper quanh `core.asr_engine.TranscriberPipeline` (signal-based) |
| `streaming_asr.py` | Real-time offline ASR (`OfflineRecognizer` + VADTrigger ring buffer) |
| `streaming_asr_online.py` | Real-time online ASR (`OnlineRecognizer` + endpoint detection) |
| `common.py` | Qt widgets dùng chung: DragDropLabel, SearchWidget, SpeakerDiarizationThread, etc. |
| `splash_win32.py` | Win32 splash screen (ctypes, zero dep, luôn trên cùng khi load thư viện nặng) |
| `resource_monitor.py` | CPU/RAM/Disk monitoring cho desktop |
| `quality_result_dialog.py` | DNSMOS quality result dialog |

### Web service — architecture

```
server_launcher.py → server_gui.py (PyQt6 admin) + web_service/server.py (FastAPI)
                  ↗ PWA offline (offline_pwa/server.py, port 8444)
```

| File | Chức năng |
|------|-----------|
| `server_launcher.py` | Entry — starts FastAPI (uvicorn) và optional PyQt6 admin GUI |
| `server_gui.py` | Web admin GUI (PyQt6 wrapper) |
| `web_service/server.py` | FastAPI app: REST routes, WebSocket, JWT auth, file upload, static files |
| `web_service/config.py` | Server config reader (config.ini [ServerSettings]) |
| `web_service/queue_manager.py` | FIFO ASR queue (1 file at a time), convert-to-wav, progress |
| `web_service/database.py` | SQLite (sync): users, sessions, files, queue history |
| `web_service/auth.py` | JWT (HS256) auth, password hashing (hashlib+secrets), admin setup |
| `web_service/session_manager.py` | Session + WebSocket manager, upload artifact cleanup |
| `web_service/ssl_utils.py` | Self-signed cert generation (cryptography) |
| `web_service/audio_quality.py` | DNSMOS quality via subprocess (isolated from GUI) |
| `web_service/summarizer.py` | Ollama-based meeting summarizer |
| `web_service/summarizer_withE4B.py` | Gemma 4 E2B GGUF summarizer (llama-cpp-python) |

**Queue processing model:** Web service uses a synchronous FIFO queue — one file at a time. Processing happens in a thread (not asyncio). Progress is pushed via WebSocket to connected clients. The `/api/models` endpoint exposes available ASR + speaker models dynamically from disk, not hardcoded.

**Static files** (`web_service/static/`):
- `js/app.js` — Main UI logic
- `js/admin.js` — Admin panel
- `js/upload.js` — File upload & queue
- `js/websocket.js` — WebSocket client (real-time progress)
- `js/player.js`, `js/speaker.js`, `js/meetings.js`, `js/summary.js`, `js/search.js` — Feature modules
- `sw.js` — Service Worker for PWA offline
- `offline.html` — Offline fallback page

### Offline PWA (`offline_pwa/`)

Browser-only ASR (inference runs in browser via ONNX Runtime Web WASM/WebGPU). The server serves:
- PWA shell + service worker
- Model manifest (`model_manifest.json` — lists available ASR models with SHA256 pins, size, URLs for same-origin download)
- Same-origin model downloads (COOP/COEP isolation cho WASM threading)

**Key design constraints:** Separate from web_service — the PWA server does NOT run ASR. WebGPU used when browser supports it; fallback to WASM/CPU. Config in `config.ini [OfflinePWA]`.

### GPU acceleration system

GPU support is **add-on based** (not bundled by default):

1. **Detection** (`core/hardware_accel.py`) — Scans site-packages for ORT GPU providers (DirectML, OpenVINO, CUDA). No hard dependency — graceful CPU fallback.
2. **Calibration** (`core/calibration.py`) — Runs bundled 10-min audio sample on each stage separately with each GPU provider, compares speed vs CPU. GPU selected only if ≥20% faster AND numerical error within tolerance.
3. **Provider selection** — Stage-level (each stage can have a different provider). Configured via `config.ini` `stage_execution_providers` JSON. UI in **Tối ưu thiết bị** dialog.
4. **Add-on build** (`build-portable/build_gpu_addons.py`) — Packages ORT DirectML + OpenVINO wheels into `gpu_addons/` dir.

GPU benchmarks measure individual stage inference time only (not full pipeline wall-clock).

### Speaker diarization — three implementations

| Module | Approach | Speed | Quality | Status |
|--------|----------|-------|---------|--------|
| `core/speaker_diarization.py` | sherpa-onnx NeMo TitaNet + Pyannote seg-3-0 | — | Thấp | DEPRECATED |
| `core/speaker_diarization_pure_ort.py` | Pyannote Community-1: ResNet34-LM embedding + PLDA + VBx clustering, all ONNX | Medium | Cao | Default |
| `core/speaker_diarization_senko_campp.py` | CAM++ 192-dim + spectral/UMAP + HDBSCAN | Khởi đầu chậm | Cao | Alternative |
| `core/speaker_diarization_senko_campp_optimized.py` | Same as above but batch inference ~2.5x faster | Fast | Cao | Preferred Senko |

Dispatcher in `speaker_diarization.py` routes to correct implementation based on config.

### ASR engine — chunk + overlap + ROVER

`core/asr_engine.py`:
- Chunks audio → runs ASR per chunk sequentially (not parallel — memory constraint)
- Adjacent chunks overlap with fuzzy word-sequence alignment to cut duplicate text
- **ROVER mode**: runs all 3 models, votes on output for best accuracy (slowest)
- 3 ASR modes: Zipformer 30M (fast), Zipformer 68M (accurate), ROVER (combined)
- Sa-mple-level overlap resolution: sliding window with Levenshtein similarity ≥ 0.8
- Loads audio via soundfile (not librosa) after FFmpeg convert to reduce peak RAM

## Configuration System

Single file `config.ini` (no `.example` in repo — auto-created if missing). Sections:
- `[FileSettings]` — Desktop file processing defaults
- `[LiveSettings]` — Desktop live recording defaults  
- `[ServerSettings]` — Web service port, SSL, upload limits, auth
- `[OfflinePWA]` — PWA port, model source (bundled_server / huggingface), cache version
- `[HardwareAccel]` — Thread count, GPU add-on paths, stage-level providers

## Build System

### Build flow
1. `setup_build_env.py` — Create `.envtietkiem/` venv, install all dependencies + sherpa-onnx
2. `prepare_offline_build.py` — Download/verify all model files (SHA256 pinned)
3. `build_portable.py` — Copy venv + models, strip `.opt` files (ORT cache), zip into `dist/`
4. `build_gpu_addons.py` — Package GPU ORT wheels separately
5. `build_gpu_models.py` — Package GPU-specific ONNX models

### Build notes
- Venv name: `.envtietkiem/` (NOT `.venv`)
- Senko diarization cần: `numba`, `llvmlite`, `tqdm`, `pynndescent`, `umap-learn`, `hdbscan` — KHÔNG được exclude
- Giữ `.dist-info` cho: `pynndescent`, `umap_learn`, `hdbscan`, `numba`, `llvmlite`, `scikit_learn` (dùng `importlib.metadata`)
- Strip `.opt` files (ORT JIT cache generated on target machine)
- Models directory required: `campp-3dspeaker/`, `pyannote-onnx/` cho Senko

## Common Gotchas & Fixes

1. **Web server crashes at startup with `FOREIGN KEY constraint failed`** — `database.py:delete_session_files()` deletes `files` before `meetings`. Fix: add `DELETE FROM meetings WHERE file_id IN (SELECT id FROM files WHERE session_id = ?)` before `DELETE FROM files`.

2. **`prepare_offline_build.py` fails for `zipformer-30m-rnnt-6000h` and `zipformer-30m-rnnt-streaming-6000h`** — HuggingFace repos lack `tokens.txt`. Fix: generate from `bpe.model` using sentencepiece:
   ```python
   import sentencepiece as spm
   sp = spm.SentencePieceProcessor()
   sp.Load("models/<model>/bpe.model")
   with open("models/<model>/tokens.txt", "w") as f:
       for i in range(sp.GetPieceSize()):
           f.write(f"{sp.IdToPiece(i)} {i}\n")
   ```

3. **Pyannote gated repos** (`pyannote/speaker-diarization-community-1`, `pyannote/segmentation-3.0`) return 401 — not needed, the project uses pure ONNX alternatives (`altunenes_*`, `pyannote_split_encoder`). Skip these errors.

4. **Web server WebSocket fails** — install `websockets`: `pip install websockets`

5. **ASR pipeline can't find `kaldi_native_fbank`** — install separately: `pip install kaldi-native-fbank` (not listed in requirements.txt as a transitive dep of sherpa-onnx)

6. **SSL cert generation fails** — install `cryptography`: `pip install cryptography`

7. **ROVER mode** — use `rover_mode: True` in pipeline config. Do NOT manually loop over models — the engine internally loads multiple recognizers and combines results.

8. **Diarization default (`pyannote`) fails** — gated model is missing. Use `senko_campp_optimized` as speaker_model instead, or disable diarization.

9. **CLI tool `asr_cli.py`** — created at project root for running ASR without GUI. Supports `--model`, `--rover`, `--no-diarization`, `--text-only`, `--rms-normalize`.

## Data Flow Key Patterns

1. **Core isolation rule:** `core/` must never import PyQt6 — ensures web service runs headless. Desktop GUI code wraps core logic via `QThread` subclasses (`transcriber.py`, `common.py`).
2. **Web service threading:** ASR runs in a `threading.Thread`, not asyncio — avoids GIL contention with ONNX Runtime. Progress pushed via WebSocket (`session_manager.ws_manager`).
3. **JSON serialization:** Desktop saves/loads `.asr.json` files. Web stores file + metadata in SQLite. Both use `core/asr_json.py` for serialize/deserialize with speaker mapping, speaker colors, overlap segments.
4. **Version:** Derived from `git describe --tags`. Portable builds read `VERSION` file (written by build script). Both desktop About dialog and web `/api/version` consume `core.version.get_version()`.
5. **Model registry:** `core/config.py` defines `MODEL_DOWNLOAD_INFO` dict with model ID, URL, filename, SHA256. Not config.ini—models are bundled, not downloaded at runtime (desktop). Web /api/models scans disk dynamically. prepare_offline_build.py pins SHA256.
6. **Theme system:** `COLORS` dict in `core/config.py` is source of truth — desktop reads directly, web CSS mirrors via CSS custom properties. `apply_theme()` updates dict in-place before UI init.
7. **Thread safety for streaming ASR:** `streaming_asr.py` uses `queue.Queue` for audio transport from mic to recognizer thread. VADTrigger uses ring buffer (`collections.deque`).

## GitHub Sync Workflow

"Đồng bộ qua repo github" = copy code từ `d:\App\asr-vn` → `D:\App\sherpa-vietnamese-asr`:
1. Copy top-level .py files, README.md, LICENSE, resource_monitor.py
2. `rm -f core/*.py` rồi copy lại (full sync, xóa file cũ)
3. Copy `web_service/*.py` + `web_service/static/*`
4. Copy `build-portable/*.py`, `offline_pwa/*.py`, `convert_onnx/*.py`
5. `git add -A && git commit && git tag && git push --tags`

**Không** copy: `.envtietkiem/`, `dist/`, `temp/`, `models/`, `*.exe`, `*.dll`, `.claude/`, `logs/`

## Conventions

- Desktop target: i5-12400/8GB — prioritize RAM, `save_ram=True` by default
- Web target: 20vCPU/32GB — less constrained, summarizer uses Gemma 4 E2B
- Emoji OK trong PyQt6 UI
- Commit messages: tiếng Việt hoặc English đều OK
- All model paths are relative to `BASE_DIR/models/` (auto-detected at startup)
- Config.ini auto-generated with defaults if missing — never hard-require on first run
