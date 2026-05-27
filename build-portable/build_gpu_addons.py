#!/usr/bin/env python3
"""Build optional GPU runtime add-ons for CPU portable bundles."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
BUILD_ROOT = PROJECT_ROOT / "build" / "gpu-addon-envs"
DIST_ROOT = PROJECT_ROOT / "dist"

def _load_version_short() -> str:
    spec = importlib.util.spec_from_file_location("_asr_vn_version", PROJECT_ROOT / "core" / "version.py")
    if spec is None or spec.loader is None:
        return "2.6.1"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_version_short()


VERSION = _load_version_short()

ADDONS = {
    "nvidia-cuda": {
        "artifact": "gpu-addon-nvidia-cuda-win64",
        "label": "NVIDIA CUDA",
        "provider": "CUDAExecutionProvider",
        "packages": ["onnxruntime-gpu[cuda,cudnn]", "onnx"],
    },
    "directml": {
        "artifact": "gpu-addon-directml-win64",
        "label": "DirectML (NVIDIA/AMD)",
        "provider": "DmlExecutionProvider",
        "packages": ["onnxruntime-directml", "onnx"],
    },
    "intel-openvino": {
        "artifact": "gpu-addon-intel-openvino-win64",
        "label": "Intel OpenVINO",
        "provider": "OpenVINOExecutionProvider",
        "packages": ["onnxruntime-openvino==1.24.1", "openvino==2025.4.1", "onnx"],
    },
}

SKIP_TOP_LEVEL = {
    "pip",
    "setuptools",
    "wheel",
    "pkg_resources",
    "_distutils_hack",
    "distutils-precedence.pth",
    "numpy",
    "numpy.libs",
}


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), check=True)


def _venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def _site_packages(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Lib" / "site-packages"
    py = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return venv / "lib" / py / "site-packages"


def _assert_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise RuntimeError(f"Refusing to operate outside {root_resolved}: {resolved}")
    return resolved


def _clean_dir(path: Path, allowed_root: Path) -> None:
    resolved = _assert_inside(path, allowed_root)
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def _should_skip(name: str) -> bool:
    lower = name.lower()
    if lower in SKIP_TOP_LEVEL:
        return True
    for item in SKIP_TOP_LEVEL:
        base = item.replace("-", "_").lower()
        if lower.startswith(base + "-") and lower.endswith((".dist-info", ".egg-info")):
            return True
    return False


def _copy_runtime_packages(src_site: Path, dst_site: Path) -> None:
    copied = 0
    for item in src_site.iterdir():
        if item.name.startswith("~") or _should_skip(item.name):
            continue
        dst = dst_site / item.name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if item.is_dir():
            shutil.copytree(item, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
        else:
            shutil.copy2(item, dst)
        copied += 1
    print(f"[OK] Copied {copied} runtime package entries")


def _write_readme(out_dir: Path, addon_id: str, meta: dict) -> None:
    readme = f"""Sherpa Vietnamese ASR GPU Add-on: {meta['label']}

Version: {VERSION}
Provider: {meta['provider']}

Install:
1. Download the matching Sherpa Vietnamese ASR app for the same version.
2. Extract this zip into the app root folder, the folder that contains app.py or server_launcher.py.
3. After extraction, this path must exist in the app root folder:
   gpu_addons\\{addon_id}\\Lib\\site-packages\\onnxruntime\\
4. Close the app completely, open it again, then click "Tối ưu thiết bị".

Do not install this package globally. It is only an app-local runtime add-on.
"""
    (out_dir / "README-GPU-ADDON.txt").write_text(readme, encoding="utf-8")


def _zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in src_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src_dir))
    print(f"[OK] Wrote {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")


def build_addon(addon_id: str, keep_env: bool = False, make_zip: bool = True) -> Path:
    meta = ADDONS[addon_id]
    env_dir = BUILD_ROOT / addon_id
    out_dir = DIST_ROOT / f"{meta['artifact']}-{VERSION}"
    addon_root = out_dir / "gpu_addons" / addon_id
    dst_site = addon_root / "Lib" / "site-packages"

    _clean_dir(out_dir, DIST_ROOT)
    if not keep_env:
        _clean_dir(env_dir, BUILD_ROOT)
        _run([sys.executable, "-m", "venv", str(env_dir)])

    py = _venv_python(env_dir)
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    for package in meta["packages"]:
        _run([str(py), "-m", "pip", "install", "--upgrade", package])

    dst_site.mkdir(parents=True, exist_ok=True)
    _copy_runtime_packages(_site_packages(env_dir), dst_site)

    addon_json = {
        "id": addon_id,
        "artifact": meta["artifact"],
        "label": meta["label"],
        "provider": meta["provider"],
        "version": VERSION,
        "layout": "gpu_addons/<id>/Lib/site-packages",
    }
    (addon_root / "addon.json").write_text(json.dumps(addon_json, indent=2), encoding="utf-8")
    _write_readme(out_dir, addon_id, meta)

    if make_zip:
        _zip_dir(out_dir, DIST_ROOT / f"{meta['artifact']}-{VERSION}.zip")
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "addons",
        nargs="*",
        choices=sorted(ADDONS.keys()),
        help="Add-on ids to build. Omit with --all to build every add-on.",
    )
    parser.add_argument("--all", action="store_true", help="Build all add-ons")
    parser.add_argument("--keep-env", action="store_true", help="Reuse existing add-on build venvs")
    parser.add_argument("--no-zip", action="store_true", help="Only create folders under dist/")
    args = parser.parse_args()

    selected = list(ADDONS) if args.all else args.addons
    if not selected:
        parser.error("choose at least one add-on or pass --all")

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    for addon_id in selected:
        print("=" * 60)
        print(f"Building {addon_id}")
        print("=" * 60)
        build_addon(addon_id, keep_env=args.keep_env, make_zip=not args.no_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
