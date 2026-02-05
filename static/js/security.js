const video = document.getElementById("camera");
const canvas = document.getElementById("captureCanvas");
const captureBtn = document.getElementById("captureBtn");
const switchBtn = document.getElementById("switchCameraBtn");
const fileInput = document.getElementById("fileInput");

const resultPanel = document.getElementById("resultPanel");
const resultName = document.getElementById("resultName");
const resultNid = document.getElementById("resultNid");
const resultStatus = document.getElementById("resultStatus");
const resultReason = document.getElementById("resultReason");
const resultVisits = document.getElementById("resultVisits");

let currentStream = null;
let facingMode = "environment";
let imageCapture = null;

async function startCamera() {
  if (currentStream) {
    currentStream.getTracks().forEach(track => track.stop());
  }
  try {
    const supported = navigator.mediaDevices.getSupportedConstraints
      ? navigator.mediaDevices.getSupportedConstraints()
      : {};

    const videoConstraints = {
      facingMode,
      width: { ideal: 1920 },
      height: { ideal: 1080 },
      aspectRatio: { ideal: 1.7777777778 }
    };

    if (supported.focusMode || supported.exposureMode || supported.whiteBalanceMode) {
      videoConstraints.advanced = [
        supported.focusMode ? { focusMode: "continuous" } : {},
        supported.exposureMode ? { exposureMode: "continuous" } : {},
        supported.whiteBalanceMode ? { whiteBalanceMode: "continuous" } : {}
      ];
    }

    currentStream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints });
    video.srcObject = currentStream;

    const track = currentStream.getVideoTracks()[0];
    if ("ImageCapture" in window && track) {
      imageCapture = new ImageCapture(track);
    } else {
      imageCapture = null;
    }
  } catch (err) {
    console.error(err);
    alert("تعذر فتح الكاميرا. تأكد من الصلاحيات.");
  }
}

function captureFrame() {
  if (imageCapture && imageCapture.takePhoto) {
    try {
      const track = currentStream.getVideoTracks()[0];
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      const imageWidth = caps.imageWidth?.max || caps.width?.max || 1920;
      const imageHeight = caps.imageHeight?.max || caps.height?.max || 1080;
      const blob = await imageCapture.takePhoto({ imageWidth, imageHeight });
      return blob;
    } catch (err) {
      console.warn("ImageCapture failed, fallback to canvas.", err);
    }
  }

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
    canvas.toBlob(blob => resolve(blob), "image/jpeg", 0.95);
  });
}

async function sendImage(blob) {
  if (!blob) return;
  setResultLoading();
  const form = new FormData();
  form.append("image", blob, "capture.jpg");

  try {
    const res = await fetch("/api/scan", { method: "POST", body: form });
    const data = await res.json();
    renderResult(data);
  } catch (err) {
    console.error(err);
    renderResult({ status: "error", message: "تعذر الاتصال بالخادم" });
  }
}

function setResultLoading() {
  resultPanel.className = "result-panel";
  resultPanel.querySelector(".result-title").textContent = "جاري المعالجة...";
  resultName.textContent = "...";
  resultNid.textContent = "...";
  resultStatus.textContent = "...";
  resultReason.textContent = "...";
  resultVisits.textContent = "...";
}

function renderResult(data) {
  resultPanel.className = "result-panel";

  if (data.status === "blocked") {
    resultPanel.classList.add("blocked");
    resultPanel.querySelector(".result-title").textContent = "مرفوض";
    resultStatus.textContent = "محظور";
    resultReason.textContent = data.reason || "غير محدد";
  } else if (data.status === "allowed") {
    resultPanel.classList.add("success");
    resultPanel.querySelector(".result-title").textContent = "مسموح";
    resultStatus.textContent = "مسموح";
    resultReason.textContent = "—";
  } else if (data.status === "new") {
    resultPanel.classList.add("success");
    resultPanel.querySelector(".result-title").textContent = "أول مرة";
    resultStatus.textContent = "تمت الإضافة";
    resultReason.textContent = "—";
  } else {
    resultPanel.classList.add("error");
    resultPanel.querySelector(".result-title").textContent = "خطأ";
    resultStatus.textContent = "غير مكتمل";
    resultReason.textContent = data.message || "حدث خطأ";
  }

  const ocr = data.ocr || {};
  const person = data.person || {};

  resultName.textContent = ocr.full_name || person.full_name || "—";
  resultNid.textContent = ocr.national_id || person.national_id || "—";
  resultVisits.textContent = person.visits ?? "—";
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
