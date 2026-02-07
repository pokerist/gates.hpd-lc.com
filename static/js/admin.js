const tableBody = document.querySelector("#peopleTable tbody");
const searchInput = document.getElementById("searchInput");
const refreshBtn = document.getElementById("refreshBtn");
const debugAccessBtn = document.getElementById("debugAccessBtn");

async function fetchPeople() {
  const query = searchInput.value.trim();
  const url = query ? `/api/admin/people?q=${encodeURIComponent(query)}` : "/api/admin/people";
  const res = await fetch(url);
  const data = await res.json();
  renderTable(data.items || []);
}

function renderTable(items) {
  tableBody.innerHTML = "";
  if (!items.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="9">لا توجد نتائج</td>`;
    tableBody.appendChild(row);
    return;
  }

  const icons = {
    eye: `
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"></path>
        <circle cx="12" cy="12" r="3.5"></circle>
      </svg>
    `,
    edit: `
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 20h9"></path>
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path>
      </svg>
    `,
    block: `
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="9"></circle>
        <path d="M5 5l14 14"></path>
      </svg>
    `,
    allow: `
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="9"></circle>
        <path d="M8 12l3 3 5-6"></path>
      </svg>
    `,
    trash: `
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18"></path>
        <path d="M8 6V4h8v2"></path>
        <path d="M6 6l1 14h10l1-14"></path>
      </svg>
    `
  };

  items.forEach(person => {
    const row = document.createElement("tr");
    const statusBadge = person.blocked
      ? '<span class="badge blocked">محظور</span>'
      : '<span class="badge allowed">مسموح</span>';
    const needsManual = !person.full_name || (person.national_id || "").startsWith("TEMP-");
    const displayName = person.full_name || "—";
    const displayNid = (person.national_id || "").startsWith("TEMP-") ? "—" : (person.national_id || "—");
    const manualBadge = needsManual ? '<span class="badge warning">يحتاج إدخال يدوي</span>' : "";

    const photoCell = person.photo_path
      ? `<img src="/person-photos/${person.photo_path}" alt="photo" style="width:48px;height:60px;object-fit:cover;border-radius:10px;border:1px solid rgba(255,255,255,0.2);" />`
      : `<div style="width:48px;height:60px;border-radius:10px;border:1px dashed rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:rgba(255,255,255,0.5);">—</div>`;

    const cardCell = person.card_path
      ? `
        <div style="display:flex;align-items:center;gap:10px;">
          <img src="/card-images/${person.card_path}" alt="card" style="width:80px;height:52px;object-fit:cover;border-radius:10px;border:1px solid rgba(255,255,255,0.2);" />
          <button class="icon-btn" data-action="view-card" data-card="/card-images/${person.card_path}" data-face="${person.photo_path ? `/person-photos/${person.photo_path}` : ""}" title="عرض البطاقة">
            ${icons.eye}
          </button>
        </div>
      `
      : `<div style="width:80px;height:52px;border-radius:10px;border:1px dashed rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:rgba(255,255,255,0.5);">—</div>`;

    const safeName = encodeURIComponent(person.full_name || "");

    row.innerHTML = `
      <td>${photoCell}</td>
      <td>${cardCell}</td>
      <td>
        <div>${displayName}</div>
        ${manualBadge}
      </td>
      <td>${displayNid}</td>
      <td>${statusBadge}</td>
      <td>${person.block_reason || "—"}</td>
      <td>${person.visits ?? 0}</td>
      <td>${formatDate(person.last_seen_at)}</td>
      <td>
        <div class="action-group">
          <button class="icon-btn" data-action="edit" data-nid="${person.national_id}" data-name="${safeName}" title="تعديل">
            ${icons.edit}
          </button>
          <button class="icon-btn ${person.blocked ? "success" : ""}" data-action="toggle" data-nid="${person.national_id}" title="${person.blocked ? "إلغاء الحظر" : "حظر"}">
            ${person.blocked ? icons.allow : icons.block}
          </button>
          <button class="icon-btn danger" data-action="delete" data-nid="${person.national_id}" title="حذف">
            ${icons.trash}
          </button>
        </div>
      </td>
    `;
    tableBody.appendChild(row);
  });
}

async function toggleBlock(nationalId, isBlocked) {
  if (isBlocked) {
    await fetch("/api/admin/unblock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ national_id: nationalId })
    });
    return;
  }
  const reason = prompt("سبب الحظر:");
  await fetch("/api/admin/block", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ national_id: nationalId, reason: reason || "غير محدد" })
  });
}

async function deletePerson(nationalId) {
  const confirmDelete = confirm("هل أنت متأكد من الحذف؟");
  if (!confirmDelete) return;
  await fetch(`/api/admin/people/${encodeURIComponent(nationalId)}`, {
    method: "DELETE"
  });
}

tableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const action = button.getAttribute("data-action");
  if (!action) return;

  if (action === "view-card") {
    const url = button.getAttribute("data-card");
    const faceUrl = button.getAttribute("data-face") || "";
    if (url) {
      openCardPreview(url, faceUrl);
    }
    return;
  }

  const nid = button.getAttribute("data-nid");
  if (!nid) return;

  if (action === "toggle") {
    const isBlocked = button.textContent.includes("إلغاء");
    await toggleBlock(nid, isBlocked);
  }

  if (action === "edit") {
    const currentName = decodeURIComponent(button.getAttribute("data-name") || "");
    const newName = prompt("الاسم الكامل:", currentName);
    if (newName === null) return;
    const newNid = prompt("الرقم القومي (اتركه كما هو لو بدون تغيير):", nid);
    if (newNid === null) return;
    await fetch("/api/admin/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        national_id: nid,
        full_name: newName,
        new_national_id: newNid && newNid.trim() ? newNid.trim() : undefined
      })
    });
  }

  if (action === "delete") {
    await deletePerson(nid);
  }

  await fetchPeople();
});

searchInput.addEventListener("input", () => {
  clearTimeout(searchInput._timer);
  searchInput._timer = setTimeout(fetchPeople, 400);
});

refreshBtn.addEventListener("click", fetchPeople);

debugAccessBtn?.addEventListener("click", async () => {
  const pin = prompt("أدخل رمز الدخول للـ Debug");
  if (pin === null) return;
  try {
    const res = await fetch("/api/debug/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pin.trim() })
    });
    if (res.ok) {
      window.location.href = "/debug";
      return;
    }
  } catch (err) {
    console.error(err);
  }
  alert("الرمز غير صحيح");
});

const previewPanel = document.getElementById("cardPreviewPanel");
const previewBackdrop = document.getElementById("cardPreviewBackdrop");
const previewImage = document.getElementById("cardPreviewImage");
const facePreviewImage = document.getElementById("facePreviewImage");
const previewClose = document.getElementById("cardPreviewClose");

function openCardPreview(url, faceUrl) {
  previewImage.src = `${url}?t=${Date.now()}`;
  if (faceUrl) {
    facePreviewImage.src = `${faceUrl}?t=${Date.now()}`;
    facePreviewImage.style.display = "block";
  } else {
    facePreviewImage.src = "";
    facePreviewImage.style.display = "none";
  }
  previewPanel.classList.remove("hidden");
  previewBackdrop.classList.remove("hidden");
  previewPanel.setAttribute("aria-hidden", "false");
}

function closeCardPreview() {
  previewPanel.classList.add("hidden");
  previewBackdrop.classList.add("hidden");
  previewPanel.setAttribute("aria-hidden", "true");
  previewImage.src = "";
  facePreviewImage.src = "";
}

previewClose?.addEventListener("click", closeCardPreview);
previewBackdrop?.addEventListener("click", closeCardPreview);

fetchPeople();

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  try {
    return new Intl.DateTimeFormat("ar-EG", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
  } catch (err) {
    return parsed.toLocaleString();
  }
}
