"""
Hardware and ONNX Runtime acceleration helpers.

The desktop pipeline must be conservative: request a GPU provider only when it
is present, verify that ORT actually used it, and fall back to CPU otherwise.
"""
from __future__ import annotations

import csv
import importlib.util
import os
import platform
import site
import subprocess
import sys
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CPU_PROVIDER = "CPUExecutionProvider"
CUDA_PROVIDER = "CUDAExecutionProvider"
OPENVINO_PROVIDER = "OpenVINOExecutionProvider"
DML_PROVIDER = "DmlExecutionProvider"
ROCM_PROVIDER = "ROCMExecutionProvider"
_DLL_DIR_HANDLES: List[Any] = []

GPU_ADDON_DEFS: Dict[str, Dict[str, str]] = {
    "nvidia-cuda": {
        "artifact": "gpu-addon-nvidia-cuda-win64",
        "provider": CUDA_PROVIDER,
        "label": "NVIDIA CUDA",
    },
    "directml": {
        "artifact": "gpu-addon-directml-win64",
        "provider": DML_PROVIDER,
        "label": "DirectML (NVIDIA/AMD)",
    },
    "intel-openvino": {
        "artifact": "gpu-addon-intel-openvino-win64",
        "provider": OPENVINO_PROVIDER,
        "label": "Intel OpenVINO",
    },
}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _version_short() -> str:
    spec = importlib.util.spec_from_file_location("_asr_vn_version", project_root() / "core" / "version.py")
    if spec is None or spec.loader is None:
        return "<version>"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_version_short()


def gpu_addon_site_package_candidates(addon_id: str) -> List[Path]:
    root = project_root()
    meta = GPU_ADDON_DEFS[addon_id]
    candidates = [root / "gpu_addons" / addon_id / "Lib" / "site-packages"]
    for folder in sorted(root.glob(f"{meta['artifact']}-*")):
        candidates.append(folder / "gpu_addons" / addon_id / "Lib" / "site-packages")
    return candidates


def gpu_addon_site_packages(addon_id: str) -> Path:
    for candidate in gpu_addon_site_package_candidates(addon_id):
        if (candidate / "onnxruntime").is_dir():
            return candidate
    return gpu_addon_site_package_candidates(addon_id)[0]


def gpu_addon_expected_onnxruntime_path(addon_id: str) -> Path:
    return gpu_addon_site_packages(addon_id) / "onnxruntime"


def gpu_addon_installed(addon_id: str) -> bool:
    try:
        return gpu_addon_expected_onnxruntime_path(addon_id).is_dir()
    except Exception:
        return False


def installed_gpu_addons() -> List[Dict[str, Any]]:
    addons: List[Dict[str, Any]] = []
    for addon_id, meta in GPU_ADDON_DEFS.items():
        site_dir = gpu_addon_site_packages(addon_id)
        expected_onnxruntime = site_dir / "onnxruntime"
        addons.append(
            {
                "id": addon_id,
                "label": meta["label"],
                "artifact": meta["artifact"],
                "provider": meta["provider"],
                "installed": expected_onnxruntime.is_dir(),
                "site_packages": str(site_dir),
                "expected_path": str(expected_onnxruntime),
                "expected_display_path": f"/gpu_addons/{addon_id}/Lib/site-packages/onnxruntime/",
            }
        )
    return addons


def gpu_addon_install_hint(addon_id: str) -> Dict[str, Any]:
    expected = gpu_addon_expected_onnxruntime_path(addon_id)
    root = project_root()
    candidates = [
        str(candidate / "onnxruntime")
        for candidate in gpu_addon_site_package_candidates(addon_id)
        if (candidate / "onnxruntime").is_dir()
    ][:5]
    return {
        "expected_path": str(expected),
        "expected_display_path": f"/gpu_addons/{addon_id}/Lib/site-packages/onnxruntime/",
        "found_candidates": candidates,
        "zip_at_root": str(root / f"{GPU_ADDON_DEFS[addon_id]['artifact']}.zip"),
    }


def _gpu_addon_dll_dirs(site_dir: Path) -> List[Path]:
    dirs = [
        site_dir,
        site_dir / "onnxruntime" / "capi",
        site_dir / "openvino" / "libs",
        site_dir / "openvino" / "runtime" / "bin" / "intel64" / "Release",
    ]
    for dll_name in (
        "openvino.dll",
        "openvino_intel_cpu_plugin.dll",
        "openvino_intel_gpu_plugin.dll",
        "intel_gpu_plugin.dll",
    ):
        try:
            dirs.extend(path.parent for path in site_dir.rglob(dll_name))
        except OSError:
            pass

    unique: List[Path] = []
    seen = set()
    for path in dirs:
        text = str(path)
        if text not in seen:
            unique.append(path)
            seen.add(text)
    return unique


def recommended_gpu_addon() -> Optional[Dict[str, Any]]:
    """Return the default GPU add-on recommendation.

    DirectML is kept as the compact NVIDIA/AMD path. Intel should use
    OpenVINO because that add-on is small and vendor-optimized.
    """
    nvidia = detect_nvidia_gpus()
    controllers = detect_windows_video_controllers()
    if platform.system().lower() != "windows" or not (nvidia or controllers):
        return None

    vendors = [str(controller.get("vendor") or "").lower() for controller in controllers]
    if nvidia or "nvidia" in vendors:
        addon_id = "directml"
    elif "intel" in vendors:
        addon_id = "intel-openvino"
    elif "amd" in vendors:
        addon_id = "directml"
    else:
        return None

    meta = dict(GPU_ADDON_DEFS[addon_id])
    meta["id"] = addon_id
    try:
        version = _version_short()
    except Exception:
        version = "<version>"
    meta["zip_name"] = f"{meta['artifact']}-{version}.zip"
    meta["installed"] = gpu_addon_expected_onnxruntime_path(addon_id).is_dir()
    meta.update(gpu_addon_install_hint(addon_id))
    return meta


def _configured_addon_ids() -> List[str]:
    """Return add-ons to load for the requested acceleration mode."""
    requested = (os.environ.get("ASR_VN_ACCEL") or "").strip().lower()
    if requested == "cuda":
        return ["nvidia-cuda"]
    if requested == "nvidia":
        return ["directml"]
    if requested in ("openvino", "intel"):
        return ["intel-openvino"]
    if requested in ("directml", "dml", "amd"):
        return ["directml"]

    recommendation = recommended_gpu_addon()
    if recommendation:
        return [recommendation["id"]]

    if os.environ.get("ASR_VN_GPU_ADDON_FALLBACKS") == "1":
        return list(GPU_ADDON_DEFS)
    return []


@lru_cache(maxsize=1)
def configure_gpu_addon_paths() -> List[str]:
    """Prepend installed GPU add-on site-packages before importing ORT."""
    added: List[str] = []
    for addon_id in _configured_addon_ids():
        site_dir = gpu_addon_site_packages(addon_id)
        if not (site_dir / "onnxruntime").is_dir():
            continue
        text = str(site_dir)
        if text not in sys.path:
            sys.path.insert(0, text)
        if platform.system().lower() == "windows":
            for dll_dir in _gpu_addon_dll_dirs(site_dir):
                if not dll_dir.exists():
                    continue
                dll_text = str(dll_dir)
                os.environ["PATH"] = dll_text + os.pathsep + os.environ.get("PATH", "")
                if hasattr(os, "add_dll_directory"):
                    try:
                        _DLL_DIR_HANDLES.append(os.add_dll_directory(dll_text))
                    except Exception:
                        pass
        added.append(text)
    return added


def _run_text(cmd: Sequence[str], timeout: float = 4.0) -> str:
    try:
        proc = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def _parse_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


@lru_cache(maxsize=1)
def detect_nvidia_gpus() -> List[Dict[str, Any]]:
    out = _run_text(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ],
        timeout=5.0,
    )
    gpus: List[Dict[str, Any]] = []
    if not out:
        return gpus
    for row in csv.reader(out.splitlines()):
        if len(row) < 4:
            continue
        total_mb = _parse_int(row[1])
        free_mb = _parse_int(row[2])
        gpus.append(
            {
                "vendor": "nvidia",
                "name": row[0].strip(),
                "vram_total_mb": total_mb,
                "vram_free_mb": free_mb,
                "driver_version": row[3].strip(),
            }
        )
    return gpus


@lru_cache(maxsize=1)
def detect_windows_video_controllers() -> List[Dict[str, Any]]:
    if platform.system().lower() != "windows":
        return []
    out = _run_text(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Csv -NoTypeInformation",
        ],
        timeout=6.0,
    )
    if not out:
        return []
    rows = list(csv.DictReader(out.splitlines()))
    controllers: List[Dict[str, Any]] = []
    for row in rows:
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        lower = name.lower()
        if "intel" in lower:
            vendor = "intel"
        elif "nvidia" in lower:
            vendor = "nvidia"
        elif "amd" in lower or "radeon" in lower or "advanced micro devices" in lower:
            vendor = "amd"
        else:
            vendor = "unknown"
        controllers.append(
            {
                "vendor": vendor,
                "name": name,
                "adapter_ram_bytes": _parse_int(row.get("AdapterRAM")),
                "driver_version": (row.get("DriverVersion") or "").strip(),
            }
        )
    return controllers


def ort_available_providers(ort_module=None) -> List[str]:
    try:
        ort = ort_module
        if ort is None:
            configure_gpu_addon_paths()
            import onnxruntime as ort  # type: ignore
        return list(ort.get_available_providers())
    except Exception:
        return []


@lru_cache(maxsize=1)
def preload_ort_cuda_dlls() -> Dict[str, Any]:
    """Make CUDA/cuDNN pip-package DLLs visible to ONNX Runtime on Windows."""
    added: List[str] = []
    errors: List[str] = []

    if platform.system().lower() == "windows" and hasattr(os, "add_dll_directory"):
        roots = list(site.getsitepackages())
        roots.extend(configure_gpu_addon_paths())
        for root in roots:
            nvidia_root = Path(root) / "nvidia"
            if not nvidia_root.exists():
                continue
            for bin_dir in sorted(nvidia_root.glob("*/bin")):
                if not bin_dir.is_dir():
                    continue
                text = str(bin_dir)
                try:
                    _DLL_DIR_HANDLES.append(os.add_dll_directory(text))
                    os.environ["PATH"] = text + os.pathsep + os.environ.get("PATH", "")
                    added.append(text)
                except Exception as exc:
                    errors.append(f"{text}: {type(exc).__name__}: {exc}")

    try:
        import onnxruntime as ort  # type: ignore
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls(cuda=True, cudnn=True, msvc=True)
    except Exception as exc:
        errors.append(f"onnxruntime.preload_dlls: {type(exc).__name__}: {exc}")

    return {"added": added, "errors": errors}


@lru_cache(maxsize=1)
def detect_hardware() -> Dict[str, Any]:
    nvidia = detect_nvidia_gpus()
    controllers = detect_windows_video_controllers()
    gpus = list(nvidia)
    known = {gpu["name"].lower() for gpu in gpus}
    for ctl in controllers:
        if ctl["name"].lower() not in known:
            gpus.append(ctl)
    return {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or 1,
        "gpus": gpus,
        "nvidia_gpus": nvidia,
        "video_controllers": controllers,
        "ort_available_providers": ort_available_providers(),
    }


def best_gpu() -> Optional[Dict[str, Any]]:
    gpus = detect_hardware().get("gpus") or []
    if not gpus:
        return None
    nvidia = [g for g in gpus if g.get("vendor") == "nvidia"]
    if nvidia:
        return max(nvidia, key=lambda g: g.get("vram_total_mb") or 0)
    intel = [g for g in gpus if g.get("vendor") == "intel"]
    if intel:
        return intel[0]
    amd = [g for g in gpus if g.get("vendor") == "amd"]
    if amd:
        return amd[0]
    return gpus[0]


def preferred_gpu_provider(policy: str = "auto", ort_module=None) -> Optional[str]:
    policy = (policy or "cpu").lower()
    if policy in ("cpu", "none", "off"):
        return None

    available = set(ort_available_providers(ort_module))
    gpu = best_gpu()

    if policy in ("cuda",):
        return CUDA_PROVIDER if CUDA_PROVIDER in available else None
    if policy in ("nvidia",):
        if DML_PROVIDER in available:
            return DML_PROVIDER
        return CUDA_PROVIDER if CUDA_PROVIDER in available else None
    if policy in ("openvino", "intel"):
        return OPENVINO_PROVIDER if OPENVINO_PROVIDER in available else None
    if policy in ("directml", "dml", "amd"):
        if DML_PROVIDER in available:
            return DML_PROVIDER
        if ROCM_PROVIDER in available:
            return ROCM_PROVIDER
        return None
    if policy in ("rocm",):
        return ROCM_PROVIDER if ROCM_PROVIDER in available else None
    if policy not in ("auto", "gpu"):
        return None

    if gpu and gpu.get("vendor") == "nvidia" and DML_PROVIDER in available:
        return DML_PROVIDER
    if gpu and gpu.get("vendor") == "intel" and OPENVINO_PROVIDER in available:
        return OPENVINO_PROVIDER
    if gpu and gpu.get("vendor") == "amd" and DML_PROVIDER in available:
        return DML_PROVIDER
    if gpu and gpu.get("vendor") == "amd" and ROCM_PROVIDER in available:
        return ROCM_PROVIDER
    return None


def ort_provider_request(policy: str = "cpu", ort_module=None) -> List[str]:
    provider = preferred_gpu_provider(policy, ort_module)
    if provider:
        return [provider, CPU_PROVIDER]
    return [CPU_PROVIDER]


def actual_session_provider(session: Any) -> str:
    try:
        providers = list(session.get_providers())
    except Exception:
        return CPU_PROVIDER
    for provider in (CUDA_PROVIDER, OPENVINO_PROVIDER, DML_PROVIDER, ROCM_PROVIDER):
        if provider in providers:
            return provider
    return providers[0] if providers else CPU_PROVIDER


def is_gpu_provider(provider: Optional[str]) -> bool:
    return provider in {CUDA_PROVIDER, OPENVINO_PROVIDER, DML_PROVIDER, ROCM_PROVIDER}


def _ensure_campp_poolpad_model(model_path: str) -> Optional[str]:
    """Return or build the GPU-compatible CAM++ graph when possible.

    CAM++ has CAM-layer AveragePool(kernel=100, stride=100, ceil_mode=1,
    count_include_pad=1). ORT CPU divides the last partial window by 100, while
    CUDA EP divides by the number of real elements. Padding the time axis to the
    next multiple of 100 before those pools makes GPU output match CPU
    semantics and also prevents OpenVINO from rejecting short internal tensors.

    This graph is derived from the CPU ONNX file, so the app may generate it
    lazily during calibration/runtime instead of shipping it in the base bundle.
    """
    src = Path(model_path)
    if not src.exists():
        return None
    dst = src.with_name(src.stem + ".gpu.onnx")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return str(dst)
    try:
        import numpy as np  # type: ignore
        import onnx  # type: ignore
        from onnx import helper, numpy_helper  # type: ignore

        model = onnx.load(str(src))
        existing = {init.name for init in model.graph.initializer}

        def _add_init(name: str, arr: Any) -> None:
            if name not in existing:
                model.graph.initializer.append(numpy_helper.from_array(np.asarray(arr), name))
                existing.add(name)

        _add_init("__campp_pool_axis2", np.array(2, dtype=np.int64))
        _add_init("__campp_pool_kernel100", np.array(100, dtype=np.int64))
        _add_init("__campp_pool_unsq_axes0", np.array([0], dtype=np.int64))
        _add_init("__campp_pool_pads_prefix5", np.array([0, 0, 0, 0, 0], dtype=np.int64))

        new_nodes = []
        patched = 0
        for node in model.graph.node:
            is_pool = node.op_type == "AveragePool" and any(
                attr.name == "kernel_shape" and list(attr.ints) == [100]
                for attr in node.attribute
            )
            if is_pool:
                base = (node.name or f"avgpool_{patched}").replace("/", "_").replace(":", "_")
                x = node.input[0]
                shape = f"{base}_shape"
                tdim = f"{base}_tdim"
                mod = f"{base}_mod"
                need = f"{base}_need"
                pad = f"{base}_pad"
                pad1 = f"{base}_pad1"
                pads = f"{base}_pads"
                padded = f"{base}_padded"
                new_nodes.extend([
                    helper.make_node("Shape", [x], [shape], name=f"{base}_Shape"),
                    helper.make_node("Gather", [shape, "__campp_pool_axis2"], [tdim], name=f"{base}_GatherTime", axis=0),
                    helper.make_node("Mod", [tdim, "__campp_pool_kernel100"], [mod], name=f"{base}_Mod100", fmod=0),
                    helper.make_node("Sub", ["__campp_pool_kernel100", mod], [need], name=f"{base}_NeedPad"),
                    helper.make_node("Mod", [need, "__campp_pool_kernel100"], [pad], name=f"{base}_PadToMultiple100", fmod=0),
                    helper.make_node("Unsqueeze", [pad, "__campp_pool_unsq_axes0"], [pad1], name=f"{base}_UnsqueezePad"),
                    helper.make_node("Concat", ["__campp_pool_pads_prefix5", pad1], [pads], name=f"{base}_Pads", axis=0),
                    helper.make_node("Pad", [x, pads], [padded], name=f"{base}_PadPoolInput", mode="constant"),
                ])
                node.input[0] = padded
                patched += 1
            new_nodes.append(node)
        if patched <= 0:
            return None
        del model.graph.node[:]
        model.graph.node.extend(new_nodes)
        onnx.checker.check_model(model)
        onnx.save(model, str(dst))
        return str(dst)
    except Exception:
        return str(dst) if dst.exists() else None


def _ensure_openvino_campp_model(model_path: str) -> Optional[str]:
    """Backward-compatible name used by build scripts."""
    return _ensure_campp_poolpad_model(model_path)


def create_ort_session(
    ort_module: Any,
    model_path: str,
    sess_options: Any,
    policy: str = "cpu",
    stage: str = "",
) -> Tuple[Any, Dict[str, Any]]:
    """Create an ORT session and verify the requested provider really stuck."""
    requested = ort_provider_request(policy, ort_module)
    tried: List[Dict[str, Any]] = []

    stage_lower = str(stage or "").lower()
    model_lower = str(model_path or "").lower()
    campp_patch: Optional[str] = None
    if requested and requested[0] != CPU_PROVIDER and (
        "cam++" in stage_lower or "campp" in stage_lower or "campplus" in model_lower
    ):
        campp_patch = _ensure_campp_poolpad_model(model_path)
        if campp_patch:
            model_path = campp_patch

    def _create(providers: List[str]):
        if providers and providers[0] == DML_PROVIDER:
            try:
                sess_options.enable_mem_pattern = False
            except Exception:
                pass
            try:
                sess_options.execution_mode = ort_module.ExecutionMode.ORT_SEQUENTIAL
            except Exception:
                pass
        return ort_module.InferenceSession(model_path, sess_options, providers=providers)

    if requested != [CPU_PROVIDER]:
        try:
            if requested[0] == CUDA_PROVIDER:
                preload_ort_cuda_dlls()
            session = _create(requested)
            actual = actual_session_provider(session)
            info = {
                "stage": stage,
                "policy": policy,
                "requested_providers": requested,
                "actual_provider": actual,
                "session_providers": list(session.get_providers()),
                "used_gpu": is_gpu_provider(actual),
                "fallback_reason": None,
            }
            if campp_patch:
                info["model_path"] = campp_patch
                info["model_patch"] = "campp_avgpool_pad_to_multiple_100"
            if is_gpu_provider(requested[0]) and not is_gpu_provider(actual):
                info["fallback_reason"] = f"requested {requested[0]} but ORT created {actual}"
            return session, info
        except Exception as exc:
            tried.append({"providers": requested, "error": f"{type(exc).__name__}: {exc}"})

    session = _create([CPU_PROVIDER])
    info = {
        "stage": stage,
        "policy": policy,
        "requested_providers": requested,
        "actual_provider": actual_session_provider(session),
        "session_providers": list(session.get_providers()),
        "used_gpu": False,
        "fallback_reason": tried[-1]["error"] if tried else None,
        "tried": tried,
    }
    return session, info


def gpu_vram_mb(free: bool = True) -> Optional[int]:
    gpu = best_gpu()
    if not gpu:
        return None
    key = "vram_free_mb" if free else "vram_total_mb"
    value = gpu.get(key)
    if value is None and not free:
        ram_bytes = gpu.get("adapter_ram_bytes")
        if ram_bytes:
            value = int(ram_bytes / (1024 * 1024))
    return _parse_int(value)


def auto_batch_size(stage: str, default: int, provider: Optional[str] = None) -> int:
    if not is_gpu_provider(provider):
        return int(default)

    free_mb = gpu_vram_mb(free=True)
    total_mb = gpu_vram_mb(free=False)
    budget_mb = free_mb or total_mb or 0
    stage_key = (stage or "").lower()

    if "pyannote" in stage_key and "embedding" in stage_key:
        if budget_mb >= 10000:
            return 32
        if budget_mb >= 6000:
            return 24
        if budget_mb >= 3000:
            return 16
        return 8

    if "punct" in stage_key or "vibert" in stage_key:
        if budget_mb >= 6000:
            return 32
        if budget_mb >= 2500:
            return 16
        return 8

    if "campp" in stage_key or "speaker" in stage_key:
        if budget_mb >= 10000:
            return 128
        if budget_mb >= 7000:
            return 96
        if budget_mb >= 3500:
            return 64
        return 32

    if budget_mb >= 7000:
        return max(default, 64)
    if budget_mb >= 3500:
        return max(default, 32)
    return min(default, 16)


def hardware_summary() -> str:
    hw = detect_hardware()
    gpus = hw.get("gpus") or []
    if not gpus:
        gpu_text = "no GPU detected"
    else:
        parts = []
        for gpu in gpus:
            name = gpu.get("name", "unknown")
            total = gpu.get("vram_total_mb")
            free = gpu.get("vram_free_mb")
            if total:
                parts.append(f"{name} ({free or '?'} / {total} MB free/total)")
            else:
                parts.append(name)
        gpu_text = "; ".join(parts)
    providers = ", ".join(hw.get("ort_available_providers") or [])
    return f"CPU cores={hw.get('cpu_count')}; GPU={gpu_text}; ORT providers=[{providers}]"
