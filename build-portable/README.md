# Build Portable

Thư mục này chứa script build các gói phát hành Windows cho Sherpa Vietnamese ASR. Base package chạy CPU-only; GPU runtime và model GPU được đóng thành zip riêng để người dùng chỉ tải khi cần.

## Chuẩn bị

```bash
python build-portable/setup_build_env.py
python build-portable/prepare_offline_build.py
```

`prepare_offline_build.py` tải model vào `models/` và kiểm tra SHA256. Trên GitHub Actions, một số model Hugging Face cần `HF_TOKEN`.

## Build base CPU-only

```bash
python build-portable/build_portable.py
python build-portable/build_portable_online.py
```

Output:

```text
dist\sherpa-vietnamese-asr-<version>.zip
dist\sherpa-vietnamese-asr-service-<version>.zip
```

Desktop base bỏ ViBERT FP32 để giảm dung lượng, chỉ giữ ViBERT INT8 cho CPU. Service base giữ thêm ViBERT FP32 vì PWA offline cần file này trong manifest.

## Build GPU packages

```bash
python build-portable/build_gpu_addons.py directml intel-openvino
python build-portable/build_gpu_models.py
```

Output:

```text
dist\gpu-addon-directml-win64-<version>.zip
dist\gpu-addon-intel-openvino-win64-<version>.zip
dist\gpu-models-win64-<version>.zip
```

`gpu-models-win64` hiện chỉ chứa:

```text
models\vibert-capu\vibert-capu.onnx
```

CAM++ GPU graph không ship sẵn. Runtime tự sinh từ model CPU khi calibration cần.

## Cấu trúc giải nén đúng

Người dùng phải giải nén GPU zip vào thư mục gốc của app, tức thư mục chứa `app.py` hoặc `server_launcher.py`.

DirectML:

```text
<thu-muc-goc>\gpu_addons\directml\Lib\site-packages\onnxruntime\
```

Intel OpenVINO:

```text
<thu-muc-goc>\gpu_addons\intel-openvino\Lib\site-packages\onnxruntime\
```

GPU models:

```text
<thu-muc-goc>\models\vibert-capu\vibert-capu.onnx
```

Không tạo thêm lớp thư mục trung gian như `<thu-muc-goc>\gpu-addon-directml-win64-<version>\gpu_addons\...`.

## Release assets

Workflow `.github/workflows/build-portable.yml` publish các asset sau cho tag `v*`:

```text
sherpa-vietnamese-asr-<version>.zip
sherpa-vietnamese-asr-service-<version>.zip
gpu-addon-directml-win64-<version>.zip
gpu-addon-intel-openvino-win64-<version>.zip
gpu-models-win64-<version>.zip
```

CUDA zip không còn được build/publish mặc định. NVIDIA và AMD dùng DirectML; Intel dùng OpenVINO.
