# KE HOACH TRIEN KHAI WEB SERVICE - SHERPA ASR VN ONLINE

> **Phien ban:** 3.0 - Ban ke hoach day du
> **Ngay cap nhat:** 2026-03-10
> **Muc tieu:** Xay dung ban web service (sherpa-vietnamese-asr) chay tap trung tren server, tai su dung toi da code tu ban desktop (sherpa-vietnamese-asr)

---

## MUC LUC

1. [Tong quan kien truc](#1-tong-quan-kien-truc)
2. [Build & Deploy](#2-build--deploy)
3. [Core module - Tai su dung code](#3-core-module---tai-su-dung-code)
4. [Web Backend (FastAPI)](#4-web-backend-fastapi)
5. [Database (SQLite)](#5-database-sqlite)
6. [Session Management & Anonymous](#6-session-management--anonymous)
7. [Hang doi xu ly (Queue)](#7-hang-doi-xu-ly-queue)
8. [Authentication & Admin](#8-authentication--admin)
9. [HTTPS Self-signed](#9-https-self-signed)
10. [Web UI (Frontend)](#10-web-ui-frontend)
11. [Audio Player & Highlight](#11-audio-player--highlight)
12. [Server Admin GUI (PyQt6)](#12-server-admin-gui-pyqt6)
13. [Windows Service](#13-windows-service)
14. [Cau truc thu muc code](#14-cau-truc-thu-muc-code)
15. [API Endpoints](#15-api-endpoints)
16. [WebSocket Events](#16-websocket-events)
17. [Thu tu trien khai](#17-thu-tu-trien-khai)

---

## 1. TONG QUAN KIEN TRUC

```
+-------------------+         HTTPS (self-signed)        +-------------------+
|   Browser (Web)   | <================================> |   FastAPI Server  |
|   HTML/CSS/JS     |    WebSocket (heartbeat/progress)  |   (Python)        |
+-------------------+                                     +-------------------+
                                                               |
                                                               | Goi truc tiep
                                                               v
                                                         +-------------------+
                                                         |   core/           |
                                                         |   (Pure Python)   |
                                                         |   asr_engine      |
                                                         |   speaker_diariz  |
                                                         |   asr_json        |
                                                         |   config          |
                                                         |   punctuation     |
                                                         +-------------------+
                                                               |
                                                               v
                                                         +-------------------+
      +-------------------+                              |   models/         |
      |  Server Admin GUI |  <--- Quan ly  ---------->   |   (ONNX, PyTorch) |
      |  (PyQt6, Windows) |      FastAPI process         +-------------------+
      +-------------------+                              |   SQLite DB       |
                                                         |   (users/sessions)|
                                                         +-------------------+
```

### Nguyen tac thiet ke
- **Tai su dung code**: core/ la thu vien dung chung, desktop va web deu goi cung cac ham
- **Khong lap code**: Web service KHONG copy logic ASR/diarization, chi goi ham tu core/
- **Don gian**: Vanilla HTML/CSS/JS, khong framework frontend
- **1 file tai 1 thoi diem**: Hang doi xu ly nghiem ngat, toan server chi chay 1 file ASR
- **Anonymous mac dinh**: Ai cung dung duoc, login de luu du lieu vinh vien

---

## 2. BUILD & DEPLOY

### Build Output
```
dist/
+-- sherpa-vietnamese-asr/                    # Ban desktop hien tai (giu nguyen)
|   +-- app.py
|   +-- core/
|   +-- models/                       # Tat ca models ke ca streaming
|   +-- ...
|
+-- sherpa-vietnamese-asr/             # Ban web service moi
    +-- server_launcher.py            # Entry point (khoi dong server)
    +-- server_gui.py                 # GUI quan tri (PyQt6, 7 Tabs)
    +-- core/                         # Copy tu goc
    +-- models/                       # Copy tu goc, LOAI TRU:
    |   |                             #   - zipformer-30m-rnnt-streaming-6000h
    +-- web_service/
    |   +-- __init__.py
    |   +-- server.py                 # FastAPI app chinh
    |   +-- auth.py                   # JWT authentication
    |   +-- database.py               # SQLite models
    |   +-- session_manager.py        # Session lifecycle
    |   +-- queue_manager.py          # Hang doi xu ly
    |   +-- asr_worker.py             # Worker goi core/ pipeline
    |   +-- ssl_utils.py              # Tu sinh HTTPS cert
    |   +-- config.py                 # Cau hinh server
    |   +-- static/                   # Web frontend
    |   |   +-- index.html
    |   |   +-- css/
    |   |   |   +-- style.css
    |   |   +-- js/
    |   |       +-- app.js            # Main app logic
    |   |       +-- upload.js         # Upload + progress
    |   |       +-- player.js         # Audio player + sync
    |   |       +-- websocket.js      # WS heartbeat/progress
    |   |       +-- speaker.js        # Speaker context menu
    |   |       +-- search.js         # Search text
    |   +-- data/                     # Runtime data
    |       +-- uploads/              # Uploaded files (per session)
    |       +-- asr.db                # SQLite database
    |       +-- certs/                # SSL certificates
    |       +-- logs/                 # Log files
    +-- ffmpeg.exe                    # Dong goi kem
    +-- config.ini                    # Cau hinh server
```

### Models duoc copy (loai tru streaming)
```
models/
+-- sherpa-onnx-zipformer-vi-2025-04-20/   # ASR chinh
+-- zipformer-30m-rnnt-6000h/              # ASR nhe
+-- vibert-capu/                           # Them dau
+-- speaker_embedding/                     # Nemo TitaNet
+-- speaker_diarization/                   # Pyannote segmentation
+-- pyannote/                              # Pyannote models
+-- pyannote-onnx/                         # Pyannote ONNX (Altunenes)
+-- dnsmos/                                # Chat luong audio
```

**KHONG copy:** `zipformer-30m-rnnt-streaming-6000h/` (khong can stream tren web)

### FFmpeg
- Dong goi `ffmpeg.exe` vao thu muc goc cua ban online
- Server dung ffmpeg de convert audio (decode tren server, KHONG dung browser)

---

## 3. CORE MODULE - TAI SU DUNG CODE

### Kiem tra phu thuoc PyQt6 trong core/

| File | PyQt6? | Danh gia |
|------|--------|----------|
| `core/asr_engine.py` | KHONG | Dung callback thuan, tai su dung 100% |
| `core/speaker_diarization.py` | KHONG | Dung callback thuan, tai su dung 100% |
| `core/speaker_diarization_pyannote.py` | KHONG | Tai su dung 100% |
| `core/speaker_diarization_onnx_altunenes.py` | KHONG | Tai su dung 100% |
| `core/asr_json.py` | KHONG | Tai su dung 100% |
| `core/config.py` | KHONG | Tai su dung 100% |
| `core/utils.py` | KHONG | Tai su dung 100% |
| `core/punctuation_restorer_improved.py` | KHONG | Tai su dung 100% |
| `core/gec_model.py` | KHONG | Tai su dung 100% |
| `core/audio_analyzer.py` | **CO** | Chi 2 class QThread (DNSMOSDownloader, AnalysisThread) |

### Xu ly audio_analyzer.py
- **Cac method analyze_file(), analyze_microphone(), compute_dnsmos()** la pure Python -> dung duoc
- **DNSMOSDownloader, AnalysisThread** dung QThread -> web service KHONG dung, thay bang threading.Thread hoac goi truc tiep (sync)
- **Khong can sua file goc**, web service chi can goi method pure Python, bo qua 2 class QThread

### API core/ dung trong web service

#### TranscriberPipeline (asr_engine.py)
```python
from core.asr_engine import TranscriberPipeline

pipeline = TranscriberPipeline(
    file_path="path/to/audio.wav",
    model_path="models/zipformer-30m-rnnt-6000h",
    config={
        'cpu_threads': 4,
        'restore_punctuation': True,
        'enable_speaker_diarization': True,
        'speaker_model_id': 'community1_onnx',
        'speaker_num_clusters': 0,        # 0 = tu dong
        'speaker_threshold': 0.7
    },
    progress_callback=lambda msg: ...,    # Nhan "PHASE:*|*|*"
    cancel_check=lambda: is_cancelled     # Return True de huy
)
result = pipeline.run()
# result = {
#     'text': str,
#     'segments': List[dict],
#     'timing': dict,
#     'paragraphs': List[dict],
#     'has_speaker_diarization': bool,
#     'speaker_segments_raw': List[dict]
# }
```

#### Speaker Diarization (speaker_diarization.py)
```python
from core.speaker_diarization import run_diarization

speaker_segments_raw, elapsed, result_segments = run_diarization(
    audio_file="path/to/audio.wav",
    segments=transcribed_segments,
    speaker_model_id="community1_onnx",
    num_speakers=0,
    num_threads=4,
    threshold=0.7,
    progress_callback=lambda msg: ...,
    cancel_check=lambda: is_cancelled
)
```

#### JSON (asr_json.py)
```python
from core.asr_json import serialize_segments, deserialize_segments, load_asr_json, save_asr_json

# Luu
data = serialize_segments(segments, speaker_name_mapping, model_name, 'file', duration_sec)
save_asr_json("output.asr.json", data)

# Doc
data = load_asr_json("output.asr.json")
segments, speaker_mapping, has_speakers = deserialize_segments(data)
```

#### Config (config.py)
```python
from core.config import (
    get_allowed_cpu_count,    # So CPU vat ly
    ALLOWED_THREADS,          # Gia tri da tinh
    BASE_DIR,                 # Thu muc goc
    COLORS,                   # Bang mau (hex) - dung cho ca web
    get_speaker_embedding_models,
    is_diarization_available,
)
```

---

## 4. WEB BACKEND (FastAPI)

### Cong nghe
- **FastAPI** + **uvicorn** (ASGI server)
- **python-multipart** (upload file)
- **python-jose** (JWT token)
- **passlib[bcrypt]** (hash password)
- **aiosqlite** (async SQLite)
- **websockets** (da co trong FastAPI)
- **cryptography** (tu sinh SSL cert)

### Requirements bo sung (them vao requirements.txt cho ban online)
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
aiosqlite>=0.19.0
cryptography>=41.0.0
```

### Cau truc server.py
```python
from fastapi import FastAPI, WebSocket, UploadFile, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

app = FastAPI(title="Sherpa Vietnamese ASR")

# Serve static frontend
app.mount("/static", StaticFiles(directory="web_service/static"), name="static")

# Root -> index.html
@app.get("/")
async def root():
    return FileResponse("web_service/static/index.html")

# API routes (xem muc 15)
# WebSocket routes (xem muc 16)

def start_server(host, port, ssl_certfile, ssl_keyfile, num_threads):
    """Duoc goi tu server_launcher.py hoac server_gui.py"""
    uvicorn.run(
        app,
        host=host,
        port=port,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
```

---

## 5. DATABASE (SQLite)

### File: `web_service/data/asr.db`

### Bang users
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',          -- 'admin' hoac 'user'
    storage_limit_gb REAL DEFAULT 5.0, -- Gioi han luu tru (GB), chinh duoc
    storage_used_bytes INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Bang sessions
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,               -- UUID
    user_id INTEGER NULL,              -- NULL = anonymous
    ip_address TEXT,
    user_agent TEXT,
    is_anonymous BOOLEAN DEFAULT 1,
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expired_at TIMESTAMP NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Bang files
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id INTEGER NULL,              -- NULL = anonymous
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,      -- UUID-based tren server
    file_size_bytes INTEGER,
    duration_sec REAL NULL,
    status TEXT DEFAULT 'uploaded',     -- uploaded/queued/processing/completed/error/cancelled
    asr_result_json TEXT NULL,          -- JSON ket qua ASR (LONGTEXT)
    speaker_names_json TEXT NULL,       -- JSON mapping speaker names
    model_used TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Bang queue
```sql
CREATE TABLE queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    priority INTEGER DEFAULT 0,        -- Timestamp-based, nho hon = uu tien hon
    status TEXT DEFAULT 'waiting',      -- waiting/processing/completed/cancelled/error
    progress_percent INTEGER DEFAULT 0,
    progress_message TEXT DEFAULT '',
    config_json TEXT,                   -- JSON cau hinh ASR cua user
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

---

## 6. SESSION MANAGEMENT & ANONYMOUS

### Co che hoat dong

```
Browser mo web  ──>  Server tao session (UUID)
                     Luu vao cookie + DB
                     |
                     v
                WebSocket ket noi
                Heartbeat moi 30 giay
                     |
         +-----------+-----------+
         |                       |
    [Heartbeat OK]          [Mat ket noi]
    Session active          Dem nguoc 10 phut
         |                       |
         |                  [10 phut het]
         |                       |
         |                  EXPIRED:
         |                  - Kill process dang chay
         |                  - Xoa file upload
         |                  - Xoa record DB (anonymous)
         |
    [User tat browser]
    WebSocket disconnect
         |
    [Anonymous?] ──Yes──> Kill process NGAY LAP TUC
         |                Xoa file + DB record
         |
        [No = Logged in]
         |
    Giu file + data vinh vien
    Chi xoa process dang chay
```

### Chi tiet
- **Anonymous**: Cookie `session_id` (httpOnly, secure). Khi WebSocket disconnect -> doi 5 giay (phong reconnect) -> neu khong reconnect -> kill tat ca process cua session do, xoa files, xoa DB records
- **Logged in**: JWT token trong header. File + ket qua ASR luu vinh vien (toi khi admin xoa hoac vuot storage limit)
- **Heartbeat**: WebSocket ping moi 30s. Server khong nhan heartbeat trong 10 phut -> session expired
- **Timeout co the chinh**: Admin chinh duoc tren GUI hoac config.ini

### Cleanup process (chay dinh ky moi 60 giay)
```python
async def cleanup_expired_sessions():
    """Chay moi 60 giay"""
    now = datetime.utcnow()
    timeout = timedelta(minutes=config.anonymous_timeout_minutes)  # Mac dinh 10 phut

    expired = db.query(sessions).filter(
        sessions.is_anonymous == True,
        sessions.last_heartbeat < now - timeout,
        sessions.expired_at == None
    )

    for session in expired:
        # 1. Kill process dang chay (ASR, diarization, convert...)
        kill_session_processes(session.id)
        # 2. Xoa file upload
        delete_session_files(session.id)
        # 3. Danh dau expired
        session.expired_at = now
```

---

## 7. HANG DOI XU LY (QUEUE)

### Nguyen tac
- **Nghiem ngat 1 file tai 1 thoi diem** tren toan server
- Ai bam "Xu ly" truoc -> vao queue truoc (FIFO theo thoi gian bam)
- Moi user chi duoc 1 file trong queue tai 1 thoi diem
- User dang doi -> hien thi vi tri hang doi, cap nhat realtime qua WebSocket

### Luong xu ly
```
User bam "Xu ly"
     |
     v
[Kiem tra: user da co file trong queue chua?]
     |
    [Co] --> Thong bao "Ban da co 1 file dang cho xu ly"
     |
    [Chua]
     |
     v
[Them vao queue, priority = timestamp hien tai]
     |
     v
[Worker kiem tra: co file nao dang processing?]
     |
    [Co] --> Gui WebSocket: "Ban dang o vi tri #N trong hang doi"
     |
    [Khong]
     |
     v
[Lay file dau tien trong queue (priority thap nhat)]
     |
     v
[Chay pipeline ASR]
  - Convert audio (ffmpeg tren server)
  - Transcription (core/asr_engine.py TranscriberPipeline)
  - Speaker diarization (core/speaker_diarization.py)
  - Them dau (core/punctuation_restorer_improved.py)
     |
     | Progress gui qua WebSocket realtime
     v
[Hoan thanh] --> Luu ket qua vao DB
              --> Gui WebSocket: ket qua JSON
              --> Lay file tiep theo trong queue
```

### Queue Worker (chay trong background thread)
```python
class QueueWorker:
    def __init__(self):
        self.current_file_id = None
        self.current_process_cancelled = False
        self.lock = threading.Lock()

    def cancel_check(self):
        """Duoc truyen vao TranscriberPipeline.cancel_check"""
        return self.current_process_cancelled

    def progress_callback(self, msg):
        """Duoc truyen vao TranscriberPipeline.progress_callback"""
        # Parse "PHASE:Name|Message|Percent"
        # Cap nhat DB + gui WebSocket

    def process_next(self):
        with self.lock:
            if self.current_file_id is not None:
                return  # Dang xu ly file khac

            next_item = db.get_next_queue_item()  # ORDER BY priority ASC
            if next_item is None:
                return  # Queue trong

            self.current_file_id = next_item.file_id
            self.current_process_cancelled = False

        # Chay trong thread rieng
        threading.Thread(target=self._process, args=(next_item,)).start()

    def _process(self, queue_item):
        try:
            # 1. Convert audio neu can (ffmpeg)
            wav_path = convert_to_wav(queue_item.file_path)

            # 2. Goi core pipeline
            pipeline = TranscriberPipeline(
                file_path=wav_path,
                model_path=queue_item.config['model_path'],
                config=queue_item.config,
                progress_callback=self.progress_callback,
                cancel_check=self.cancel_check
            )
            result = pipeline.run()

            # 3. Luu ket qua
            db.save_asr_result(queue_item.file_id, result)

            # 4. Thong bao qua WebSocket
            ws_manager.send_to_session(queue_item.session_id, {
                'type': 'asr_complete',
                'file_id': queue_item.file_id,
                'result': result
            })
        except Exception as e:
            db.set_queue_error(queue_item.file_id, str(e))
        finally:
            self.current_file_id = None
            self.process_next()  # Xu ly file tiep theo

    def cancel(self, file_id):
        """Huy xu ly file"""
        if self.current_file_id == file_id:
            self.current_process_cancelled = True  # Pipeline se check va dung
        else:
            db.remove_from_queue(file_id)  # Xoa khoi hang doi neu chua xu ly
```

---

## 8. AUTHENTICATION & ADMIN

### Admin
- **Duy nhat 1 admin** tren he thong
- Mat khau admin duoc cau hinh:
  1. Lan dau: Nhap tren GUI khi khoi dong (hoac bien moi truong `ADMIN_PASSWORD`)
  2. Sau do: Luu hash trong DB (bang users, role='admin')
  3. Doi mat khau: Tren GUI tab Config hoac tren web (login as admin)
- Admin login tren web co the quan ly users, xem queue, kill session

### User thong thuong
- Admin tao tai khoan tren GUI hoac web admin panel
- User login bang username/password
- JWT token (expire configurable, mac dinh 24h)
- File + ket qua ASR luu vinh vien, gioi han storage (mac dinh 5GB, chinh duoc per user)

### Anonymous
- Khong can login, dung ngay
- Session cookie (UUID)
- Du lieu bi xoa khi tat browser hoac timeout 10 phut
- KHONG the xem lai ket qua cu

### JWT Flow
```
[Login] POST /api/auth/login
  Body: { username, password }
  Response: { token: "eyJ...", user: { username, role } }

[Authenticated request]
  Header: Authorization: Bearer eyJ...

[Refresh] - Khong can, login lai khi het han
```

---

## 9. HTTPS SELF-SIGNED

### Tu sinh certificate lan dau
```python
# web_service/ssl_utils.py
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime, os

def ensure_ssl_certs(cert_dir="web_service/data/certs"):
    cert_file = os.path.join(cert_dir, "server.crt")
    key_file = os.path.join(cert_dir, "server.key")

    if os.path.exists(cert_file) and os.path.exists(key_file):
        return cert_file, key_file

    os.makedirs(cert_dir, exist_ok=True)

    # Tao RSA key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Tao self-signed cert (valid 10 nam)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Sherpa Vietnamese ASR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ASR VN"),
    ])
    cert = (x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )

    # Luu file
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_file, key_file
```

### Cho phep admin upload cert rieng
- Tab Config tren GUI co nut "Upload SSL Certificate"
- Hoac copy file .crt va .key vao thu muc `web_service/data/certs/`
- Server uu tien cert custom, fallback ve self-signed

### Luu y browser
- Self-signed cert se bao "Not Secure" tren browser
- Admin va user can accept cert thu cong (Advanced -> Proceed)
- Voi cert Let's Encrypt hoac corporate CA thi khong co van de nay

---

## 10. WEB UI (FRONTEND)

### Cong nghe: Vanilla HTML/CSS/JS (khong framework)

### Layout tong the - Mo phong tab_file.py cua desktop

```
+------------------------------------------------------------------------+
|  Sherpa Vietnamese ASR                    [Dang nhap] hoac [user01 | X] |
+------------------------------------------------------------------------+
|                                                                        |
|  +-- Cau hinh (co the dong/mo) ------------------------------------+  |
|  |  Model ASR:    [zipformer-30m-rnnt-6000h      v]                |  |
|  |  CPU threads:  [===o========] 4/8                               |  |
|  |  Them dau:     [======o=====] Nhieu (7/10)                      |  |
|  |  Viet hoa:     [=o=========] It (3/10)                          |  |
|  |  [x] Speaker diarization                                       |  |
|  |    So nguoi noi: [Khong ro (tu dong) v]                         |  |
|  |    Model:        [Pyannote ONNX       v]                        |  |
|  |    Nguong:       [=======o==] 0.70                              |  |
|  +----------------------------------------------------------------+  |
|                                                                        |
|  +-- Khu vuc file -------------------------------------------------+  |
|  |                                                                  |  |
|  |   +--------------------------------------------------+          |  |
|  |   |                                                  |          |  |
|  |   |     Keo tha file am thanh vao day               |          |  |
|  |   |     hoac click de chon file                      |          |  |
|  |   |     (mp3, wav, m4a, flac, aac, wma,             |          |  |
|  |   |      ogg, opus, mp4, mkv, avi, mov,             |          |  |
|  |   |      webm, flv, wmv - toi da 500MB)             |          |  |
|  |   |                                                  |          |  |
|  |   +--------------------------------------------------+          |  |
|  |                                                                  |  |
|  |   [Load JSON]  (upload file .asr.json da co truoc do)           |  |
|  |                                                                  |  |
|  |   [Xu ly]  [Ket thuc]  [Luu JSON]  [Copy text]                 |  |
|  |                                                                  |  |
|  |   +-- Progress bar ------------------------------------------+  |  |
|  |   | Dang xu ly... 45%  |  Dang speaker diarization...        |  |  |
|  |   +----------------------------------------------------------+  |  |
|  |                                                                  |  |
|  |   +-- Hang doi -----------------------------------------------+ |  |
|  |   | Ban dang o vi tri #3 trong hang doi.                       | |  |
|  |   | Vui long doi va khong tat trinh duyet.                     | |  |
|  |   +-----------------------------------------------------------+ |  |
|  +----------------------------------------------------------------+  |
|                                                                        |
|  +-- Ket qua ---------------- [Tim kiem: _____ 3/15 < > x ] ------+  |
|  |  [Noi dung]  [Nguoi noi]                                       |  |
|  |                                                                  |  |
|  |  +------- Speaker A: -------------------------------------------+|  |
|  |  || Xin chao, hom nay chung ta se thao luan ve van de kinh te.  ||  |
|  |  || Day la mot chu de rat quan trong trong giai doan hien nay.   ||  |
|  |  +--------------------------------------------------------------+|  |
|  |                                                                  |  |
|  |  +------- Speaker B: -------------------------------------------+|  |
|  |  || Vang, toi dong y voi y kien cua anh. Chung ta can co nhung  ||  |
|  |  || giai phap cu the de giai quyet van de nay.                   ||  |
|  |  +--------------------------------------------------------------+|  |
|  |                                                                  |  |
|  +----------------------------------------------------------------+  |
|                                                                        |
|  +-- Audio Player -------------------------------------------------+  |
|  |  [Play/Pause]  [===o==========================] 01:23 / 05:45  |  |
|  +----------------------------------------------------------------+  |
|                                                                        |
+------------------------------------------------------------------------+
```

### Tinh nang Web UI chi tiet

#### 10.1 Upload file
- Drag-drop zone (HTML5 drag & drop API)
- Click de mo file dialog (`<input type="file">`)
- Progress bar upload (XMLHttpRequest with `upload.onprogress`)
- Gioi han 500MB (kiem tra ca client va server)
- Dinh dang chap nhan: mp3, wav, m4a, flac, aac, wma, ogg, opus, mp4, mkv, avi, mov, webm, flv, wmv
- Sau khi upload xong, server tra ve `file_id`

#### 10.2 Upload JSON
- Nut "Load JSON" rieng biet
- Upload file `.asr.json` sau khi da upload file audio
- Server validate JSON theo cau truc `core/asr_json.py`
- Web hien thi ket qua ASR tu JSON, dong bo voi audio player
- Khong can doi file audio convert xong moi upload JSON

#### 10.3 Cau hinh ASR (collapsible panel)
- Model ASR: dropdown (2 model: zipformer-30m-rnnt-6000h, sherpa-onnx-zipformer-vi-2025-04-20)
- Them dau: slider 1-10 (nhan: Rat it / It / Vua / Nhieu / Rat nhieu)
- Viet hoa: slider 1-10
- Speaker diarization: checkbox
  - So nguoi noi: dropdown (Tu dong, 2-20)
  - Model speaker: dropdown (Pyannote ONNX, Pyannote PyTorch, Titanet)
  - Nguong: slider 0.10-1.50

#### 10.4 Xu ly & Ket thuc
- Nut "Xu ly": Gui request vao queue
- Nut "Ket thuc": Huy xu ly (cancel pipeline), nhuong CPU
- Progress bar: Cap nhat realtime qua WebSocket
- Thong bao hang doi: "Ban dang o vi tri #N", cap nhat khi queue thay doi

#### 10.5 Hien thi ket qua ASR
- 2 tab: "Noi dung" (formatted) va "Nguoi noi" (raw diarization)
- Speaker blocks voi mau sac (giong desktop: accent border, light bg)
- Click vao cau -> seek audio den vi tri tuong ung
- Auto-highlight cau dang phat
- Right-click context menu:
  - "Tach nguoi noi tu cau nay" (split speaker)
  - "Gop voi nguoi noi phia truoc" (merge up)
  - "Gop voi nguoi noi phia sau" (merge down)
  - "Doi ten nguoi noi" (rename speaker)
  - "Sao chep" (copy)

#### 10.6 Tim kiem text
- Search bar goc phai cua tab ket qua
- Tim kiem case-insensitive, ho tro tieng Viet (dau/khong dau)
- Nut Previous/Next de di chuyen giua ket qua
- Hien so luong ket qua (vd: "3/15")
- Highlight ket qua tim kiem trong text
- Debounce 300ms

#### 10.7 Export
- "Luu JSON": Download file .asr.json (cung dinh dang voi desktop)
- "Copy text": Copy plain text vao clipboard
  - Neu co speaker: "Speaker A:\n text1 text2\n\nSpeaker B:\n text3"
  - Neu khong: van ban lien tuc

#### 10.8 Login/Logout
- Goc phai tren: "Dang nhap" link -> modal login form
- Sau login: Hien username + nut logout
- Admin login: Hien them link "Quan ly" de vao admin panel tren web (hoac chi dung GUI)

---

## 11. AUDIO PLAYER & HIGHLIGHT

### Kien truc
- Server convert file upload thanh WAV (dung ffmpeg, chay tren server)
- Web dung HTML5 `<audio>` element de phat WAV/MP3
- WAV file duoc serve qua API: `GET /api/files/{file_id}/audio`
- KHONG luu cache tren browser (stream truc tiep tu server)

### Tinh nang
```javascript
// player.js
class AudioPlayer {
    constructor() {
        this.audio = document.getElementById('audio-player');
        this.segments = [];          // Danh sach segments voi timestamp
        this.currentSegIndex = -1;
    }

    // Click vao cau text -> seek audio
    seekToSegment(segIndex) {
        const seg = this.segments[segIndex];
        this.audio.currentTime = seg.start_time;
        this.audio.play();
        this.highlightSegment(segIndex);
    }

    // Auto-highlight khi audio dang phat
    onTimeUpdate() {
        const currentTime = this.audio.currentTime;
        const segIndex = this.findSegmentAtTime(currentTime);
        if (segIndex !== this.currentSegIndex) {
            this.currentSegIndex = segIndex;
            this.highlightSegment(segIndex);
            this.scrollToSegment(segIndex);
        }
    }

    // Highlight cau dang phat (background color)
    highlightSegment(segIndex) {
        // Xoa highlight cu
        document.querySelectorAll('.seg-highlight').forEach(
            el => el.classList.remove('seg-highlight')
        );
        // Them highlight moi
        const el = document.querySelector(`[data-seg="${segIndex}"]`);
        if (el) {
            el.classList.add('seg-highlight');
        }
    }
}
```

### CSS highlight
```css
.seg-highlight {
    background-color: rgba(0, 123, 255, 0.15);
    border-radius: 3px;
    transition: background-color 0.2s;
}

.speaker-block {
    background: #f8f9fa;
    border-left: 3px solid #007bff;
    padding: 8px 12px;
    margin: 6px 0;
    cursor: pointer;
}

.speaker-label {
    font-weight: bold;
    color: #007bff;
    cursor: pointer;
}
```

---

## 12. SERVER ADMIN GUI (PyQt6)

### Muc dich
- Chay tren may server (Remote Desktop vao de dung)
- Quan ly FastAPI server process
- 7 tab quan tri

### 7 Tab

#### Tab 1: Status (Dashboard)
- Start/Stop/Restart FastAPI server
- Hien trang thai: Running/Stopped, uptime
- Cau hinh nhanh: Port, CPU threads, Bind address
- 3 card thong ke: Sessions dang hoat dong, Queue dang cho, Files da xu ly hom nay

#### Tab 2: Sessions
- Bang sessions: Session ID, IP, User (an danh/ten), Files, Status (active/idle/expired)
- Tim kiem, loc (Tat ca / An danh / Da dang nhap)
- Kill session (1 hoac nhieu), Kill all anonymous, Cleanup expired
- Panel chi tiet: files cua session, thoi gian tao, last heartbeat

#### Tab 3: Queue
- Bang queue: #, File name, User, Status (Waiting/Processing/Completed/Error), Progress, Time
- Progress bar cho file dang xu ly
- Pause/Resume queue, Cancel file, Clear completed
- Panel chi tiet: file dang xu ly, progress %, log

#### Tab 4: Users
- Bang users: Username, Role, Storage used/limit, Files count, Created, Actions
- Tao user moi (form inline)
- Chinh sua: Reset password, Xem files, Vo hieu hoa, Xoa
- Warning khi storage > 80%

#### Tab 5: Config
- Server: Host, Port, CPU threads
- Limits: Max upload (MB), Anonymous timeout (phut), Storage per user (GB), Max sessions
- ASR Defaults: Model, Speaker model, Punctuation confidence, Case confidence, Diarization threshold
- Security: JWT expire, Doi admin password
- Cleanup: Don dep files tam, Xoa session expired
- Nut "Upload SSL Certificate" de dung cert rieng

#### Tab 6: Logs
- Log viewer realtime (doc tu file log + stream moi)
- Mau sac: INFO=xanh, WARNING=vang, ERROR=do
- Filter theo level, Tim kiem trong log
- Auto-scroll (bat/tat), Pause/Resume, Export .txt, Clear man hinh
- Mo thu muc log

#### Tab 7: Service (Windows Service)
- Trang thai: Chua cai / Da cai / Running / Stopped
- Install/Uninstall service (dung pywin32 hoac nssm)
- Start/Stop/Restart
- Auto-start checkbox (khoi dong cung Windows)
- Hien thi CLI commands (sc start/stop/query...)

### Giao tiep GUI <-> Server
```python
# server_gui.py giao tiep voi FastAPI bang:
# 1. Subprocess management (start/stop uvicorn process)
# 2. HTTP requests den localhost:PORT/api/admin/* (cho data)
# 3. Doc file log truc tiep

class ServerProcess:
    def __init__(self):
        self.process = None

    def start(self, host, port):
        self.process = subprocess.Popen([
            sys.executable, "server_launcher.py",
            "--host", host,
            "--port", str(port)
        ])

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=10)

    def is_running(self):
        return self.process and self.process.poll() is None
```

---

## 13. WINDOWS SERVICE

### Cong nghe: pywin32 (hoac nssm lam phuong an du phong)

### Install Service
```python
import win32serviceutil
import win32service
import win32event
import servicemanager

class SherpaASRService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SherpaVietnameseASR"
    _svc_display_name_ = "Sherpa ASR Vietnamese Online Service"
    _svc_description_ = "Web service ASR tieng Viet chay tap trung tren server"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server_process = None

    def SvcDoRun(self):
        # Khoi dong FastAPI server
        self.server_process = subprocess.Popen([...])
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.server_process:
            self.server_process.terminate()
```

### Cac lenh CLI
```
# Cai dat (chay voi quyen Admin)
python service_installer.py install

# Go bo
python service_installer.py remove

# Lenh Windows
sc start SherpaVietnameseASR
sc stop SherpaVietnameseASR
sc query SherpaVietnameseASR
sc config SherpaVietnameseASR start= auto
```

---

## 14. CAU TRUC THU MUC CODE

### Trong source code (truoc khi build)
```
asr-vn/
+-- app.py                              # Desktop entry point (giu nguyen)
+-- tab_file.py                         # Desktop file tab (giu nguyen)
+-- tab_live.py                         # Desktop live tab (giu nguyen)
+-- common.py                           # Desktop shared widgets (giu nguyen)
+-- transcriber.py                      # Desktop transcriber thread (giu nguyen)
+-- core/                               # SHARED - desktop va web dung chung
|   +-- __init__.py
|   +-- asr_engine.py                   # TranscriberPipeline
|   +-- asr_json.py                     # JSON serialize/deserialize
|   +-- speaker_diarization.py          # run_diarization()
|   +-- speaker_diarization_pyannote.py
|   +-- speaker_diarization_onnx_altunenes.py
|   +-- config.py                       # COLORS, models, CPU detection
|   +-- utils.py                        # Vietnamese text utils
|   +-- punctuation_restorer_improved.py
|   +-- gec_model.py
|   +-- audio_analyzer.py              # Co 2 class QThread, web khong dung
|
+-- web_service/                        # MOI - chi cho ban online
|   +-- __init__.py
|   +-- server.py                       # FastAPI app
|   +-- auth.py                         # JWT, password hashing
|   +-- database.py                     # SQLite schema & queries
|   +-- session_manager.py              # Session lifecycle, cleanup
|   +-- queue_manager.py                # FIFO queue, worker
|   +-- asr_worker.py                   # Goi core/ pipeline, progress
|   +-- ssl_utils.py                    # Tu sinh cert
|   +-- config.py                       # Server config (doc config.ini)
|   +-- static/
|       +-- index.html                  # Trang chinh
|       +-- login.html                  # Trang login (hoac modal)
|       +-- admin.html                  # Admin panel (tuy chon, co the chi dung GUI)
|       +-- css/
|       |   +-- style.css               # Dark theme giong desktop
|       +-- js/
|           +-- app.js                  # Main logic, render segments
|           +-- upload.js               # Upload file + progress
|           +-- player.js              # Audio player, seek, highlight
|           +-- websocket.js           # Heartbeat, progress, queue status
|           +-- speaker.js            # Context menu, rename, split, merge
|           +-- search.js             # Tim kiem text
|
+-- server_launcher.py                  # Entry point cho ban online
+-- server_gui.py                       # Admin GUI (PyQt6, 7 tabs)
+-- service_installer.py                # Windows Service installer
+-- models/                             # AI models
+-- build-portable/
|   +-- build_portable.py               # Can sua: build 2 ban
|   +-- prepare_offline_build.py        # Can sua: tuy chon streaming model
+-- config.ini                          # Cau hinh (desktop + server)
+-- requirements.txt                    # Dependencies
+-- requirements-online.txt             # Dependencies bo sung cho ban online
```

---

## 15. API ENDPOINTS

### Public (khong can login)

| Method | Path | Mo ta |
|--------|------|-------|
| `GET` | `/` | Trang chu (index.html) |
| `GET` | `/api/config/models` | Danh sach models ASR + speaker co san |
| `GET` | `/api/config/defaults` | Cau hinh mac dinh (model, thresholds...) |
| `POST` | `/api/session` | Tao session moi (tra ve session_id cookie) |
| `POST` | `/api/upload` | Upload file audio (multipart, max 500MB) |
| `POST` | `/api/upload-json/{file_id}` | Upload JSON ASR cho file da upload |
| `POST` | `/api/process/{file_id}` | Bat dau xu ly ASR (vao queue) |
| `POST` | `/api/cancel/{file_id}` | Huy xu ly / xoa khoi queue |
| `GET` | `/api/files/{file_id}/status` | Trang thai file (uploaded/processing/completed...) |
| `GET` | `/api/files/{file_id}/result` | Ket qua ASR (JSON) |
| `GET` | `/api/files/{file_id}/audio` | Stream file audio de phat tren web |
| `GET` | `/api/queue/position/{file_id}` | Vi tri trong hang doi |
| `POST` | `/api/files/{file_id}/speakers` | Cap nhat speaker names (rename) |
| `POST` | `/api/files/{file_id}/split-speaker` | Tach nguoi noi |
| `POST` | `/api/files/{file_id}/merge-speaker` | Gop nguoi noi |
| `GET` | `/api/files/{file_id}/download-json` | Download file .asr.json |
| `WebSocket` | `/ws` | Heartbeat + realtime updates |

### Auth (can login)

| Method | Path | Mo ta |
|--------|------|-------|
| `POST` | `/api/auth/login` | Dang nhap (tra ve JWT) |
| `POST` | `/api/auth/logout` | Dang xuat |
| `GET` | `/api/auth/me` | Thong tin user hien tai |
| `POST` | `/api/auth/change-password` | Doi mat khau |
| `GET` | `/api/user/files` | Danh sach files cua user (chi logged-in) |
| `DELETE` | `/api/user/files/{file_id}` | Xoa file (chi logged-in, file cua minh) |

### Admin (can login admin)

| Method | Path | Mo ta |
|--------|------|-------|
| `GET` | `/api/admin/sessions` | Danh sach tat ca sessions |
| `DELETE` | `/api/admin/sessions/{session_id}` | Kill session |
| `POST` | `/api/admin/sessions/cleanup` | Don dep expired sessions |
| `GET` | `/api/admin/queue` | Xem hang doi |
| `POST` | `/api/admin/queue/pause` | Tam dung queue |
| `POST` | `/api/admin/queue/resume` | Tiep tuc queue |
| `GET` | `/api/admin/users` | Danh sach users |
| `POST` | `/api/admin/users` | Tao user moi |
| `PUT` | `/api/admin/users/{user_id}` | Sua user (storage limit, active...) |
| `POST` | `/api/admin/users/{user_id}/reset-password` | Reset password |
| `DELETE` | `/api/admin/users/{user_id}` | Xoa user |
| `GET` | `/api/admin/stats` | Thong ke tong quan (cho GUI dashboard) |
| `GET` | `/api/admin/config` | Doc cau hinh server |
| `PUT` | `/api/admin/config` | Cap nhat cau hinh server |

---

## 16. WEBSOCKET EVENTS

### Ket noi
```javascript
// Client
const ws = new WebSocket(`wss://${location.host}/ws?session_id=${sessionId}`);
```

### Client -> Server

| Event | Data | Mo ta |
|-------|------|-------|
| `heartbeat` | `{ type: "heartbeat" }` | Gui moi 30 giay |
| `subscribe_queue` | `{ type: "subscribe_queue", file_id: 123 }` | Theo doi file trong queue |

### Server -> Client

| Event | Data | Mo ta |
|-------|------|-------|
| `heartbeat_ack` | `{ type: "heartbeat_ack" }` | Xac nhan heartbeat |
| `queue_position` | `{ type: "queue_position", file_id: 123, position: 3, total: 5 }` | Vi tri hang doi |
| `processing_started` | `{ type: "processing_started", file_id: 123 }` | Bat dau xu ly |
| `progress` | `{ type: "progress", file_id: 123, percent: 45, phase: "Transcription", message: "Dang chuyen thanh van ban..." }` | Tien do xu ly |
| `asr_complete` | `{ type: "asr_complete", file_id: 123, result: {...} }` | Ket qua ASR day du |
| `asr_error` | `{ type: "asr_error", file_id: 123, error: "..." }` | Loi xu ly |
| `asr_cancelled` | `{ type: "asr_cancelled", file_id: 123 }` | Da huy xu ly |
| `session_expired` | `{ type: "session_expired", reason: "timeout" }` | Session het han |

---

## 17. THU TU TRIEN KHAI

### Phase 1: Backend co ban
1. **web_service/config.py** - Doc/ghi config.ini cho server (port, host, CPU, limits)
2. **web_service/ssl_utils.py** - Tu sinh HTTPS cert
3. **web_service/database.py** - SQLite schema, CRUD operations
4. **web_service/auth.py** - JWT, password hash, middleware
5. **web_service/session_manager.py** - Tao/xoa session, heartbeat tracking, cleanup
6. **web_service/server.py** - FastAPI app co ban (routes, static files, CORS)

### Phase 2: Upload & Queue
7. **web_service/server.py** - API upload file (multipart, validate, luu file)
8. **web_service/queue_manager.py** - FIFO queue, worker thread
9. **web_service/asr_worker.py** - Goi core/asr_engine + core/speaker_diarization
10. **WebSocket** - Heartbeat, progress, queue position

### Phase 3: Web UI
11. **static/index.html** - Layout chinh
12. **static/css/style.css** - Dark theme
13. **static/js/websocket.js** - WS connection, heartbeat
14. **static/js/upload.js** - Drag-drop, upload progress
15. **static/js/app.js** - Render ASR results, config panel
16. **static/js/player.js** - Audio player, seek, highlight
17. **static/js/speaker.js** - Context menu, rename, split, merge
18. **static/js/search.js** - Tim kiem text

### Phase 4: Server GUI
19. **server_gui.py** - 7 tabs (Status, Sessions, Queue, Users, Config, Logs, Service)
20. **server_launcher.py** - Entry point, arg parsing

### Phase 5: Windows Service & Build
21. **service_installer.py** - pywin32 Windows Service
22. **build-portable/** - Sua script build 2 ban (desktop + online)

### Phase 6: Test & Polish
23. Test full flow: upload -> queue -> ASR -> result -> export
24. Test anonymous cleanup (tat browser -> xoa data)
25. Test multi-user queue (nhieu nguoi dung cung luc)
26. Test login/logout, admin functions
27. Performance tuning

---

## GHI CHU KY THUAT QUAN TRONG

### 1. Audio decode tren server
- Tat ca file audio/video duoc convert thanh WAV 16kHz tren server bang ffmpeg
- Browser KHONG can decode audio (khong dung FFmpeg.wasm hay Web Audio API de convert)
- Browser chi phat audio qua HTML5 `<audio>` (stream tu server)
- Tiet kiem tai nguyen client, dam bao tuong thich moi browser

### 2. Khong luu cache tren browser
- Audio stream truc tiep tu server, khong luu local
- Tranh day o dia client

### 3. Thread safety
- Queue worker chay trong background thread, dung threading.Lock
- FastAPI async endpoints, worker thread rieng biet
- cancel_check la thread-safe (chi doc 1 boolean)
- SQLite dung aiosqlite cho async, connection pooling

### 4. So luong ket noi dong thoi
- Thiet ke cho ~10 nguoi dung dong thoi
- WebSocket connection pool
- Uvicorn workers: 1 (vi ASR chay CPU-bound, nhieu workers khong co loi)
- Moi user 1 WebSocket connection

### 5. Speaker operations tren web
- Split/merge/rename speaker thao tac tren ket qua JSON trong DB
- Server xu ly logic (tuong tu desktop nhung qua API)
- Web UI gui request, server tra ve JSON moi, web re-render

### 6. Dong bo config giua GUI va Web
- Ca GUI (PyQt6) va Web (FastAPI) deu doc/ghi cung config.ini
- Khi GUI doi config -> restart FastAPI process de ap dung
- Khi admin doi config qua web API -> ghi config.ini + hot-reload neu co the

---

*Ket thuc tai lieu*
