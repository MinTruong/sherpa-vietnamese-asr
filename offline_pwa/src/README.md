# Offline PWA Engine Scaffold

This folder is the planned browser-side implementation surface.

- `app/`: UI state and transcript editing modules.
- `engine/`: audio decode, VAD, ASR RNNT, punctuation, diarization, quality.
- `workers/`: Web Worker and AudioWorklet entry points.

The current baseline serves an installable PWA, model manifest, OPFS model
storage, and same-origin model downloads. Inference ports are added here in
separate phases.

