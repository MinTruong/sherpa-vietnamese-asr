#!/usr/bin/env python3
"""Build optional GPU model package for CPU-only app bundles."""
from __future__ import annotations

import shutil
import sys
import zipfile
import importlib.util
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
DIST_ROOT = PROJECT_ROOT / "dist"

def _load_version_short() -> str:
    spec = importlib.util.spec_from_file_location("_asr_vn_version", PROJECT_ROOT / "core" / "version.py")
    if spec is None or spec.loader is None:
        return "2.6.1"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_version_short()


VERSION = _load_version_short()
ARTIFACT = "gpu-models-win64"

FILES = [
    (
        PROJECT_ROOT / "models" / "vibert-capu" / "vibert-capu.onnx",
        Path("models") / "vibert-capu" / "vibert-capu.onnx",
    ),
]


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


def _zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in src_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src_dir))
    print(f"[OK] Wrote {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")


def build_gpu_models(make_zip: bool = True) -> Path:
    out_dir = DIST_ROOT / f"{ARTIFACT}-{VERSION}"
    _clean_dir(out_dir, DIST_ROOT)

    for src, rel in FILES:
        if not src.is_file():
            raise FileNotFoundError(f"Missing GPU model source: {src}")
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[OK] Copied {rel}")

    readme = f"""Sherpa Vietnamese ASR GPU Models

Version: {VERSION}

Contains:
- models\\vibert-capu\\vibert-capu.onnx

Install:
1. Download the matching Sherpa Vietnamese ASR app for the same version.
2. Extract this zip into the app root folder, the folder that contains app.py or server_launcher.py.
3. After extraction, this path must exist in the app root folder:
   models\\vibert-capu\\vibert-capu.onnx
4. Install the matching GPU runtime add-on, then reopen the app and click "Tối ưu".

CAM++ GPU graph is generated automatically from the CPU ONNX model when needed.
"""
    (out_dir / "README-GPU-MODELS.txt").write_text(readme, encoding="utf-8")

    if make_zip:
        _zip_dir(out_dir, DIST_ROOT / f"{ARTIFACT}-{VERSION}.zip")
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-zip", action="store_true", help="Only create the folder under dist/")
    args = parser.parse_args()
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    build_gpu_models(make_zip=not args.no_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
