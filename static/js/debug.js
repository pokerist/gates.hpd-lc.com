const video = document.getElementById("debugCamera");
const canvas = document.getElementById("debugCanvas");
const captureBtn = document.getElementById("debugCaptureBtn");
const switchBtn = document.getElementById("debugSwitchBtn");
const fileInput = document.getElementById("debugFileInput");
const debugImage = document.getElementById("debugImage");
const debugData = document.getElementById("debugData");

let currentStream = null;
let facingMode = "environment";

async function startCamera() {
  if (currentStream) {
    currentStream.getTracks().forEach(track => track.stop());
  }
  try {
    currentStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode } });
    video.srcObject = currentStream;
  } catch (err) {
    console.error(err);
    alert("تعذر فتح الكاميرا.");
  }
}

function captureFrame() {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) {
    alert("الكاميرا غير جاهزة بعد");
    return null;
  }

  const targetAspect = 1.58;
  let sw = vw;
  let sh = vh;
  let sx = 0;
  let sy = 0;

  if (vw / vh > targetAspect) {
    sh = vh;
    sw = Math.floor(vh * targetAspect);
    sx = Math.floor((vw - sw) / 2);
  } else {
    sw = vw;
    sh = Math.floor(vw / targetAspect);
    sy = Math.floor((vh - sh) / 2);
  }

  canvas.width = sw;
  canvas.height = sh;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);

  return new Promise(resolve => {
    canvas.toBlob(blob => resolve(blob), "image/jpeg", 0.92);
  });
}

async function sendImage(blob) {
  if (!blob) return;
  debugData.innerHTML = "جاري التحليل...";
  const form = new FormData();
  form.append("image", blob, "debug.jpg");

  try {
    const res = await fetch("/api/debug", { method: "POST", body: form });
    const data = await res.json();
    renderDebug(data);
  } catch (err) {
    console.error(err);
    debugData.innerHTML = "حدث خطأ أثناء الاتصال بالخادم";
  }
}

function renderDebug(data) {
  if (data.debug_image_url) {
    debugImage.src = `${data.debug_image_url}?t=${Date.now()}`;
    debugImage.style.display = "block";
  }

  const fields = data.fields || [];
  const easy = data.easyocr || {};
  const tess = data.tesseract || {};
  const final = data.final || {};

  const lines = [];
  lines.push(`<div class="field-item"><strong>النتيجة النهائية - الاسم:</strong> <span>${final.full_name || "—"}</span></div>`);
  lines.push(`<div class="field-item"><strong>النتيجة النهائية - الرقم القومي:</strong> <span>${final.national_id || "—"}</span></div>`);
  lines.push(`<div class="field-item"><strong>EasyOCR - الاسم الخام:</strong> <span>${easy.full_name_raw || "—"}</span></div>`);
  lines.push(`<div class="field-item"><strong>EasyOCR - الرقم الخام:</strong> <span>${easy.national_id_raw || "—"}</span></div>`);
  lines.push(`<div class="field-item"><strong>Tesseract - الاسم الخام:</strong> <span>${tess.full_name_raw || "—"}</span></div>`);
  lines.push(`<div class="field-item"><strong>Tesseract - الرقم الخام:</strong> <span>${tess.national_id_raw || "—"}</span></div>`);

  if (fields.length) {
    lines.push(`<div style="margin-top: 8px; font-weight: 700;">الحقول المكتشفة:</div>`);
    fields.forEach(field => {
      lines.push(`<div class="field-item"><span>${field.label}</span><span>ثقة: ${field.conf.toFixed(2)}</span></div>`);
    });
  }

  debugData.innerHTML = lines.join("");
}

captureBtn.addEventListener("click", async () => {
  const blob = await captureFrame();
  await sendImage(blob);
});

switchBtn.addEventListener("click", async () => {
  facingMode = facingMode === "environment" ? "user" : "environment";
  await startCamera();
});

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  await sendImage(file);
  fileInput.value = "";
});

startCamera();
