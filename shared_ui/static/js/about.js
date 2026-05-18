(function () {
  const ABOUT_HTML = `
    <div id="about-modal" class="modal" style="display:none">
      <div class="modal-content about-dialog">
        <div class="modal-header">
          <h3>Thông tin</h3>
          <button class="modal-close" type="button" data-about-close>&times;</button>
        </div>
        <div class="modal-body about-body">
          <div class="about-hero">
            <div class="about-app-name">sherpa-vietnamese-asr</div>
            <div class="about-version" id="about-version-text">Phiên bản ...</div>
          </div>

          <div class="about-info-grid">
            <div class="about-info-item">
              <span class="about-info-label">Thiết kế</span>
              <span>Nguyễn Hồng Quân</span>
              <span class="about-info-sub">nhquan.thanhuy@tphcm.gov.vn — 098.558.3555</span>
              <span class="about-info-sub">Phòng Chuyển đổi số - Cơ yếu, VP Thành ủy TP.HCM</span>
            </div>
            <div class="about-info-item">
              <span class="about-info-label">Lập trình</span>
              <span>Claude và những người bạn</span>
            </div>
          </div>

          <div class="about-license">
            Phần mềm sử dụng trong môi trường giáo dục, hành chính công, tổ chức Đảng, đoàn thể. Không sử dụng cho mục đích thương mại.
          </div>

          <details class="about-details">
            <summary>Chức năng</summary>
            <ul>
              <li>Chuyển ghi âm thành văn bản tiếng Việt (offline)</li>
              <li>3 model ASR: Zipformer 30M, 68M, ROVER</li>
              <li>Phân tách người nói: Pyannote Community-1, Senko CAM++</li>
              <li>NaturalTurn: nhận diện lượt nói tự nhiên</li>
              <li>Tự động thêm dấu câu, viết hoa</li>
              <li>Tóm tắt cuộc họp (Gemma 4 E2B)</li>
              <li>Hỗ trợ hotwords (từ khóa tùy chỉnh)</li>
              <li>Đánh giá chất lượng âm thanh (DNSMOS)</li>
              <li>PWA — cài trên mobile/desktop như app native</li>
            </ul>
          </details>

          <details class="about-details">
            <summary>Công nghệ</summary>
            <ul>
              <li><b>ASR:</b> Sherpa-ONNX, Zipformer RNN-T (30M + 68M)</li>
              <li><b>Diarization:</b> Pyannote Community-1 + Senko CAM++ (Pure ONNX Runtime)</li>
              <li><b>Dấu câu:</b> ViBERT-capu (ONNX)</li>
              <li><b>VAD:</b> Pyannote Segmentation (ONNX)</li>
              <li><b>Summarizer:</b> Gemma 4 E2B (GGUF, llama-cpp-python)</li>
              <li><b>Resampling:</b> SoXR VHQ</li>
              <li><b>Web:</b> FastAPI, WebSocket, SQLite</li>
            </ul>
          </details>
        </div>
        <div class="modal-footer about-footer">
          <button class="btn" type="button" data-about-close>Đóng</button>
        </div>
      </div>
    </div>`;

  function ensureAboutDialog() {
    let modal = document.getElementById("about-modal");
    if (!modal) {
      document.body.insertAdjacentHTML("beforeend", ABOUT_HTML);
      modal = document.getElementById("about-modal");
    }
    modal.querySelectorAll("[data-about-close]").forEach((button) => {
      button.onclick = window.hideAboutDialog;
    });
    return modal;
  }

  window.showAboutDialog = function showAboutDialog() {
    const modal = ensureAboutDialog();
    modal.style.display = "flex";
    fetch("/api/version")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        const version = document.getElementById("about-version-text");
        if (version && data?.version) version.textContent = `Phiên bản ${data.version}`;
      })
      .catch(() => {});
  };

  window.hideAboutDialog = function hideAboutDialog() {
    const modal = document.getElementById("about-modal");
    if (modal) modal.style.display = "none";
  };
})();
