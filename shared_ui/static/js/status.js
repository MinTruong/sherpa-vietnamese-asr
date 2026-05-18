(function () {
  const STATUS = {
    waiting: {
      status: "waiting",
      label: "Ch\u1edd x\u1eed l\u00fd",
      terminal: false,
    },
    processing: {
      status: "processing",
      label: "\u0110ang x\u1eed l\u00fd",
      terminal: false,
    },
    completed: {
      status: "completed",
      label: "Ho\u00e0n th\u00e0nh",
      terminal: true,
    },
    error: {
      status: "error",
      label: "L\u1ed7i",
      terminal: true,
    },
    cancelled: {
      status: "cancelled",
      label: "\u0110\u00e3 h\u1ee7y",
      terminal: true,
    },
  };

  const RAW_STATUS_TO_DISPLAY = {
    importing: "waiting",
    source_ready: "waiting",
    waiting: "waiting",
    processing: "processing",
    result_ready: "completed",
    completed: "completed",
    error: "error",
    cancelled: "cancelled",
  };

  function getAsrFileStatus(item) {
    const raw = String(item?.status || "").trim();
    const hasError = Boolean(item?.errorMessage || item?.error_message);
    const rawStatus = hasError ? "error" : (item?.resultStored ? "result_ready" : raw);
    const displayStatus = RAW_STATUS_TO_DISPLAY[rawStatus] || "waiting";
    const meta = STATUS[displayStatus];
    return {
      ...meta,
      rawStatus,
      message: item?.errorMessage || item?.error_message || "",
    };
  }

  window.ASR_FILE_STATUSES = STATUS;
  window.ASR_RAW_STATUS_TO_DISPLAY = RAW_STATUS_TO_DISPLAY;
  window.getAsrFileStatus = getAsrFileStatus;
})();
