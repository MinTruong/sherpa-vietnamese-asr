#!/usr/bin/env python3
"""
asr_cli.py — CLI tool cho Sherpa Vietnamese ASR.

Chạy ASR trên file audio từ command line, không cần GUI hay Web UI.

Usage:
    python asr_cli.py input.mp3 -o output.json
    python asr_cli.py input.mp3 --model 68M --speakers 2 --text-only
    python asr_cli.py input.mp3 --punctuation --no-diarization -v
    python asr_cli.py input.mp3 --rover

Options:
    -o, --output FILE       Ghi kết quả ra file JSON (mặc định: input.asr.json)
    --text-only             Chỉ in text, không JSON
    --model {30M,68M,rover} Chọn model ASR (mặc định: 68M)
    --speakers N            Số lượng người nói (mặc định: auto)
    --punctuation           Bật phục hồi dấu câu (mặc định: bật)
    --no-punctuation        Tắt phục hồi dấu câu
    --diarization           Bật speaker diarization (mặc định: bật)
    --no-diarization        Tắt speaker diarization
    --speaker-model         {pyannote,senko,senko_optimized} (mặc định: senko_optimized)
    --threads N             Số CPU threads (mặc định: số core vật lý)
    --rover                 Bật ROVER mode (chạy 2 model, chậm hơn, chính xác hơn)
    --rms-normalize         Bật RMS normalization
    --wpe                   Bật WPE dereverberation
    -v, --verbose           In chi tiết tiến trình
    -q, --quiet             Im lặng, chỉ in kết quả cuối
"""
import argparse
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def resolve_model_path(model_key: str) -> str:
    models_dir = os.path.join(BASE_DIR, "models")
    model_map = {
        "30M": "zipformer-30m-rnnt-6000h",
        "68M": "sherpa-onnx-zipformer-vi-2025-04-20",
    }
    if model_key in model_map:
        path = os.path.join(models_dir, model_map[model_key])
    else:
        path = model_key if os.path.isabs(model_key) else os.path.join(models_dir, model_key)
    if not os.path.isdir(path):
        print(f"❌ Model not found: {path}", file=sys.stderr)
        print(f"   Available: {', '.join(model_map.keys())}", file=sys.stderr)
        sys.exit(1)
    return path


def build_config(args) -> dict:
    from core.config import DEFAULT_THREADS
    config = {
        "cpu_threads": args.threads or DEFAULT_THREADS,
        "execution_provider": "cpu",
        "stage_execution_providers": {},
        "restore_punctuation": True,
        "bypass_restorer": False,
        "punctuation_confidence": -0.3666666666666667,
        "case_confidence": -0.38888888888888884,
        "speaker_diarization": True,
        "speaker_model": "senko_campp_optimized",
        "num_speakers": -1,
        "diarization_threshold": 0.5,
        "save_ram": False,
        "rover_mode": False,
        "preprocess_rms_normalize": False,
        "bypass_vad": False,
    }
    if args.punctuation is False:
        config["bypass_restorer"] = True
    if args.diarization is False:
        config["speaker_diarization"] = False
    if args.speaker_model:
        config["speaker_model"] = args.speaker_model
    if args.speakers:
        config["num_speakers"] = args.speakers
    if args.rover:
        config["rover_mode"] = True
    if args.rms_normalize:
        config["preprocess_rms_normalize"] = True
    return config


class ProgressPrinter:
    def __init__(self, verbose: bool):
        self.verbose = verbose
        self._last_msg = ""

    def __call__(self, msg: str):
        if not self.verbose:
            return
        if self._last_msg:
            sys.stderr.write("\r" + " " * (len(self._last_msg) + 4) + "\r")
        msg_clean = msg.split("|")[-1] if "|" in msg else msg
        sys.stderr.write(f"⏳ {msg_clean}")
        sys.stderr.flush()
        self._last_msg = f"⏳ {msg_clean}"

    def done(self):
        if self._last_msg and self.verbose:
            sys.stderr.write("\r" + " " * (len(self._last_msg) + 4) + "\r")
            sys.stderr.flush()
        self._last_msg = ""


def main():
    parser = argparse.ArgumentParser(
        description="Sherpa Vietnamese ASR — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="File audio/video đầu vào")
    parser.add_argument("-o", "--output", help="File JSON đầu ra (mặc định: <input>.asr.json)")
    parser.add_argument("--text-only", action="store_true", help="Chỉ in text, không JSON")
    parser.add_argument("--model", default="68M", choices=["30M", "68M"],
                        help="Model ASR (mặc định: 68M)")
    parser.add_argument("--speakers", type=int, default=None, help="Số người nói (mặc định: auto)")
    parser.add_argument("--punctuation", action=argparse.BooleanOptionalAction,
                        default=True, help="Phục hồi dấu câu")
    parser.add_argument("--diarization", action=argparse.BooleanOptionalAction,
                        default=True, help="Speaker diarization")
    parser.add_argument("--speaker-model", choices=["pyannote", "senko", "senko_optimized"],
                        default="senko_optimized")
    parser.add_argument("--threads", type=int, default=None, help="Số CPU threads")
    parser.add_argument("--rover", action="store_true",
                        help="ROVER mode (chạy 2 model: 30M+68M, chính xác hơn)")
    parser.add_argument("--rms-normalize", action="store_true", help="RMS normalization")
    parser.add_argument("--wpe", action="store_true", help="WPE dereverberation")
    parser.add_argument("-v", "--verbose", action="store_true", help="In chi tiết")
    parser.add_argument("-q", "--quiet", action="store_true", help="Im lặng")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"❌ File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # ROVER mode: engine internally loads multiple models, chỉ cần run 1 lần
    model_path = resolve_model_path("68M" if args.rover else args.model)
    config = build_config(args)
    output_path = args.output or (os.path.splitext(args.input)[0] + ".asr.json")

    if not args.quiet:
        print(f"🎤 Sherpa Vietnamese ASR CLI", file=sys.stderr)
        print(f"   Input: {args.input}", file=sys.stderr)
        print(f"   Model: {'ROVER (30M+68M)' if args.rover else args.model}", file=sys.stderr)
        status_diar = "ON" if config.get("speaker_diarization") else "OFF"
        print(f"   Diarization: {status_diar}", file=sys.stderr)
        print(f"   Punctuation: {'ON' if not config.get('bypass_restorer') else 'OFF'}", file=sys.stderr)
        print(file=sys.stderr)

    from core.asr_engine import TranscriberPipeline
    from core.asr_json import serialize_segments

    progress = ProgressPrinter(args.verbose)

    try:
        start = time.time()

        pipeline = TranscriberPipeline(
            file_path=args.input,
            model_path=model_path,
            config=config,
            progress_callback=progress,
        )
        result = pipeline.run()
        progress.done()

        elapsed = time.time() - start
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        text = result.get("text", "").strip()
        if not text and "segments" in result:
            text = " ".join(s.get("text", "") for s in result["segments"]).strip()

        if args.text_only:
            print(text)
        else:
            json_output = serialize_segments(result)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_output)
            if not args.quiet:
                print(f"✅ Done in {minutes}m{seconds}s", file=sys.stderr)
                print(f"📄 Output: {output_path}", file=sys.stderr)
                print(f"📝 Length: {len(text)} chars", file=sys.stderr)
                n_speakers = result.get("has_speaker_diarization", False)
                if n_speakers:
                    print(f"👥 Speakers detected: {n_speakers}", file=sys.stderr)
                print(file=sys.stderr)
            print(text)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
