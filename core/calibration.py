"""Device calibration helpers for desktop and web server.

Calibration is opt-in: the application starts on CPU, detects whether a GPU
provider is usable, then runs the bundled 10 minute sample only when the user
confirms optimization.
"""
from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.config import ALLOWED_THREADS, BASE_DIR
from core.hardware_accel import (
    CPU_PROVIDER,
    DML_PROVIDER,
    actual_session_provider,
    auto_batch_size,
    best_gpu,
    create_ort_session,
    detect_hardware,
    gpu_vram_mb,
    hardware_summary,
    installed_gpu_addons,
    is_gpu_provider,
    ort_provider_request,
    preferred_gpu_provider,
    recommended_gpu_addon,
)


CALIBRATION_SAMPLE_MP3 = Path(BASE_DIR) / "offline_pwa" / "static" / "calibration" / "1hour_qh_10min.mp3"
CALIBRATION_SAMPLE_WAV = Path(BASE_DIR) / "temp" / "1hour_qh_10min_16k.wav"
CALIBRATION_CACHE_WAV = Path(BASE_DIR) / "temp" / "calibration_1hour_qh_10min_16k.wav"
CALIBRATION_REPORT_PATH = Path(BASE_DIR) / "temp" / "device_calibration_last.json"

GPU_STAGE_SPEEDUP_MIN = 1.20

PWA_FIXED_CPU_STAGES = [
    {
        "key": "asr",
        "label": "ASR encoder/decoder/joiner",
        "selected_provider": "cpu",
        "reason": "PWA offline giữ ASR full backend ở WASM/CPU; không benchmark GPU cho stage này.",
    },
    {
        "key": "audio_decode",
        "label": "Audio decode / resample",
        "selected_provider": "cpu",
        "reason": "FFmpeg/ffprobe là audio codec + metadata, không cần GPU cho calibration.",
    },
    {
        "key": "vad",
        "label": "Silero VAD",
        "selected_provider": "cpu",
        "reason": "PWA offline đánh dấu VAD recurrent runner là CPU/WASM-only.",
    },
    {
        "key": "speaker_postprocess",
        "label": "Speaker segmentation / VBx / clustering",
        "selected_provider": "cpu",
        "reason": "PWA offline chỉ tăng tốc embedding; clustering/segmentation giữ CPU.",
    },
]

GPU_BENCHMARK_STAGES = [
    {
        "key": "speaker_campp_embedding",
        "label": "Speaker Diarization: CAM++ embedding",
        "path": Path(BASE_DIR) / "models" / "campp-3dspeaker" / "campplus_cn_en_common_200k.onnx",
        "batch_default": 32,
        "tolerance": {"max_abs": 2e-3, "rel_l2": 2e-4},
        "pipeline_key": "diarization_campp",
    },
    {
        "key": "speaker_pyannote_embedding",
        "label": "Speaker Diarization: Pyannote embedding encoder",
        "path": Path(BASE_DIR) / "models" / "pyannote-onnx" / "embedding_encoder.onnx",
        "batch_default": 8,
        "tolerance": {"max_abs": 2e-3, "rel_l2": 2e-4},
        "pipeline_key": "diarization_pyannote",
    },
    {
        "key": "dnsmos",
        "label": "DNSMOS quality",
        "path": Path(BASE_DIR) / "models" / "dnsmos" / "sig_bak_ovr.onnx",
        "batch_default": 8,
        "tolerance": {"max_abs": 1e-3, "rel_l2": 1e-4},
        "pipeline_key": "dnsmos",
    },
    {
        "key": "punctuation",
        "label": "Punctuation: ViBERT punctuation fp32",
        "path": Path(BASE_DIR) / "models" / "vibert-capu" / "vibert-capu.onnx",
        "batch_default": 8,
        "tolerance": {"max_abs": 5e-3, "rel_l2": 5e-4},
        "pipeline_key": "punctuation",
    },
]

GPU_MODELS_ARTIFACT = "gpu-models-win64"
GPU_MODEL_FILES = [
    {
        "label": "ViBERT punctuation FP32",
        "relative_path": "models/vibert-capu/vibert-capu.onnx",
    },
]


def _version_short() -> str:
    spec = importlib.util.spec_from_file_location("_asr_vn_version", Path(BASE_DIR) / "core" / "version.py")
    if spec is None or spec.loader is None:
        return "<version>"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_version_short()


def recommended_gpu_models() -> Dict[str, Any]:
    try:
        version = _version_short()
    except Exception:
        version = "<version>"

    expected = []
    missing = []
    root = Path(BASE_DIR)
    for item in GPU_MODEL_FILES:
        rel = item["relative_path"]
        path = root / rel
        entry = {
            "label": item["label"],
            "relative_path": rel,
            "display_path": "/" + rel.replace("\\", "/"),
            "path": str(path),
            "present": path.is_file(),
        }
        expected.append(entry)
        if not entry["present"]:
            missing.append(entry)

    return {
        "artifact": GPU_MODELS_ARTIFACT,
        "zip_name": f"{GPU_MODELS_ARTIFACT}-{version}.zip",
        "label": "GPU models",
        "installed": not missing,
        "expected_paths": expected,
        "missing_paths": missing,
    }


def _safe_ram_info() -> Dict[str, Any]:
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return {
            "total_mb": int(vm.total / (1024 * 1024)),
            "available_mb": int(vm.available / (1024 * 1024)),
        }
    except Exception:
        return {}


def _emit(callback: Optional[Callable[[str, int], None]], message: str, percent: int) -> None:
    if callback:
        callback(message, max(0, min(100, int(percent))))


def _first_existing(paths: List[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def _model_specs() -> List[Dict[str, Any]]:
    root = Path(BASE_DIR)
    return [
        {
            "stage": "ASR encoder",
            "path": root / "models" / "sherpa-onnx-zipformer-vi-2025-04-20" / "encoder-epoch-12-avg-8.onnx",
            "batch_default": 16,
        },
        {
            "stage": "ASR decoder",
            "path": root / "models" / "sherpa-onnx-zipformer-vi-2025-04-20" / "decoder-epoch-12-avg-8.onnx",
            "batch_default": 16,
        },
        {
            "stage": "ASR joiner",
            "path": root / "models" / "sherpa-onnx-zipformer-vi-2025-04-20" / "joiner-epoch-12-avg-8.onnx",
            "batch_default": 16,
        },
        {
            "stage": "DNSMOS quality",
            "path": root / "models" / "dnsmos" / "sig_bak_ovr.onnx",
            "batch_default": 16,
        },
        {
            "stage": "CAM++ speaker embedding",
            "path": root / "models" / "campp-3dspeaker" / "campplus_cn_en_common_200k.onnx",
            "batch_default": 32,
        },
        {
            "stage": "ViBERT punctuation fp32",
            "path": root / "models" / "vibert-capu" / "vibert-capu.onnx",
            "batch_default": 8,
        },
        {
            "stage": "Pyannote Community-1 embedding encoder",
            "path": root / "models" / "pyannote-onnx" / "embedding_encoder.onnx",
            "batch_default": 8,
        },
    ]


def run_provider_probe(policy: str = "auto", light: bool = False) -> List[Dict[str, Any]]:
    """Create ONNX sessions and record the actual provider ORT selected."""
    try:
        from core.hardware_accel import configure_gpu_addon_paths
        configure_gpu_addon_paths()
        import onnxruntime as ort  # type: ignore
    except Exception as exc:
        return [{"stage": "onnxruntime", "error": f"{type(exc).__name__}: {exc}"}]

    specs = _model_specs()
    if light:
        specs = [s for s in specs if s["stage"] == "DNSMOS quality"] or specs[:1]

    results: List[Dict[str, Any]] = []
    for spec in specs:
        path = Path(spec["path"])
        if not path.exists():
            results.append({"stage": spec["stage"], "missing": str(path)})
            continue

        sess_options = ort.SessionOptions()
        try:
            session, info = create_ort_session(
                ort,
                str(path),
                sess_options,
                policy=policy,
                stage=spec["stage"],
            )
            actual = actual_session_provider(session)
            results.append(
                {
                    "stage": spec["stage"],
                    "requested_providers": info.get("requested_providers"),
                    "actual_provider": actual,
                    "session_providers": info.get("session_providers"),
                    "used_gpu": is_gpu_provider(actual),
                    "fallback_reason": info.get("fallback_reason"),
                    "auto_batch": auto_batch_size(spec["stage"], spec["batch_default"], actual),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "stage": spec["stage"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "requested_providers": ort_provider_request(policy, ort),
                }
            )
    return results


def detect_calibration_status() -> Dict[str, Any]:
    hw = detect_hardware()
    addon = recommended_gpu_addon()
    gpu_models = recommended_gpu_models()
    provider = preferred_gpu_provider("auto")
    light_probe = run_provider_probe("auto", light=True) if provider else []
    provider_ready = any(item.get("used_gpu") for item in light_probe)
    gpus = hw.get("gpus") or []
    gpu_models_ready = bool(gpu_models.get("installed"))

    reason = ""
    if not gpus:
        reason = "no_gpu"
    elif addon and not addon.get("installed"):
        reason = "gpu_addon_missing"
    elif not provider:
        reason = "no_supported_ort_provider"
    elif not provider_ready:
        reason = "provider_probe_failed"
    elif not gpu_models_ready:
        reason = "gpu_models_missing"

    if addon and gpus and addon.get("installed") and provider and not provider_ready:
        reason = "gpu_addon_provider_not_loaded"

    return {
        "hardware": hw,
        "ram": _safe_ram_info(),
        "hardware_summary": hardware_summary(),
        "preferred_provider": provider or CPU_PROVIDER,
        "provider_request": ort_provider_request("auto"),
        "provider_ready": provider_ready,
        "gpu_models_ready": gpu_models_ready,
        "can_optimize": bool(gpus and provider and provider_ready and gpu_models_ready),
        "reason": reason,
        "recommended_addon": addon,
        "recommended_gpu_models": gpu_models,
        "installed_addons": installed_gpu_addons(),
        "light_probe": light_probe,
        "sample_file": str(CALIBRATION_SAMPLE_MP3),
        "sample_available": CALIBRATION_SAMPLE_MP3.exists() or CALIBRATION_SAMPLE_WAV.exists(),
        "last_report": str(CALIBRATION_REPORT_PATH),
        "last_report_available": CALIBRATION_REPORT_PATH.exists(),
    }


def _nvidia_cuda_advice(stage_results: List[Dict[str, Any]]) -> Optional[str]:
    return None


def _validate_wav_16k_mono(path: Path) -> None:
    try:
        import soundfile as sf  # type: ignore

        info = sf.info(str(path))
        if info.samplerate == 16000 and info.channels == 1 and info.frames > 0:
            return
    except Exception:
        pass

    from core.audio_decode import find_ffprobe, ffmpeg_error_tail

    ffprobe = find_ffprobe()
    if not ffprobe:
        raise RuntimeError(f"cannot validate calibration WAV; ffprobe not found: {path}")
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,duration",
        "-of",
        "default=noprint_wrappers=1",
        str(path),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=creationflags)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe validation failed: {ffmpeg_error_tail(result.stderr, result.stdout)}")
    text = result.stdout.decode("utf-8", errors="replace")
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    if fields.get("sample_rate") != "16000" or fields.get("channels") != "1":
        raise RuntimeError(f"calibration WAV validation failed: {fields}")


def ensure_calibration_wav() -> Path:
    if CALIBRATION_SAMPLE_WAV.exists():
        _validate_wav_16k_mono(CALIBRATION_SAMPLE_WAV)
        return CALIBRATION_SAMPLE_WAV
    if CALIBRATION_CACHE_WAV.exists():
        try:
            _validate_wav_16k_mono(CALIBRATION_CACHE_WAV)
            return CALIBRATION_CACHE_WAV
        except Exception:
            try:
                CALIBRATION_CACHE_WAV.unlink()
            except OSError:
                pass
    if not CALIBRATION_SAMPLE_MP3.exists():
        raise FileNotFoundError(f"Calibration sample not found: {CALIBRATION_SAMPLE_MP3}")

    from core.audio_decode import (
        ffmpeg_error_tail,
        ffmpeg_resample_filter_candidates,
        find_ffmpeg,
    )

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg.exe not found in app root folder")

    CALIBRATION_CACHE_WAV.parent.mkdir(parents=True, exist_ok=True)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    last_error = ""
    for filter_expr in ffmpeg_resample_filter_candidates():
        if CALIBRATION_CACHE_WAV.exists():
            try:
                CALIBRATION_CACHE_WAV.unlink()
            except OSError:
                pass
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(CALIBRATION_SAMPLE_MP3),
            "-vn",
        ]
        if filter_expr:
            cmd += ["-af", filter_expr]
        cmd += [
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(CALIBRATION_CACHE_WAV),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=creationflags)
        if result.returncode == 0:
            _validate_wav_16k_mono(CALIBRATION_CACHE_WAV)
            return CALIBRATION_CACHE_WAV
        last_error = ffmpeg_error_tail(result.stderr, result.stdout)
    raise RuntimeError(f"ffmpeg calibration conversion failed: {last_error}")


def _select_model_name(preferred: Optional[str]) -> str:
    candidates = [
        preferred,
        "sherpa-onnx-zipformer-vi-2025-04-20",
        "zipformer-30m-rnnt-6000h",
        "sherpa-onnx-zipformer-vi-30M",
    ]
    for name in candidates:
        if not name or name == "rover-voting":
            continue
        if (Path(BASE_DIR) / "models" / name).is_dir():
            return name
    raise FileNotFoundError("No calibration ASR model directory found")


def _select_speaker_model(preferred: Optional[str]) -> Optional[str]:
    try:
        from core.speaker_diarization import get_available_models

        available = get_available_models()
    except Exception:
        return None

    for name in (
        preferred,
        "community1_pure_ort",
        "senko_campp_optimized",
        "senko_campp",
    ):
        if name and name in available:
            return name
    return None


def _dtype_for_ort(ort_type: str):
    import numpy as np

    text = str(ort_type).lower()
    if "int64" in text:
        return np.int64
    if "int32" in text:
        return np.int32
    if "float16" in text:
        return np.float16
    if "double" in text or "float64" in text:
        return np.float64
    return np.float32


def _shape_dim_value(dim: Any, axis: int, input_name: str, stage_key: str, batch: int) -> int:
    if isinstance(dim, int) and dim > 0:
        return int(dim)

    name = str(input_name or "").lower()
    stage = str(stage_key or "").lower()
    if axis == 0:
        return max(1, int(batch))
    if "input_offsets" in name or "num_words" in str(dim).lower():
        return 40
    if "input_ids" in name or "attention" in name or "token_type" in name or "seq" in str(dim).lower():
        return 80
    if "audio" in name or "wave" in name:
        return 144160
    if "campp" in stage or "pyannote" in stage or "frame" in str(dim).lower() or "time" in str(dim).lower():
        return 200
    return 80


def _make_stage_inputs(session: Any, stage_key: str, batch: int) -> Dict[str, Any]:
    import numpy as np

    rng = np.random.default_rng(12345)
    inputs: Dict[str, Any] = {}
    for item in session.get_inputs():
        shape = [
            _shape_dim_value(dim, axis, item.name, stage_key, batch)
            for axis, dim in enumerate(item.shape or [])
        ]
        dtype = _dtype_for_ort(item.type)
        name = str(item.name or "").lower()
        if np.issubdtype(dtype, np.integer):
            if "attention" in name:
                arr = np.ones(shape, dtype=dtype)
            elif "token_type" in name:
                arr = np.zeros(shape, dtype=dtype)
            elif "offset" in name and len(shape) == 2:
                arr = np.tile(np.arange(shape[1], dtype=dtype), (shape[0], 1))
            else:
                arr = rng.integers(1, 1000, size=shape, dtype=dtype)
        else:
            arr = rng.normal(0.0, 0.2, size=shape).astype(dtype)
        inputs[item.name] = arr
    return inputs


def _load_calibration_audio(wav_path: Path) -> Any:
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    if int(sr) != 16000:
        raise RuntimeError(f"calibration WAV must be 16 kHz, got {sr}")
    return np.asarray(audio, dtype=np.float32)


def _split_single_input_batches(name: str, array: Any, batch_size: int) -> List[Dict[str, Any]]:
    return _split_inputs_batches({name: array}, batch_size)


def _first_batch_dim(inputs: Dict[str, Any]) -> Optional[int]:
    for value in inputs.values():
        shape = getattr(value, "shape", None)
        if shape and len(shape) > 0:
            return int(shape[0])
    return None


def _split_inputs_batches(inputs: Dict[str, Any], batch_size: int) -> List[Dict[str, Any]]:
    total = _first_batch_dim(inputs)
    if not total:
        return [inputs]
    batches: List[Dict[str, Any]] = []
    step = max(1, int(batch_size or total or 1))
    for start in range(0, total, step):
        end = start + step
        item: Dict[str, Any] = {}
        for name, value in inputs.items():
            shape = getattr(value, "shape", None)
            if shape and len(shape) > 0 and int(shape[0]) == total:
                item[name] = value[start:end]
            else:
                item[name] = value
        batches.append(item)
    return batches or [inputs]


def _input_item_count(inputs: Any) -> int:
    if isinstance(inputs, list):
        return sum(_input_item_count(item) for item in inputs)
    if isinstance(inputs, dict):
        return int(_first_batch_dim(inputs) or 1)
    return 1


def _slice_inputs(inputs: Dict[str, Any], count: int) -> Dict[str, Any]:
    total = _first_batch_dim(inputs)
    if not total:
        return inputs
    count = max(1, min(int(count), total))
    item: Dict[str, Any] = {}
    for name, value in inputs.items():
        shape = getattr(value, "shape", None)
        if shape and len(shape) > 0 and int(shape[0]) == total:
            item[name] = value[:count]
        else:
            item[name] = value
    return item


def _limit_inputs(inputs: Any, max_items: int) -> Any:
    if not isinstance(inputs, list):
        return _slice_inputs(inputs, max_items) if isinstance(inputs, dict) else inputs
    remaining = max(1, int(max_items))
    limited: List[Dict[str, Any]] = []
    for item in inputs:
        count = _input_item_count(item)
        if count <= remaining:
            limited.append(item)
            remaining -= count
        else:
            limited.append(_slice_inputs(item, remaining))
            remaining = 0
        if remaining <= 0:
            break
    return limited or inputs[:1]


def _merge_input_batches(inputs: Any) -> Dict[str, Any]:
    import numpy as np

    if isinstance(inputs, dict):
        return inputs
    if not isinstance(inputs, list) or not inputs:
        return {}
    keys = list(inputs[0].keys())
    merged: Dict[str, Any] = {}
    for key in keys:
        values = [item[key] for item in inputs if key in item]
        if not values:
            continue
        first = values[0]
        shape = getattr(first, "shape", None)
        if shape and len(shape) > 0 and all(getattr(v, "shape", [None])[1:] == shape[1:] for v in values):
            try:
                merged[key] = np.concatenate(values, axis=0)
                continue
            except Exception:
                pass
        merged[key] = first
    return merged


def _select_even_inputs(inputs: Any, count: int) -> Dict[str, Any]:
    import numpy as np

    merged = _merge_input_batches(inputs)
    total = _first_batch_dim(merged)
    if not total:
        return merged
    count = max(1, min(int(count), int(total)))
    if count >= total:
        return merged
    indices = np.linspace(0, total - 1, num=count, dtype=np.int64)
    selected: Dict[str, Any] = {}
    for name, value in merged.items():
        shape = getattr(value, "shape", None)
        if shape and len(shape) > 0 and int(shape[0]) == total:
            selected[name] = value[indices]
        else:
            selected[name] = value
    return selected


def _sample_inputs(inputs: Any, count: int, batch_size: int) -> List[Dict[str, Any]]:
    return _split_inputs_batches(_select_even_inputs(inputs, count), batch_size)


def _progressive_item_counts(stage_key: str, total_items: int) -> List[int]:
    total = max(1, int(total_items or 1))
    key = str(stage_key or "").lower()
    if key == "speaker_campp_embedding":
        candidates = [64, 256, total]
    elif key == "speaker_pyannote_embedding":
        candidates = [12, 30, total]
    elif key == "dnsmos":
        candidates = [3, total]
    elif key == "punctuation":
        candidates = [8, 16, total]
    else:
        candidates = [min(total, 16), total]
    return sorted({max(1, min(int(value), total)) for value in candidates})


def _make_campp_sample_inputs(audio: Any, batch_size: int) -> Dict[str, Any]:
    import numpy as np
    from core.speaker_diarization_senko_campp_optimized import _compute_fbank

    fbank = _compute_fbank(audio, 16000)
    window_frames = 150
    step_frames = 60
    if fbank.shape[0] <= 0:
        raise RuntimeError("sample audio produced no CAM++ fbank frames")
    if fbank.shape[0] < window_frames:
        batch_feats = np.zeros((1, fbank.shape[0], 80), dtype=np.float32)
        batch_feats[0, : fbank.shape[0]] = fbank
        return {
            "inputs": _split_single_input_batches("feats", batch_feats, batch_size),
            "workload": {
                "source": "calibration_sample_10min",
                "unit": "campp_embedding_windows",
                "items": 1,
                "audio_sec": round(float(len(audio) / 16000), 3),
                "summary": "trích từ file mẫu 10 phút: 1 cửa sổ CAM++",
            },
        }

    positions = list(range(0, max(1, fbank.shape[0] - window_frames), step_frames))
    tail = max(0, fbank.shape[0] - window_frames)
    if not positions or positions[-1] != tail:
        positions.append(tail)
    batch_feats = np.zeros((len(positions), window_frames, 80), dtype=np.float32)
    for i, pos in enumerate(positions):
        batch_feats[i] = fbank[pos: pos + window_frames]
    return {
        "inputs": _split_single_input_batches("feats", batch_feats, batch_size),
        "workload": {
            "source": "calibration_sample_10min",
            "unit": "campp_embedding_windows",
            "items": len(positions),
            "audio_sec": round(float(len(audio) / 16000), 3),
            "summary": f"trích từ file mẫu 10 phút: {len(positions)} cửa sổ CAM++ embedding",
        },
    }


def _make_pyannote_embedding_sample_inputs(audio: Any, batch_size: int) -> Dict[str, Any]:
    import numpy as np
    from core.speaker_diarization_pure_ort import compute_emb_fbank

    chunk_samples = 10 * 16000
    starts = list(range(0, max(1, len(audio)), chunk_samples))
    chunks = []
    for start in starts:
        segment = audio[start: start + chunk_samples]
        if len(segment) < int(0.5 * 16000):
            continue
        if len(segment) < chunk_samples:
            padded = np.zeros(chunk_samples, dtype=np.float32)
            padded[: len(segment)] = segment
            segment = padded
        fbank = compute_emb_fbank(segment, 16000)
        if fbank.shape[0] > 0:
            chunks.append(fbank)
    if not chunks:
        raise RuntimeError("sample audio produced no Pyannote embedding fbank chunks")
    max_frames = max(chunk.shape[0] for chunk in chunks)
    batch = np.zeros((len(chunks), max_frames, 80), dtype=np.float32)
    for i, chunk in enumerate(chunks):
        batch[i, : chunk.shape[0]] = chunk
    return {
        "inputs": _split_single_input_batches("fbank_features", batch, batch_size),
        "workload": {
            "source": "calibration_sample_10min",
            "unit": "pyannote_embedding_chunks",
            "items": len(chunks),
            "audio_sec": round(float(len(audio) / 16000), 3),
            "summary": f"trích từ file mẫu 10 phút: {len(chunks)} chunk Pyannote embedding 10s",
        },
    }


def _make_dnsmos_sample_inputs(audio: Any, max_windows: int = 8, batch_size: Optional[int] = None) -> Dict[str, Any]:
    import numpy as np

    target_len = 144160
    if len(audio) <= 0:
        raise RuntimeError("sample audio is empty")
    if len(audio) < target_len:
        padded = np.zeros(target_len, dtype=np.float32)
        padded[: len(audio)] = audio
        windows = [padded]
    else:
        count = max(1, min(int(max_windows), 1 + (len(audio) - target_len) // target_len))
        starts = np.linspace(0, len(audio) - target_len, num=count, dtype=np.int64)
        windows = [audio[int(start): int(start) + target_len] for start in starts]
    batch = np.stack(windows, axis=0).astype(np.float32, copy=False)
    return {
        "inputs": _split_single_input_batches("input_1", batch, batch_size or max_windows),
        "workload": {
            "source": "calibration_sample_10min",
            "unit": "dnsmos_9s_windows",
            "items": len(windows),
            "audio_sec": round(float(len(audio) / 16000), 3),
            "summary": f"trích từ file mẫu 10 phút: {len(windows)} đoạn DNSMOS 9.01s",
        },
    }


def _make_stage_inputs_for_sample(session: Any, stage_key: str, batch: int, audio: Any) -> Dict[str, Any]:
    if stage_key == "speaker_campp_embedding":
        return _make_campp_sample_inputs(audio, batch)
    if stage_key == "speaker_pyannote_embedding":
        return _make_pyannote_embedding_sample_inputs(audio, batch)
    if stage_key == "dnsmos":
        return _make_dnsmos_sample_inputs(audio, max_windows=8, batch_size=batch)
    total_items = max(32, int(batch or 1))
    return {
        "inputs": _split_inputs_batches(_make_stage_inputs(session, stage_key, total_items), batch),
        "workload": {
            "source": "synthetic_tensor",
            "unit": "onnx_batch",
            "items": int(total_items),
            "summary": "tensor/text benchmark; không dùng audio vì stage cần transcript sau ASR",
        },
    }


def _run_ort_inputs(session: Any, inputs: Any) -> Any:
    import numpy as np

    if not isinstance(inputs, list):
        return session.run(None, inputs)
    merged: Optional[List[List[Any]]] = None
    for item in inputs:
        outputs = session.run(None, item)
        if merged is None:
            merged = [[] for _ in outputs]
        for idx, output in enumerate(outputs):
            merged[idx].append(output)
    if merged is None:
        return []
    result = []
    for parts in merged:
        try:
            result.append(np.concatenate(parts, axis=0))
        except Exception:
            result.append(parts[-1])
    return result


def _time_ort_session(session: Any, inputs: Any, repeats: int = 5, warmups: int = 1) -> Dict[str, Any]:
    last_outputs = None
    for _ in range(max(0, int(warmups))):
        last_outputs = _run_ort_inputs(session, inputs)
    started = time.perf_counter()
    for _ in range(max(1, repeats)):
        last_outputs = _run_ort_inputs(session, inputs)
    elapsed = (time.perf_counter() - started) / max(1, repeats)
    return {"elapsed_sec": elapsed, "outputs": last_outputs}


def _unique_sorted_numbers(values: List[int]) -> List[int]:
    return sorted({int(v) for v in values if int(v) > 0})


def _gpu_memory_gb() -> float:
    mb = gpu_vram_mb(free=True) or gpu_vram_mb(free=False) or 0
    return float(mb) / 1024.0 if mb else 0.0


def _batch_candidates(stage_key: str, fallback: int, provider: str) -> List[int]:
    if not is_gpu_provider(provider):
        return [max(1, int(fallback or 1))]
    memory = _gpu_memory_gb()
    key = str(stage_key or "").lower()
    fallback = max(1, int(fallback or 1))
    vendor = ""
    try:
        vendor = str((best_gpu() or {}).get("vendor") or "").lower()
    except Exception:
        vendor = ""
    if key == "speaker_pyannote_embedding":
        candidates = _unique_sorted_numbers([fallback, 1, 2, 4, 8, 16, 24, 32, auto_batch_size(key, fallback, provider)])
        return _cap_candidates(candidates, stage_key)
    if key == "speaker_campp_embedding":
        candidates = _unique_sorted_numbers([fallback, 1, 2, 4, 8, 16, 32, 64, 96, 128, auto_batch_size(key, fallback, provider)])
        return _cap_candidates(candidates, stage_key)
    if key == "punctuation":
        candidates = _unique_sorted_numbers([fallback, 1, 2, 4, 8, 16, 32, auto_batch_size(key, fallback, provider)])
        return _cap_candidates(candidates, stage_key)
    if key == "dnsmos":
        if provider == DML_PROVIDER and vendor == "intel":
            return [1, 2, 4]
        candidates = _unique_sorted_numbers([fallback, 1, 2, 4, 8, 16, auto_batch_size(key, fallback, provider)])
        return _cap_candidates(candidates, stage_key)
    candidates = _unique_sorted_numbers([fallback, 8, 16, 32, 64, auto_batch_size(key, fallback, provider)])
    return _cap_candidates(candidates, stage_key)


def _cap_candidates(candidates: List[int], stage_key: str) -> List[int]:
    key = str(stage_key or "").lower()
    memory = _gpu_memory_gb()
    if key == "speaker_pyannote_embedding":
        cap = 32 if memory >= 12 else (24 if memory >= 8 else (16 if memory >= 4 else 8))
    elif key == "speaker_campp_embedding":
        cap = 128 if memory >= 12 else (96 if memory >= 8 else (64 if memory >= 4 else 32))
    elif key == "punctuation":
        cap = 32 if memory >= 8 else (16 if memory >= 4 else 8)
    elif key == "dnsmos":
        cap = 16 if memory >= 8 else 8
    else:
        cap = 64 if memory >= 8 else (32 if memory >= 4 else 16)
    return [value for value in candidates if value <= cap] or [min(candidates or [1], cap)]


def _autotune_sample_count(candidates: List[int], total: int) -> int:
    max_candidate = max(candidates or [1])
    return max(1, min(int(total or 1), max(max_candidate, min(int(total or 1), max_candidate * 2))))


def _nearest_supported_batch(candidates: List[int], preferred: int) -> int:
    values = _unique_sorted_numbers(candidates)
    if not values:
        return max(1, int(preferred or 1))
    preferred = max(1, int(preferred or values[0]))
    lower_or_equal = [value for value in values if value <= preferred]
    if lower_or_equal:
        return lower_or_equal[-1]
    return values[0]


def _initial_batch_for_stage(stage_key: str, fallback: int, provider: str, candidates: List[int]) -> int:
    values = _unique_sorted_numbers(candidates)
    if not values:
        return max(1, int(fallback or 1))

    key = str(stage_key or "").lower()
    memory = _gpu_memory_gb()
    vendor = ""
    try:
        vendor = str((best_gpu() or {}).get("vendor") or "").lower()
    except Exception:
        vendor = ""

    preferred = auto_batch_size(key, fallback, provider)
    if provider == DML_PROVIDER and vendor in ("intel", "amd") and memory < 4:
        if key == "speaker_campp_embedding":
            preferred = min(preferred, 16)
        elif key == "speaker_pyannote_embedding":
            preferred = min(preferred, 4)
        elif key == "dnsmos":
            preferred = min(preferred, 2)
        elif key == "punctuation":
            preferred = min(preferred, 4)

    initial = _nearest_supported_batch(values, preferred)
    try:
        idx = values.index(initial)
    except ValueError:
        return initial

    # Start near the hardware-derived batch, but one notch below aggressive
    # values. The tuner immediately probes upward after this succeeds.
    if initial >= 8 and idx > 0:
        initial = values[idx - 1]
    return initial


def _short_error_message(exc: Any) -> str:
    text = str(exc)
    if not text:
        return type(exc).__name__
    if "Kernel after dilation has size" in text:
        return "OpenVINO không chạy được input/model này: AvgPool kernel lớn hơn kích thước tensor sau padding."
    if "OpenVINOExecutionProvider" in text and "Couldn't start Inference" in text:
        return "OpenVINO không chạy được stage này với input calibration hiện tại."
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compact = " ".join(lines)
    return compact[:300] + ("..." if len(compact) > 300 else "")


def _provider_error_reason(exc: Any) -> str:
    text = f"{type(exc).__name__}: {exc}"
    provider_tokens = (
        "DmlExecutionProvider",
        "DirectML",
        "CUDAExecutionProvider",
        "OpenVINOExecutionProvider",
        "ROCMExecutionProvider",
        "ONNXRuntimeError",
    )
    if any(token in text for token in provider_tokens):
        return "provider_runtime_unsupported"
    return "benchmark_error"


def _tune_gpu_batch(
    session: Any,
    base_inputs: Any,
    candidates: List[int],
    initial_batch: Optional[int] = None,
) -> Dict[str, Any]:
    total_items = _input_item_count(base_inputs)
    candidates = _unique_sorted_numbers(candidates)
    tune_items = _autotune_sample_count(candidates, total_items)
    attempts: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    initial = _nearest_supported_batch(candidates, initial_batch or max(candidates or [1]))
    probe_order: List[int] = []
    started_total = time.perf_counter()

    def _probe(candidate: int) -> Dict[str, Any]:
        try:
            inputs = _sample_inputs(base_inputs, tune_items, candidate)
            timed = _time_ort_session(session, inputs, repeats=1, warmups=1)
            elapsed = float(timed["elapsed_sec"])
            items = max(1, int(_input_item_count(inputs)))
            sec_per_item = elapsed / items
            attempt = {
                "batch": candidate,
                "ok": True,
                "elapsed_sec": round(float(elapsed), 6),
                "items": items,
                "sec_per_item": round(float(sec_per_item), 9),
                "items_per_sec": round(float(items / elapsed), 3) if elapsed > 0 else None,
            }
            return attempt
        except Exception as exc:
            return {"batch": candidate, "ok": False, "error": _short_error_message(exc)}

    def _record(candidate: int) -> Dict[str, Any]:
        nonlocal best
        probe_order.append(candidate)
        attempt = _probe(candidate)
        attempts.append(attempt)
        if attempt.get("ok") and (
            not best or float(attempt.get("sec_per_item") or 1e18) < float(best.get("sec_per_item") or 1e18)
        ):
            best = attempt
        return attempt

    initial_attempt = _record(initial)
    higher = [value for value in candidates if value > initial]
    lower = sorted([value for value in candidates if value < initial], reverse=True)

    if initial_attempt.get("ok"):
        for candidate in higher:
            attempt = _record(candidate)
            if not attempt.get("ok"):
                break
        for candidate in lower:
            _record(candidate)
    else:
        for candidate in lower:
            _record(candidate)

    total_sec = time.perf_counter() - started_total
    if not best:
        first_error = next((item.get("error") for item in attempts if item.get("error")), None)
        return {
            "selected_batch": None,
            "candidates": candidates,
            "initial_batch": initial,
            "probe_order": probe_order,
            "attempts": attempts,
            "total_sec": round(float(total_sec), 6),
            "tune_items": tune_items,
            "strategy": "start_hardware_batch_then_probe_up_down_select_best_throughput",
            "error": first_error or "all_batch_candidates_failed",
        }
    return {
        "selected_batch": best.get("batch"),
        "candidates": candidates,
        "initial_batch": initial,
        "probe_order": probe_order,
        "attempts": attempts,
        "working_batches": [item.get("batch") for item in attempts if item.get("ok")],
        "selected_items_per_sec": best.get("items_per_sec"),
        "selected_sec_per_item": best.get("sec_per_item"),
        "total_sec": round(float(total_sec), 6),
        "tune_items": tune_items,
        "strategy": "start_hardware_batch_then_probe_up_down_select_best_throughput",
    }


def _output_diff(cpu_outputs: Any, gpu_outputs: Any) -> Dict[str, Any]:
    import numpy as np

    if len(cpu_outputs or []) != len(gpu_outputs or []):
        return {"ok": False, "reason": "output_count_mismatch"}

    max_abs = 0.0
    mean_abs_total = 0.0
    rel_l2_max = 0.0
    compared = 0
    for cpu, gpu in zip(cpu_outputs or [], gpu_outputs or []):
        c = np.asarray(cpu)
        g = np.asarray(gpu)
        if c.shape != g.shape:
            return {"ok": False, "reason": f"shape_mismatch {c.shape} != {g.shape}"}
        if not np.issubdtype(c.dtype, np.number):
            continue
        cf = c.astype(np.float64, copy=False)
        gf = g.astype(np.float64, copy=False)
        diff = np.abs(cf - gf)
        if diff.size:
            max_abs = max(max_abs, float(np.max(diff)))
            mean_abs_total += float(np.mean(diff))
            denom = float(np.linalg.norm(cf.ravel())) + 1e-12
            rel_l2_max = max(rel_l2_max, float(np.linalg.norm((cf - gf).ravel()) / denom))
            compared += 1

    return {
        "ok": True,
        "outputs_compared": compared,
        "max_abs": max_abs,
        "mean_abs": mean_abs_total / max(1, compared),
        "rel_l2": rel_l2_max,
    }


def _run_stage_microbenchmarks(cpu_threads: int, wav_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    try:
        from core.hardware_accel import configure_gpu_addon_paths
        configure_gpu_addon_paths()
        import onnxruntime as ort  # type: ignore
        import numpy as np  # noqa: F401
    except Exception as exc:
        return [{"key": "onnxruntime", "label": "ONNX Runtime", "error": f"{type(exc).__name__}: {exc}"}]

    results: List[Dict[str, Any]] = []
    sample_audio = None
    if wav_path is not None:
        try:
            sample_audio = _load_calibration_audio(Path(wav_path))
        except Exception as exc:
            results.append({
                "key": "calibration_sample",
                "label": "Calibration sample",
                "selected_provider": "cpu",
                "error": _short_error_message(exc),
                "error_detail": f"{type(exc).__name__}: {exc}",
                "reason": "sample_load_error",
            })
    for spec in GPU_BENCHMARK_STAGES:
        path = Path(spec["path"])
        if not path.exists():
            results.append({
                "key": spec["key"],
                "label": spec["label"],
                "selected_provider": "cpu",
                "missing": str(path),
                "reason": "model_missing",
            })
            continue

        try:
            cpu_options = ort.SessionOptions()
            cpu_options.intra_op_num_threads = max(1, int(cpu_threads or 4))
            cpu_options.inter_op_num_threads = 1
            cpu_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            cpu_options.log_severity_level = 3
            cpu_load_started = time.perf_counter()
            cpu_session = ort.InferenceSession(str(path), cpu_options, providers=[CPU_PROVIDER])
            cpu_load_sec = time.perf_counter() - cpu_load_started

            gpu_options = ort.SessionOptions()
            gpu_options.intra_op_num_threads = max(1, int(cpu_threads or 4))
            gpu_options.inter_op_num_threads = 1
            gpu_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            gpu_options.log_severity_level = 3
            gpu_load_started = time.perf_counter()
            gpu_session, provider_info = create_ort_session(
                ort,
                str(path),
                gpu_options,
                policy="auto",
                stage=str(spec["label"]),
            )
            gpu_load_sec = time.perf_counter() - gpu_load_started
            actual_provider = actual_session_provider(gpu_session)
            if not is_gpu_provider(actual_provider):
                results.append({
                    "key": spec["key"],
                    "pipeline_key": spec.get("pipeline_key"),
                    "label": spec["label"],
                    "selected_provider": "cpu",
                    "actual_provider": actual_provider,
                    "skipped": True,
                    "cpu_load_sec": round(float(cpu_load_sec), 6),
                    "gpu_load_sec": round(float(gpu_load_sec), 6),
                    "error": provider_info.get("fallback_reason"),
                    "error_detail": provider_info.get("fallback_reason"),
                    "provider_info": provider_info,
                    "reason": "gpu_provider_fell_back_to_cpu",
                })
                continue

            default_batch = max(1, int(spec.get("batch_default") or 8))
            if sample_audio is not None:
                cpu_payload = _make_stage_inputs_for_sample(cpu_session, str(spec["key"]), default_batch, sample_audio)
            else:
                total_items = max(32, default_batch)
                cpu_payload = {
                    "inputs": _split_inputs_batches(_make_stage_inputs(cpu_session, str(spec["key"]), total_items), default_batch),
                    "workload": {
                        "source": "synthetic_tensor",
                        "unit": "onnx_batch",
                        "items": int(total_items),
                        "summary": "tensor benchmark; không có file mẫu",
                    },
                }
            cpu_inputs = cpu_payload["inputs"]
            workload = cpu_payload.get("workload") or {}
            total_items = _input_item_count(cpu_inputs)

            candidates = _batch_candidates(str(spec["key"]), default_batch, actual_provider)
            initial_batch = _initial_batch_for_stage(
                str(spec["key"]),
                default_batch,
                actual_provider,
                candidates,
            )
            tuning = _tune_gpu_batch(
                gpu_session,
                cpu_inputs,
                candidates,
                initial_batch=initial_batch,
            )
            batch = int(tuning.get("selected_batch") or default_batch)
            working_batches = sorted(
                {
                    int(value)
                    for value in (tuning.get("working_batches") or [])
                    if value and int(value) > 0
                },
                reverse=True,
            )
            if tuning.get("error") or not tuning.get("selected_batch"):
                results.append({
                    "key": spec["key"],
                    "pipeline_key": spec.get("pipeline_key"),
                    "label": spec["label"],
                    "selected_provider": "cpu",
                    "cpu_load_sec": round(float(cpu_load_sec), 6),
                    "gpu_load_sec": round(float(gpu_load_sec), 6),
                    "gpu_tune_sec": round(float(tuning.get("total_sec") or 0.0), 6),
                    "actual_provider": actual_provider,
                    "workload": workload,
                    "batch": batch,
                    "batch_tuning": tuning,
                    "error": tuning.get("error"),
                    "error_detail": json.dumps(tuning, ensure_ascii=False),
                    "reason": tuning.get("stop_reason") or "gpu_batch_tune_failed",
                })
                continue

            measurements = []
            cpu_timed = None
            gpu_timed = None
            diff: Dict[str, Any] = {"ok": False, "reason": "not_measured"}
            speedup = None
            inference_speedup = None
            diff_ok = False
            speed_ok = False
            selected = "cpu"
            reason = "gpu_not_faster_enough"
            sample_items = 0
            provider_retries = []
            tol = spec.get("tolerance") or {}
            for sample_items in _progressive_item_counts(str(spec["key"]), total_items):
                cpu_sample_inputs = _sample_inputs(cpu_inputs, sample_items, default_batch)
                gpu_sample_inputs = _sample_inputs(cpu_inputs, sample_items, batch)
                repeats = 2 if sample_items <= 16 else 1
                cpu_timed = _time_ort_session(cpu_session, cpu_sample_inputs, repeats=repeats, warmups=1)
                try:
                    gpu_timed = _time_ort_session(gpu_session, gpu_sample_inputs, repeats=repeats, warmups=1)
                except Exception as exc:
                    last_error = exc
                    retry_batches = [value for value in working_batches if value < batch]
                    if not retry_batches and batch > 1:
                        retry_batches = [1]
                    gpu_timed = None
                    for retry_batch in retry_batches:
                        retry_inputs = _sample_inputs(cpu_inputs, sample_items, retry_batch)
                        try:
                            gpu_timed = _time_ort_session(gpu_session, retry_inputs, repeats=repeats, warmups=1)
                            provider_retries.append({
                                "from_batch": batch,
                                "to_batch": retry_batch,
                                "items": int(sample_items),
                                "error": _short_error_message(last_error),
                                "recovered": True,
                            })
                            batch = retry_batch
                            break
                        except Exception as retry_exc:
                            provider_retries.append({
                                "from_batch": batch,
                                "to_batch": retry_batch,
                                "items": int(sample_items),
                                "error": _short_error_message(retry_exc),
                                "recovered": False,
                            })
                            last_error = retry_exc
                    if gpu_timed is None:
                        raise last_error
                diff = _output_diff(cpu_timed["outputs"], gpu_timed["outputs"])
                diff_ok = bool(
                    diff.get("ok")
                    and (
                        float(diff.get("max_abs") or 0.0) <= float(tol.get("max_abs") or 0.0)
                        or float(diff.get("rel_l2") or 0.0) <= float(tol.get("rel_l2") or 0.0)
                    )
                )
                speedup = (
                    float(cpu_timed["elapsed_sec"]) / float(gpu_timed["elapsed_sec"])
                    if cpu_timed.get("elapsed_sec") and gpu_timed.get("elapsed_sec")
                    else None
                )
                inference_speedup = speedup
                speed_ok = bool(speedup and speedup >= GPU_STAGE_SPEEDUP_MIN)
                measurements.append({
                    "items": int(sample_items),
                    "cpu_sec": round(float(cpu_timed["elapsed_sec"]), 6),
                    "gpu_sec": round(float(gpu_timed["elapsed_sec"]), 6),
                    "speedup": round(float(speedup), 3) if speedup else None,
                    "diff_ok": diff_ok,
                    "diff_max_abs": diff.get("max_abs"),
                    "diff_rel_l2": diff.get("rel_l2"),
                })
                if not diff_ok:
                    reason = "diff_exceeds_tolerance"
                    break
                if speedup and speedup >= 1.35:
                    selected = "auto"
                    reason = "accepted"
                    break
                if speedup and speedup < 1.10:
                    reason = "gpu_not_faster_enough"
                    break
                if sample_items >= total_items:
                    selected = "auto" if speed_ok else "cpu"
                    reason = "accepted" if selected == "auto" else "gpu_not_faster_enough"
                    break

            gpu_tune_sec = float(tuning.get("total_sec") or 0.0)
            cpu_total_sec = float(cpu_load_sec) + float(cpu_timed["elapsed_sec"])
            gpu_total_sec = float(gpu_load_sec) + gpu_tune_sec + float(gpu_timed["elapsed_sec"])
            results.append({
                "key": spec["key"],
                "pipeline_key": spec.get("pipeline_key"),
                "label": spec["label"],
                "selected_provider": selected,
                "cpu_sec": round(float(cpu_timed["elapsed_sec"]), 6),
                "gpu_sec": round(float(gpu_timed["elapsed_sec"]), 6),
                "cpu_load_sec": round(float(cpu_load_sec), 6),
                "gpu_load_sec": round(float(gpu_load_sec), 6),
                "gpu_tune_sec": round(float(gpu_tune_sec), 6),
                "cpu_total_sec": round(float(cpu_total_sec), 6),
                "gpu_total_sec": round(float(gpu_total_sec), 6),
                "speedup": round(float(speedup), 3) if speedup else None,
                "inference_speedup": round(float(inference_speedup), 3) if inference_speedup else None,
                "speedup_min": GPU_STAGE_SPEEDUP_MIN,
                "batch": batch,
                "batch_tuning": tuning,
                "provider_retries": provider_retries,
                "sample_items": int(sample_items),
                "sample_items_total": int(total_items),
                "progressive_measurements": measurements,
                "actual_provider": actual_provider,
                "workload": workload,
                "diff": {
                    "max_abs": diff.get("max_abs"),
                    "mean_abs": diff.get("mean_abs"),
                    "rel_l2": diff.get("rel_l2"),
                    "ok": diff_ok,
                    "tolerance": tol,
                    "reason": diff.get("reason"),
                },
                "accepted": bool(selected == "auto"),
                "reason": reason,
            })
        except Exception as exc:
            results.append({
                "key": spec["key"],
                "pipeline_key": spec.get("pipeline_key"),
                "label": spec["label"],
                "selected_provider": "cpu",
                "error": _short_error_message(exc),
                "error_detail": f"{type(exc).__name__}: {exc}",
                "reason": _provider_error_reason(exc),
            })
    return results


def _stage_provider_profile(stage_results: List[Dict[str, Any]], speaker_model: Optional[str]) -> Dict[str, str]:
    profile: Dict[str, str] = {
        "asr": "cpu",
        "audio_decode": "cpu",
        "vad": "cpu",
        "speaker_postprocess": "cpu",
    }
    by_key = {item.get("key"): item for item in stage_results}
    profile["dnsmos"] = by_key.get("dnsmos", {}).get("selected_provider", "cpu")
    profile["punctuation"] = by_key.get("punctuation", {}).get("selected_provider", "cpu")
    profile["diarization_campp"] = by_key.get("speaker_campp_embedding", {}).get("selected_provider", "cpu")
    profile["diarization_pyannote"] = by_key.get("speaker_pyannote_embedding", {}).get("selected_provider", "cpu")
    if speaker_model in ("senko_campp", "senko_campp_optimized"):
        profile["diarization"] = profile["diarization_campp"]
    else:
        profile["diarization"] = profile["diarization_pyannote"]
    return {key: ("auto" if value == "auto" else "cpu") for key, value in profile.items()}


def _active_profile_has_gpu(stage_profile: Dict[str, str]) -> bool:
    """Whether the current runtime configuration will actually use a GPU stage."""
    return any(
        str(stage_profile.get(key, "cpu")).lower() == "auto"
        for key in ("diarization", "dnsmos", "punctuation")
    )


def _run_pipeline_once(
    wav_path: Path,
    provider: str,
    model_name: str,
    speaker_model: Optional[str],
    cpu_threads: int,
    callback: Optional[Callable[[str, int], None]],
    start_percent: int,
    end_percent: int,
) -> Dict[str, Any]:
    from core.asr_engine import TranscriberPipeline

    model_path = Path(BASE_DIR) / "models" / model_name
    span = max(1, end_percent - start_percent)

    def _pipeline_progress(msg: str) -> None:
        # Keep UI progress coarse; detailed pipeline percentages are stage-local.
        lower = str(msg).lower()
        offset = 0
        if "diar" in lower or "người" in lower:
            offset = int(span * 0.55)
        elif "dấu" in lower or "punct" in lower:
            offset = int(span * 0.80)
        elif "asr" in lower or "nhận" in lower:
            offset = int(span * 0.25)
        _emit(callback, msg, start_percent + offset)

    config = {
        "cpu_threads": max(1, min(int(cpu_threads or 4), ALLOWED_THREADS)),
        "execution_provider": provider,
        "restore_punctuation": True,
        "bypass_restorer": False,
        "punctuation_confidence": 0.5 - (7 - 1) * (1.3 / 9),
        "case_confidence": -1.5 + (6 - 1) * (2.0 / 9),
        "speaker_diarization": bool(speaker_model),
        "speaker_model": speaker_model or "community1_pure_ort",
        "num_speakers": -1,
        "save_ram": True,
        "rover_mode": False,
        "resample_quality": "soxr_hq",
    }

    started = time.monotonic()
    pipeline = TranscriberPipeline(
        file_path=str(wav_path),
        model_path=str(model_path),
        config=config,
        progress_callback=_pipeline_progress,
    )
    result = pipeline.run()
    elapsed = time.monotonic() - started
    duration = float(result.get("duration_sec") or 0)
    segments = result.get("segments") or []
    text = result.get("text") or result.get("full_text") or ""
    speaker_ids = set()
    for seg in segments:
        speaker = seg.get("speaker") if isinstance(seg, dict) else None
        if speaker:
            speaker_ids.add(str(speaker))
    for seg in result.get("speaker_segments_raw") or []:
        speaker = seg.get("speaker") if isinstance(seg, dict) else None
        if speaker:
            speaker_ids.add(str(speaker))
    speaker_count = len(speaker_ids) or len(result.get("speaker_names") or {})

    return {
        "provider": provider,
        "model_name": model_name,
        "speaker_model": speaker_model,
        "elapsed_sec": elapsed,
        "duration_sec": duration,
        "rtf": elapsed / duration if duration > 0 else None,
        "timing": result.get("timing") or {},
        "quality_info": result.get("quality_info") or {},
        "asr_provider_info": result.get("asr_provider_info") or {},
        "execution_provider": result.get("execution_provider"),
        "asr_confidence": result.get("asr_confidence"),
        "text_chars": len(text),
        "segments": len(segments),
        "speaker_turns": len(result.get("speaker_segments_raw") or result.get("speaker_segments") or []),
        "speaker_count": speaker_count,
    }


def _compare_runs(cpu_run: Dict[str, Any], gpu_run: Dict[str, Any]) -> Dict[str, Any]:
    cpu_elapsed = float(cpu_run.get("elapsed_sec") or 0)
    gpu_elapsed = float(gpu_run.get("elapsed_sec") or 0)
    speedup = (cpu_elapsed / gpu_elapsed) if cpu_elapsed > 0 and gpu_elapsed > 0 else None

    stage_speedups: Dict[str, Any] = {}
    cpu_timing = cpu_run.get("timing") or {}
    gpu_timing = gpu_run.get("timing") or {}
    for key in sorted(set(cpu_timing) | set(gpu_timing)):
        c = float(cpu_timing.get(key) or 0)
        g = float(gpu_timing.get(key) or 0)
        stage_speedups[key] = round(c / g, 3) if c > 0 and g > 0 else None

    cpu_text_chars = int(cpu_run.get("text_chars") or 0)
    text_delta = int(gpu_run.get("text_chars") or 0) - cpu_text_chars
    text_delta_ratio = abs(text_delta) / max(1, cpu_text_chars)
    speaker_count_delta = int(gpu_run.get("speaker_count") or 0) - int(cpu_run.get("speaker_count") or 0)
    speaker_turn_delta = int(gpu_run.get("speaker_turns") or 0) - int(cpu_run.get("speaker_turns") or 0)
    confidence_delta = None
    if cpu_run.get("asr_confidence") is not None and gpu_run.get("asr_confidence") is not None:
        confidence_delta = float(gpu_run["asr_confidence"]) - float(cpu_run["asr_confidence"])

    text_ok = abs(text_delta) <= max(20, int(cpu_text_chars * 0.002))
    parity_ok = (
        text_ok
        and speaker_count_delta == 0
        and speaker_turn_delta == 0
        and (confidence_delta is None or abs(confidence_delta) < 1e-4)
    )
    faster = bool(speedup and speedup >= 1.05)

    return {
        "wall_speedup": round(speedup, 3) if speedup else None,
        "stage_speedups": stage_speedups,
        "text_chars_delta": text_delta,
        "text_chars_delta_ratio": text_delta_ratio,
        "text_tolerance_ok": text_ok,
        "speaker_count_delta": speaker_count_delta,
        "speaker_turn_delta": speaker_turn_delta,
        "confidence_delta": confidence_delta,
        "parity_ok": parity_ok,
        "gpu_faster": faster,
        "accepted": bool(parity_ok and faster),
    }


def run_device_calibration(
    model_name: Optional[str] = None,
    speaker_model: Optional[str] = None,
    cpu_threads: int = 4,
    callback: Optional[Callable[[str, int], None]] = None,
    save_report: bool = True,
) -> Dict[str, Any]:
    """Benchmark only GPU-sensitive stages and build a per-stage provider profile."""
    _emit(callback, "Detecting hardware", 1)
    status = detect_calibration_status()
    if not status.get("can_optimize"):
        report = {
            "status": "no_gpu",
            "selected_execution_provider": "cpu",
            "stage_execution_providers": {
                "asr": "cpu",
                "audio_decode": "cpu",
                "vad": "cpu",
                "diarization": "cpu",
                "diarization_campp": "cpu",
                "diarization_pyannote": "cpu",
                "speaker_postprocess": "cpu",
                "dnsmos": "cpu",
                "punctuation": "cpu",
            },
            "detect": status,
            "fixed_cpu_stages": PWA_FIXED_CPU_STAGES,
            "message": "Current CPU-only configuration is optimal for this machine.",
        }
        if save_report:
            CALIBRATION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            CALIBRATION_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    _emit(callback, "Preparing 10 minute calibration sample", 5)
    wav_path = ensure_calibration_wav()
    selected_speaker = _select_speaker_model(speaker_model)

    _emit(callback, "Benchmarking GPU-sensitive stages on calibration sample", 15)
    stage_results = _run_stage_microbenchmarks(cpu_threads, wav_path)
    stage_profile = _stage_provider_profile(stage_results, selected_speaker)
    selected_provider = "auto" if _active_profile_has_gpu(stage_profile) else "cpu"
    provider_probe = run_provider_probe("auto", light=False)
    stage_speedups = {
        item.get("key"): item.get("speedup")
        for item in stage_results
        if item.get("speedup") is not None
    }
    accepted_count = sum(1 for item in stage_results if item.get("accepted"))
    measured_count = sum(1 for item in stage_results if item.get("speedup") is not None)
    comparison = {
        "benchmark_mode": "per_stage_sample_workload",
        "speedup_min": GPU_STAGE_SPEEDUP_MIN,
        "policy": (
            "GPU selection uses per-stage ONNX inference time only. ONNX session load time and batch tuning time are not counted in speedup. "
            "Speaker embedding and DNSMOS timings use workloads extracted from the bundled 10-minute sample. "
            "Punctuation uses a tensor/text benchmark because transcript text is only available after ASR. "
            f"GPU is selected per stage only when speedup >= {GPU_STAGE_SPEEDUP_MIN:.2f}x "
            "and output diff is within tolerance by max_abs or rel_l2. Small numeric diff is accepted."
        ),
        "stage_speedups": stage_speedups,
        "stage_details": stage_results,
        "fixed_cpu_stages": PWA_FIXED_CPU_STAGES,
        "accepted_stage_count": accepted_count,
        "measured_stage_count": measured_count,
        "gpu_advice": _nvidia_cuda_advice(stage_results),
        "accepted": bool(accepted_count > 0),
        "parity_ok": all((item.get("diff") or {}).get("ok", True) for item in stage_results),
    }

    report = {
        "status": "completed",
        "selected_execution_provider": selected_provider,
        "stage_execution_providers": stage_profile,
        "detect": status,
        "sample_wav": str(wav_path),
        "model_name": _select_model_name(model_name),
        "speaker_model": selected_speaker,
        "runs": {},
        "comparison": comparison,
        "provider_probe": provider_probe,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if save_report:
        CALIBRATION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _emit(callback, "Calibration completed", 100)
    return report
