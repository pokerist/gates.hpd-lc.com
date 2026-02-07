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

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    toggle.checked = Boolean(data.docai_grayscale);
    faceToggle.checked = Boolean(data.face_match_enabled);
    const threshold = Number(data.face_match_threshold ?? 0.35);
    thresholdInput.value = threshold.toFixed(2);
    thresholdValue.textContent = threshold.toFixed(2);
    const maxDim = Number(data.docai_max_dim ?? 1600);
    maxDimInput.value = maxDim.toFixed(0);
    maxDimValue.textContent = maxDim.toFixed(0);
    const jpegQuality = Number(data.docai_jpeg_quality ?? 85);
    jpegInput.value = jpegQuality.toFixed(0);
    jpegValue.textContent = jpegQuality.toFixed(0);
    setStatus("");
  } catch (err) {
    console.error(err);
    setStatus("تعذر تحميل الإعدادات", "error");
  }
}

async function saveSettings() {
  setStatus("جاري الحفظ...");
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        docai_grayscale: toggle.checked,
        face_match_enabled: faceToggle.checked,
        face_match_threshold: Number(thresholdInput.value),
        docai_max_dim: Number(maxDimInput.value),
        docai_jpeg_quality: Number(jpegInput.value)
      })
    });
    const data = await res.json();
    toggle.checked = Boolean(data.docai_grayscale);
    faceToggle.checked = Boolean(data.face_match_enabled);
    const threshold = Number(data.face_match_threshold ?? 0.35);
    thresholdInput.value = threshold.toFixed(2);
    thresholdValue.textContent = threshold.toFixed(2);
    const maxDim = Number(data.docai_max_dim ?? 1600);
    maxDimInput.value = maxDim.toFixed(0);
    maxDimValue.textContent = maxDim.toFixed(0);
    const jpegQuality = Number(data.docai_jpeg_quality ?? 85);
    jpegInput.value = jpegQuality.toFixed(0);
    jpegValue.textContent = jpegQuality.toFixed(0);
    setStatus("تم الحفظ", "success");
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
  thresholdValue.textContent = Number(thresholdInput.value).toFixed(2);
});

thresholdInput.addEventListener("change", () => {
  saveSettings();
});

maxDimInput.addEventListener("input", () => {
  maxDimValue.textContent = Number(maxDimInput.value).toFixed(0);
});

maxDimInput.addEventListener("change", () => {
  saveSettings();
});

jpegInput.addEventListener("input", () => {
  jpegValue.textContent = Number(jpegInput.value).toFixed(0);
});

jpegInput.addEventListener("change", () => {
  saveSettings();
});

loadSettings();
