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

async function tryGetStream(constraintsList) {
  for (const constraints of constraintsList) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: constraints });
      return stream;
    } catch (err) {
      console.warn("Constraints failed", constraints, err);
    }
  }
  throw new Error("No compatible camera constraints");
}

async function cropBlobToAspect(blob, targetAspect, mime = "image/jpeg", quality = 0.98) {
  try {
    let source;
    if ("createImageBitmap" in window) {
      source = await createImageBitmap(blob);
    } else {
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        const url = URL.createObjectURL(blob);
        img.onload = () => {
          URL.revokeObjectURL(url);
          resolve(img);
        };
        img.onerror = reject;
        img.src = url;
      });
    }

    const iw = source.width;
    const ih = source.height;
    let sw = iw;
    let sh = ih;
    let sx = 0;
    let sy = 0;

    if (iw / ih > targetAspect) {
      sh = ih;
      sw = Math.floor(ih * targetAspect);
      sx = Math.floor((iw - sw) / 2);
    } else {
      sw = iw;
      sh = Math.floor(iw / targetAspect);
      sy = Math.floor((ih - sh) / 2);
    }

    canvas.width = sw;
    canvas.height = sh;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(source, sx, sy, sw, sh, 0, 0, sw, sh);

    if (source.close) {
      source.close();
    }

    return await new Promise(resolve => {
      canvas.toBlob(result => resolve(result || blob), mime, quality);
    });
  } catch (err) {
    console.warn("Crop failed, using original blob.", err);
    return blob;
  }
}

async function startCamera() {
  if (currentStream) {
    currentStream.getTracks().forEach(track => track.stop());
  }
  try {
    const supported = navigator.mediaDevices.getSupportedConstraints
      ? navigator.mediaDevices.getSupportedConstraints()
      : {};

    const facingConstraint = supported.facingMode ? { ideal: facingMode } : facingMode;

    const constraintsList = [
      {
        facingMode: facingConstraint,
        width: { ideal: 1920 },
        height: { ideal: 1080 },
        frameRate: { ideal: 30 },
        resizeMode: supported.resizeMode ? "none" : undefined
      },
      {
        facingMode: facingConstraint,
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 }
      },
      { facingMode: facingConstraint },
      true
    ];

    const cleaned = constraintsList.map(item => {
      if (item === true) return true;
      const copy = { ...item };
      Object.keys(copy).forEach(key => copy[key] === undefined && delete copy[key]);
      return copy;
    });

    currentStream = await tryGetStream(cleaned);
    video.srcObject = currentStream;

    try {
      await video.play();
    } catch (err) {
      console.warn("video.play failed", err);
    }

    const track = currentStream.getVideoTracks()[0];
    if ("ImageCapture" in window && track) {
      imageCapture = new ImageCapture(track);
    } else {
      imageCapture = null;
    }

    if (track && track.getCapabilities && track.applyConstraints) {
      const caps = track.getCapabilities();
      const advanced = [];
      const maxWidth = caps.width?.max || caps.imageWidth?.max;
      const maxHeight = caps.height?.max || caps.imageHeight?.max;
      if (maxWidth && maxHeight) {
        advanced.push({ width: maxWidth, height: maxHeight });
      }
      if (caps.focusMode?.includes("continuous")) {
        advanced.push({ focusMode: "continuous" });
      }
      if (caps.exposureMode?.includes("continuous")) {
        advanced.push({ exposureMode: "continuous" });
      }
      if (caps.whiteBalanceMode?.includes("continuous")) {
        advanced.push({ whiteBalanceMode: "continuous" });
      }
      if (advanced.length) {
        try {
          await track.applyConstraints({ advanced });
        } catch (err) {
          console.warn("applyConstraints failed.", err);
        }
      }
      if (track.getSettings) {
        console.log("[Camera] settings", track.getSettings());
      }
    }
  } catch (err) {
    console.error(err);
    alert("تعذر فتح الكاميرا. تأكد من الصلاحيات.");
  }
}

async function captureFrame() {
  if (imageCapture && imageCapture.takePhoto) {
    try {
      const track = currentStream.getVideoTracks()[0];
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      const imageWidth = caps.imageWidth?.max || caps.width?.max || 1920;
      const imageHeight = caps.imageHeight?.max || caps.height?.max || 1080;
      const blob = await imageCapture.takePhoto({ imageWidth, imageHeight });
      return await cropBlobToAspect(blob, 1.58, "image/jpeg", 0.98);
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
    canvas.toBlob(blob => resolve(blob), "image/jpeg", 0.98);
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
