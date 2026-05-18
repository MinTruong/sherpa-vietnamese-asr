Sherpa-ONNX WebAssembly runtime assets
====================================

Source: k2-fsa/sherpa-onnx WebAssembly VAD+ASR browser build, mirrored from
https://huggingface.co/spaces/k2-fsa/web-assembly-vad-asr-sherpa-onnx-en-whisper-tiny

License: Apache-2.0, matching https://github.com/k2-fsa/sherpa-onnx

The PWA does not use the model .data package from the demo. Its worker overrides
getPreloadedPackage() and mounts ASR model files downloaded through the local
PWA model manifest into Emscripten MEMFS at runtime.
