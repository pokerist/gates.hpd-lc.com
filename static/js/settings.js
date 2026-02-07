const toggle = document.getElementById("docaiGrayscaleToggle");
const faceToggle = document.getElementById("faceMatchToggle");
const thresholdInput = document.getElementById("faceMatchThreshold");
const thresholdValue = document.getElementById("faceMatchThresholdValue");
const maxDimInput = document.getElementById("docaiMaxDim");
const maxDimValue = document.getElementById("docaiMaxDimValue");
const jpegInput = document.getElementById("docaiJpegQuality");
const jpegValue = document.getElementById("docaiJpegQualityValue");
const statusEl = document.getElementById("settingsStatus");

function setStatus(message, type = "") {
  statusEl.textContent = message;
  statusEl.className = `settings-status ${type}`.trim();
}

function normalizeDigits(value) {
  const map = {
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"
  };
  return (value || "").replace(/[٠-٩۰-۹]/g, (ch) => map[ch] || ch);
}

function toNumberSafe(value) {
  const normalized = normalizeDigits(String(value || "").trim());
  const num = Number(normalized);
  return Number.isFinite(num) ? num : null;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function setNumericField(input, labelEl, value, suffix = "") {
  input.value = Number(value).toFixed(input.step && input.step.includes(".") ? 2 : 0);
  labelEl.textContent = `${input.value}${suffix}`;
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    toggle.checked = Boolean(data.docai_grayscale);
    faceToggle.checked = Boolean(data.face_match_enabled);
    const threshold = Number(data.face_match_threshold ?? 0.35);
    setNumericField(thresholdInput, thresholdValue, threshold, "");
    const maxDim = Number(data.docai_max_dim ?? 1600);
    setNumericField(maxDimInput, maxDimValue, maxDim, " px");
    const jpegQuality = Number(data.docai_jpeg_quality ?? 85);
    setNumericField(jpegInput, jpegValue, jpegQuality, "%");
    setStatus("");
  } catch (err) {
    console.error(err);
    setStatus("تعذر تحميل الإعدادات", "error");
  }
}

async function saveSettings() {
  const threshold = toNumberSafe(thresholdInput.value);
  const maxDim = toNumberSafe(maxDimInput.value);
  const jpegQuality = toNumberSafe(jpegInput.value);

  if (threshold === null || maxDim === null || jpegQuality === null) {
    setStatus("قيمة غير صحيحة. استخدم أرقام واضحة.", "error");
    return;
  }

  const safeThreshold = clamp(threshold, 0.2, 0.9);
  const safeMaxDim = clamp(maxDim, 640, 3000);
  const safeJpeg = clamp(jpegQuality, 50, 95);

  setStatus("جاري الحفظ...");
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        docai_grayscale: toggle.checked,
        face_match_enabled: faceToggle.checked,
        face_match_threshold: safeThreshold,
        docai_max_dim: safeMaxDim,
        docai_jpeg_quality: safeJpeg
      })
    });
    const data = await res.json();
    toggle.checked = Boolean(data.docai_grayscale);
    faceToggle.checked = Boolean(data.face_match_enabled);
    const srvThreshold = Number(data.face_match_threshold ?? safeThreshold);
    const srvMaxDim = Number(data.docai_max_dim ?? safeMaxDim);
    const srvJpeg = Number(data.docai_jpeg_quality ?? safeJpeg);
    setNumericField(thresholdInput, thresholdValue, srvThreshold, "");
    setNumericField(maxDimInput, maxDimValue, srvMaxDim, " px");
    setNumericField(jpegInput, jpegValue, srvJpeg, "%");

    const adjusted = (
      Math.abs(srvThreshold - safeThreshold) > 0.001 ||
      Math.abs(srvMaxDim - safeMaxDim) > 1 ||
      Math.abs(srvJpeg - safeJpeg) > 1
    );
    setStatus(adjusted ? "تم الحفظ مع ضبط القيم للحدود المسموحة" : "تم الحفظ", "success");
  } catch (err) {
    console.error(err);
    setStatus("تعذر حفظ الإعدادات", "error");
  }
}

toggle.addEventListener("change", () => {
  saveSettings();
});

faceToggle.addEventListener("change", () => {
  saveSettings();
});

thresholdInput.addEventListener("input", () => {
  const value = toNumberSafe(thresholdInput.value);
  if (value !== null) {
    thresholdValue.textContent = value.toFixed(2);
  }
});

thresholdInput.addEventListener("change", () => {
  saveSettings();
});

maxDimInput.addEventListener("input", () => {
  const value = toNumberSafe(maxDimInput.value);
  if (value !== null) {
    maxDimValue.textContent = `${value.toFixed(0)} px`;
  }
});

maxDimInput.addEventListener("change", () => {
  saveSettings();
});

jpegInput.addEventListener("input", () => {
  const value = toNumberSafe(jpegInput.value);
  if (value !== null) {
    jpegValue.textContent = `${value.toFixed(0)}%`;
  }
});

jpegInput.addEventListener("change", () => {
  saveSettings();
});

loadSettings();
