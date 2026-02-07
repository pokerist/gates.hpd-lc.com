const toggle = document.getElementById("docaiGrayscaleToggle");
const faceToggle = document.getElementById("faceMatchToggle");
const thresholdInput = document.getElementById("faceMatchThreshold");
const thresholdValue = document.getElementById("faceMatchThresholdValue");
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
        face_match_threshold: Number(thresholdInput.value)
      })
    });
    const data = await res.json();
    toggle.checked = Boolean(data.docai_grayscale);
    faceToggle.checked = Boolean(data.face_match_enabled);
    const threshold = Number(data.face_match_threshold ?? 0.35);
    thresholdInput.value = threshold.toFixed(2);
    thresholdValue.textContent = threshold.toFixed(2);
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

loadSettings();
