const tableBody = document.querySelector("#peopleTable tbody");
const searchInput = document.getElementById("searchInput");
const refreshBtn = document.getElementById("refreshBtn");
const debugAccessBtn = document.getElementById("debugAccessBtn");
const manualIssuesList = document.getElementById("manualIssuesList");
const manualIssuesCount = document.getElementById("manualIssuesCount");
const liveStatus = document.getElementById("liveStatus");
const toastContainer = document.getElementById("toastContainer");
const selectAllRows = document.getElementById("selectAllRows");
const rotateCcwBtn = document.getElementById("rotateCcwBtn");
const rotateCwBtn = document.getElementById("rotateCwBtn");
const selectedCountEl = document.getElementById("selectedCount");
const pagePrevBtn = document.getElementById("pagePrevBtn");
const pageNextBtn = document.getElementById("pageNextBtn");
const pageInfo = document.getElementById("pageInfo");
const pageSizeSelect = document.getElementById("pageSizeSelect");

const previewPanel = document.getElementById("cardPreviewPanel");
const previewBackdrop = document.getElementById("cardPreviewBackdrop");
const previewImage = document.getElementById("cardPreviewImage");
const facePreviewImage = document.getElementById("facePreviewImage");
const previewClose = document.getElementById("cardPreviewClose");

const state = {
  people: new Map(),
  peopleById: new Map(),
  lastItems: [],
  manualIssues: [],
  manualIssuesTotal: 0,
  manualIssuesDirty: true,
  manualIssuesLoaded: false,
  manualIssuesFetching: false,
  manualIssuesLimit: 0,
  issueIds: new Set(),
  activeEditor: null,
  selectedIds: new Set(),
  pendingRefresh: false,
  fetching: false,
  cursorTs: null,
  cursorId: null,
  sse: null,
  sseConnected: false,
  hasInitialLoad: false,
  page: 1,
  pageSize: 25,
  total: 0
};

if (pageSizeSelect) {
  const parsed = parseInt(pageSizeSelect.value, 10);
  if (!Number.isNaN(parsed)) {
    state.pageSize = parsed;
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) {
    return CSS.escape(value);
  }
  return String(value || "").replace(/"/g, "\\\"");
}

function isValidNid(value) {
  return /^\d{14}$/.test((value || "").trim());
}

function isTempNid(value) {
  return (value || "").startsWith("TEMP-");
}

function needsManual(person) {
  if (!person) return false;
  const hasName = Boolean((person.full_name || "").trim());
  const hasValidNid = isValidNid(person.national_id || "");
  return !hasName || !hasValidNid;
}

function displayNid(person) {
  if (!person) return "—";
  return isValidNid(person.national_id || "") ? person.national_id : "—";
}

function getRecordId(item) {
  if (!item) return "";
  const value = item.id;
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function updateLiveStatus() {
  if (!liveStatus) return;
  if (state.activeEditor) {
    liveStatus.textContent = "تعديل جارٍ • التحديث مؤجل";
    liveStatus.className = "live-status paused";
    return;
  }
  if (!state.sseConnected) {
    liveStatus.textContent = "غير متصل";
    liveStatus.className = "live-status disconnected";
    return;
  }
  if (state.pendingRefresh) {
    liveStatus.textContent = "تحديثات جديدة في الانتظار";
    liveStatus.className = "live-status paused";
    return;
  }
  liveStatus.textContent = "متصل • تحديث لحظي";
  liveStatus.className = "live-status connected";
}

function updateSelectedCount() {
  if (selectedCountEl) {
    selectedCountEl.textContent = String(state.selectedIds.size);
  }
}

function syncSelection(items) {
  const visibleIds = new Set(items.map(getRecordId).filter(Boolean));
  for (const id of Array.from(state.selectedIds)) {
    if (!visibleIds.has(id)) {
      state.selectedIds.delete(id);
    }
  }
  if (selectAllRows) {
    const allSelected = items.length > 0 && items.every(item => {
      const rid = getRecordId(item);
      return rid && state.selectedIds.has(rid);
    });
    const anySelected = items.some(item => {
      const rid = getRecordId(item);
      return rid && state.selectedIds.has(rid);
    });
    selectAllRows.checked = allSelected;
    selectAllRows.indeterminate = anySelected && !allSelected;
  }
  updateSelectedCount();
}

function applySelectionToDom() {
  const checkboxes = document.querySelectorAll('input[data-action="select-row"]');
  checkboxes.forEach(cb => {
    const rid = (cb.getAttribute("data-id") || "").trim();
    cb.checked = rid && state.selectedIds.has(rid);
  });
  updateSelectedCount();
}

function updateCursor(items) {
  let bestTs = state.cursorTs;
  let bestId = state.cursorId || 0;
  for (const item of items) {
    const ts = item.updated_at || item.created_at;
    const id = item.id || 0;
    if (!ts) continue;
    const tsValue = Date.parse(ts);
    const bestValue = bestTs ? Date.parse(bestTs) : -1;
    if (!bestTs || tsValue > bestValue || (tsValue === bestValue && id > bestId)) {
      bestTs = ts;
      bestId = id;
    }
  }
  state.cursorTs = bestTs;
  state.cursorId = bestId;
}

function updatePagination(total) {
  state.total = typeof total === "number" ? total : 0;
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (state.page > totalPages) {
    state.page = totalPages;
    state.pendingRefresh = true;
  }
  if (state.page < 1) {
    state.page = 1;
  }
  if (pageInfo) {
    pageInfo.textContent = `صفحة ${state.page} من ${totalPages} • ${state.total} سجل`;
  }
  if (pagePrevBtn) {
    pagePrevBtn.disabled = state.page <= 1;
  }
  if (pageNextBtn) {
    pageNextBtn.disabled = state.page >= totalPages;
  }
}

async function fetchPeople({ silent = false } = {}) {
  if (state.fetching) {
    state.pendingRefresh = true;
    updateLiveStatus();
    return;
  }
  state.fetching = true;
  if (!silent) {
    updateLiveStatus();
  }
  const query = searchInput.value.trim();
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  params.set("page", String(state.page));
  params.set("page_size", String(state.pageSize));
  const url = `/api/admin/people?${params.toString()}`;
  try {
    const res = await fetch(url);
    const data = await res.json();
    const items = data.items || [];
    updatePagination(data.total || 0);
    state.lastItems = items;
    state.people = new Map(items.map(item => [(item.national_id || "").trim(), item]));
    state.peopleById = new Map();
    items.forEach(item => {
      const rid = getRecordId(item);
      if (rid) {
        state.peopleById.set(rid, item);
      }
    });
    if (state.activeEditor && !state.people.has(state.activeEditor)) {
      state.activeEditor = null;
    }
    renderTable(items);
    if (state.manualIssuesDirty || !state.manualIssuesLoaded) {
      fetchManualIssues({ silent: true });
    }
    updateCursor(items);
    if (!state.sse) {
      startSse();
    }
    if (!state.hasInitialLoad) {
      state.hasInitialLoad = true;
    }
  } catch (err) {
    console.error(err);
  } finally {
    state.fetching = false;
    if (state.pendingRefresh && !state.activeEditor) {
      state.pendingRefresh = false;
      fetchPeople({ silent: true });
    }
    updateLiveStatus();
  }
}

function renderTable(items) {
  tableBody.innerHTML = "";
  if (!items.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="11">لا توجد نتائج</td>`;
    tableBody.appendChild(row);
    syncSelection([]);
    return;
  }

  syncSelection(items);

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
    const nidValue = (person.national_id || "").trim();
    const rowId = getRecordId(person);
    row.setAttribute("data-nid", nidValue);
    row.setAttribute("data-id", rowId);
    const isSelected = rowId && state.selectedIds.has(rowId);
    const statusBadge = person.blocked
      ? '<span class="badge blocked">محظور</span>'
      : '<span class="badge allowed">مسموح</span>';
    const needsManualEntry = needsManual(person);
    const displayName = escapeHtml(person.full_name || "—");
    const displayNidValue = displayNid(person);
    const displayGate = person.gate_number ?? "—";
    const displayGateValue = escapeHtml(displayGate);
    const manualBadge = needsManualEntry ? '<span class="badge warning">يحتاج إدخال يدوي</span>' : "";

    const photoCell = person.photo_path
      ? `<img src="/person-photos/${escapeAttr(person.photo_path)}" alt="photo" style="width:48px;height:60px;object-fit:cover;border-radius:10px;border:1px solid rgba(255,255,255,0.2);" />`
      : `<div style="width:48px;height:60px;border-radius:10px;border:1px dashed rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:rgba(255,255,255,0.5);">—</div>`;

    const cardCell = person.card_path
      ? `
        <div style="display:flex;align-items:center;gap:10px;">
          <img src="/card-images/${escapeAttr(person.card_path)}" alt="card" style="width:80px;height:52px;object-fit:cover;border-radius:10px;border:1px solid rgba(255,255,255,0.2);" />
          <button class="icon-btn" data-action="view-card" data-card="/card-images/${escapeAttr(person.card_path)}" data-face="${person.photo_path ? `/person-photos/${escapeAttr(person.photo_path)}` : ""}" title="عرض البطاقة">
            ${icons.eye}
          </button>
        </div>
      `
      : `<div style="width:80px;height:52px;border-radius:10px;border:1px dashed rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:rgba(255,255,255,0.5);">—</div>`;

    const manualButton = needsManualEntry
      ? `<button class="btn btn-warning btn-sm" data-action="manual" data-nid="${escapeAttr(nidValue)}">إدخال يدوي</button>`
      : "";

    row.innerHTML = `
      <td>
        <input type="checkbox" data-action="select-row" data-id="${escapeAttr(rowId)}" ${isSelected ? "checked" : ""} />
      </td>
      <td>${photoCell}</td>
      <td>${cardCell}</td>
      <td>
        <div>${displayName}</div>
        ${manualBadge}
      </td>
      <td>${displayNidValue}</td>
      <td>${displayGateValue}</td>
      <td>${statusBadge}</td>
      <td>${escapeHtml(person.block_reason || "—")}</td>
      <td>${person.visits ?? 0}</td>
      <td>${formatDate(person.last_seen_at)}</td>
      <td>
        <div class="action-group">
          ${manualButton}
          <button class="icon-btn" data-action="edit" data-nid="${escapeAttr(nidValue)}" title="تعديل">
            ${icons.edit}
          </button>
          <button class="icon-btn ${person.blocked ? "success" : ""}" data-action="toggle" data-nid="${escapeAttr(nidValue)}" data-blocked="${person.blocked ? "1" : "0"}" title="${person.blocked ? "إلغاء الحظر" : "حظر"}">
            ${person.blocked ? icons.allow : icons.block}
          </button>
          <button class="icon-btn danger" data-action="delete" data-nid="${escapeAttr(nidValue)}" title="حذف">
            ${icons.trash}
          </button>
        </div>
      </td>
    `;
    tableBody.appendChild(row);

    if (state.activeEditor && nidValue === state.activeEditor) {
      const editorRow = document.createElement("tr");
      editorRow.className = "inline-editor-row";
      editorRow.setAttribute("data-editor-for", nidValue);
      const hasValidNid = isValidNid(nidValue);
      const editorNidValue = hasValidNid ? nidValue : "";
      const editorNameValue = person.full_name || "";
      const nidHint = hasValidNid
        ? "اتركه فارغ لو بدون تغيير."
        : "الرقم القومي مطلوب (14 رقم).";
      const previewCardUrl = person.card_path ? `/card-images/${escapeAttr(person.card_path)}` : "";
      const previewFaceUrl = person.photo_path ? `/person-photos/${escapeAttr(person.photo_path)}` : "";
      const previewCard = previewCardUrl
        ? `<img src="${previewCardUrl}" alt="card preview" />`
        : `<div class="inline-card-placeholder">لا توجد صورة بطاقة</div>`;
      editorRow.innerHTML = `
        <td colspan="11">
          <div class="inline-editor">
            <div class="inline-preview">
              <div class="inline-card">
                ${previewCard}
              </div>
              <div class="inline-preview-meta">
                <span>الرقم القومي الحالي: ${escapeHtml(displayNidValue)}</span>
                <span>البوابة: ${escapeHtml(displayGate)}</span>
              </div>
              ${previewCardUrl ? `
                <div class="inline-preview-actions">
                  <button class="btn btn-outline btn-sm" data-action="view-card" data-card="${previewCardUrl}" data-face="${previewFaceUrl}">عرض البطاقة كاملة</button>
                </div>
              ` : ""}
            </div>
            <div class="inline-fields">
              <div>
                <label>الاسم الكامل</label>
                <input class="inline-input" data-field="full_name" type="text" value="${escapeAttr(editorNameValue)}" />
              </div>
              <div>
                <label>الرقم القومي</label>
                <input class="inline-input" data-field="national_id" type="text" value="${escapeAttr(editorNidValue)}" placeholder="14 رقم" />
                <div class="issue-meta">${nidHint}</div>
              </div>
            </div>
            <div class="inline-actions">
              <button class="btn btn-primary btn-sm" data-action="save-edit" data-nid="${escapeAttr(nidValue)}">حفظ</button>
              <button class="btn btn-outline btn-sm" data-action="cancel-edit" data-nid="${escapeAttr(nidValue)}">إلغاء</button>
              <span class="inline-status" data-role="status"></span>
            </div>
          </div>
        </td>
      `;
      tableBody.appendChild(editorRow);
    }
  });
  applySelectionToDom();
}

function buildIssueItems(items) {
  return (items || []).map(person => ({
    id: (person.national_id || "").trim(),
    name: person.full_name || "بدون اسم",
    nid: isValidNid(person.national_id || "") ? person.national_id : "غير معروف",
    gate: person.gate_number ?? "—",
    photo: person.photo_path || "",
    card: person.card_path || "",
    missingName: !((person.full_name || "").trim()),
    missingNid: !isValidNid(person.national_id || ""),
    updatedAt: person.updated_at || person.created_at || ""
  })).filter(issue => issue.id);
}

function renderIssues(items, total) {
  if (!manualIssuesList) return;
  const issues = buildIssueItems(items);
  state.manualIssues = issues;
  state.manualIssuesTotal = typeof total === "number" ? total : issues.length;
  manualIssuesList.innerHTML = "";
  if (manualIssuesCount) {
    manualIssuesCount.textContent = String(state.manualIssuesTotal);
  }

  if (!issues.length) {
    manualIssuesList.innerHTML = `
      <div class="issue-item">
        <div class="issue-body">
          <div class="issue-title">لا توجد سجلات تحتاج إدخال يدوي حالياً.</div>
          <div class="issue-sub">كل البيانات مكتملة في الوقت الحالي.</div>
        </div>
      </div>
    `;
  } else {
    issues.forEach(issue => {
      const item = document.createElement("div");
      item.className = "issue-item";
      const cardUrl = issue.card ? `/card-images/${escapeAttr(issue.card)}` : "";
      const faceUrl = issue.photo ? `/person-photos/${escapeAttr(issue.photo)}` : "";
      const cardThumb = cardUrl
        ? `<img src="${cardUrl}" alt="card" />`
        : `<div class="issue-thumb-placeholder">لا توجد بطاقة</div>`;
      const faceThumb = faceUrl
        ? `<img src="${faceUrl}" alt="face" />`
        : `<div class="issue-thumb-placeholder">لا توجد صورة</div>`;
      const tags = [];
      if (issue.missingName) tags.push({ label: "الاسم ناقص", tone: "warning" });
      if (issue.missingNid) tags.push({ label: "رقم قومي غير صحيح", tone: "danger" });
      const tagsHtml = tags
        .map(tag => `<span class="issue-tag ${tag.tone}">${escapeHtml(tag.label)}</span>`)
        .join("");
      const updatedLabel = issue.updatedAt ? formatDate(issue.updatedAt) : "—";
      item.innerHTML = `
        <div class="issue-media">
          <div class="issue-card-thumb">${cardThumb}</div>
          <div class="issue-face-thumb">${faceThumb}</div>
        </div>
        <div class="issue-body">
          <div class="issue-title">${escapeHtml(issue.name)}</div>
          <div class="issue-sub">
            الرقم القومي: ${escapeHtml(issue.nid)} • البوابة: ${escapeHtml(issue.gate)}
          </div>
          <div class="issue-sub">آخر تحديث: ${escapeHtml(updatedLabel)}</div>
          <div class="issue-tags">
            ${tagsHtml || `<span class="issue-tag neutral">يحتاج إدخال يدوي</span>`}
          </div>
        </div>
        <div class="issue-actions">
          <button class="btn btn-warning btn-sm" data-action="manual" data-nid="${escapeAttr(issue.id || "")}">فتح الإدخال</button>
          ${cardUrl ? `<button class="btn btn-outline btn-sm" data-action="view-card" data-card="${cardUrl}" data-face="${faceUrl}">عرض البطاقة</button>` : ""}
        </div>
      `;
      manualIssuesList.appendChild(item);
    });
  }

  const nextIssueIds = new Set(issues.map(issue => issue.id));
  if (state.hasInitialLoad) {
    issues.forEach(issue => {
      if (!state.issueIds.has(issue.id)) {
        showIssueToast(issue);
      }
    });
  }
  state.issueIds = nextIssueIds;
}

async function fetchManualIssues({ silent = false } = {}) {
  if (state.manualIssuesFetching) return;
  state.manualIssuesFetching = true;
  try {
    const params = new URLSearchParams();
    params.set("limit", String(state.manualIssuesLimit));
    const url = `/api/admin/issues?${params.toString()}`;
    const res = await fetch(url);
    const data = await res.json();
    renderIssues(data.items || [], data.total || 0);
    state.manualIssuesLoaded = true;
    state.manualIssuesDirty = false;
  } catch (err) {
    console.error(err);
    if (!silent) {
      showToast("تعذر تحميل السجلات اليدوية", "حدث خطأ أثناء جلب السجلات المحتاجة إدخال.");
    }
  } finally {
    state.manualIssuesFetching = false;
  }
}

function showIssueToast(issue) {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `
    <div class="toast-header">
      <div class="toast-title">سجل يحتاج إدخال يدوي</div>
      <button class="toast-close" data-action="close-toast">×</button>
    </div>
    <div class="toast-body">${escapeHtml(issue.name)} • ${escapeHtml(issue.nid)}</div>
    <div class="toast-actions">
      <button class="btn btn-outline btn-sm" data-action="open-manual" data-nid="${escapeAttr(issue.id || "")}">فتح الإدخال</button>
    </div>
  `;
  toastContainer.appendChild(toast);

  const closeBtn = toast.querySelector("[data-action='close-toast']");
  closeBtn?.addEventListener("click", () => toast.remove());

  const openBtn = toast.querySelector("[data-action='open-manual']");
  openBtn?.addEventListener("click", () => {
    openEditorEnsureVisible(issue.id || "");
    toast.remove();
  });

  setTimeout(() => {
    toast.remove();
  }, 10000);
}

function showToast(title, body) {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `
    <div class="toast-header">
      <div class="toast-title">${escapeHtml(title)}</div>
      <button class="toast-close" data-action="close-toast">×</button>
    </div>
    <div class="toast-body">${escapeHtml(body)}</div>
  `;
  toastContainer.appendChild(toast);
  toast.querySelector("[data-action='close-toast']")?.addEventListener("click", () => toast.remove());
  setTimeout(() => {
    toast.remove();
  }, 8000);
}

async function sendReprocess(direction) {
  const ids = Array.from(state.selectedIds);
  const recordIds = ids
    .map(id => parseInt(id, 10))
    .filter(value => Number.isFinite(value));
  if (!recordIds.length) {
    showToast("لا توجد سجلات", "اختر سجلات أولاً لتنفيذ التدوير.");
    return;
  }
  const nationalIds = ids
    .map(id => {
      const person = state.peopleById.get(id);
      return (person?.national_id || "").trim();
    })
    .filter(Boolean);
  try {
    const res = await fetch("/api/admin/reprocess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ record_ids: recordIds, national_ids: nationalIds, direction })
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showToast("تعذر تنفيذ العملية", data.detail || "حدث خطأ أثناء إرسال الطلب.");
      return;
    }
    state.selectedIds.clear();
    showToast("تم إرسال الطلب", `تم جدولة ${ids.length} سجل لإعادة المعالجة.`);
    state.manualIssuesDirty = true;
    fetchPeople({ silent: true });
  } catch (err) {
    console.error(err);
    showToast("تعذر تنفيذ العملية", "حدث خطأ أثناء الاتصال بالخادم.");
  }
}

function openEditor(nid) {
  const safeId = (nid || "").trim();
  if (!safeId) return;
  if (!state.people.has(safeId)) {
    fetchPeople().then(() => openEditor(safeId));
    return;
  }
  state.activeEditor = safeId;
  renderTable(state.lastItems);
  updateLiveStatus();
  scrollToRow(safeId);
}

function openEditorEnsureVisible(nid) {
  if (!nid) return;
  const safeId = (nid || "").trim();
  if (!safeId) return;
  if (!state.people.has(safeId)) {
    searchInput.value = safeId;
    state.page = 1;
    fetchPeople().then(() => openEditor(safeId));
    return;
  }
  openEditor(safeId);
}

function closeEditor() {
  state.activeEditor = null;
  renderTable(state.lastItems);
  if (state.pendingRefresh) {
    state.pendingRefresh = false;
    fetchPeople({ silent: true });
  }
  updateLiveStatus();
}

function scrollToRow(nid) {
  const row = document.querySelector(`tr[data-nid="${cssEscape(nid)}"]`);
  if (row) {
    row.scrollIntoView({ behavior: "smooth", block: "center" });
  }
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
  state.manualIssuesDirty = true;
}

async function saveInlineEdit(nid) {
  const safeId = (nid || "").trim();
  const row = document.querySelector(`tr[data-editor-for="${cssEscape(safeId)}"]`);
  if (!row) return;
  const fullNameInput = row.querySelector("input[data-field='full_name']");
  const nidInput = row.querySelector("input[data-field='national_id']");
  const statusEl = row.querySelector("[data-role='status']");
  if (!fullNameInput || !nidInput || !statusEl) return;

  const current = state.people.get(safeId);
  const fullName = fullNameInput.value.trim();
  const newNid = nidInput.value.trim();
  const requiresNid = !isValidNid(current?.national_id || "");

  statusEl.textContent = "";
  statusEl.classList.remove("error", "success");

  if (!fullName && !((current?.full_name || "").trim())) {
    statusEl.textContent = "برجاء إدخال الاسم الكامل.";
    statusEl.classList.add("error");
    return;
  }
  if (requiresNid && !newNid) {
    statusEl.textContent = "برجاء إدخال رقم قومي صحيح (14 رقم).";
    statusEl.classList.add("error");
    return;
  }
  if (newNid && !isValidNid(newNid)) {
    statusEl.textContent = "الرقم القومي يجب أن يكون 14 رقم.";
    statusEl.classList.add("error");
    return;
  }

  statusEl.textContent = "جارٍ الحفظ...";

  const payload = {
    national_id: safeId,
    full_name: fullName
  };
  if (newNid) {
    payload.new_national_id = newNid;
  }

  try {
    const res = await fetch("/api/admin/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      statusEl.textContent = data.detail || "تعذر حفظ البيانات.";
      statusEl.classList.add("error");
      return;
    }
    statusEl.textContent = "تم الحفظ.";
    statusEl.classList.add("success");
    state.manualIssuesDirty = true;
    closeEditor();
    fetchPeople({ silent: true });
  } catch (err) {
    console.error(err);
    statusEl.textContent = "تعذر حفظ البيانات.";
    statusEl.classList.add("error");
  }
}

function startSse() {
  const params = new URLSearchParams();
  if (state.cursorTs) params.set("cursor_ts", state.cursorTs);
  if (state.cursorId) params.set("cursor_id", String(state.cursorId));
  const url = params.toString() ? `/api/admin/stream?${params}` : "/api/admin/stream";
  const source = new EventSource(url);
  state.sse = source;

  source.addEventListener("open", () => {
    state.sseConnected = true;
    updateLiveStatus();
  });

  source.addEventListener("error", () => {
    state.sseConnected = false;
    updateLiveStatus();
  });

  source.addEventListener("heartbeat", () => {
    state.sseConnected = true;
    updateLiveStatus();
  });

  source.addEventListener("changed", (event) => {
    state.sseConnected = true;
    try {
      const payload = JSON.parse(event.data || "{}");
      if (payload.cursor_ts) state.cursorTs = payload.cursor_ts;
      if (payload.cursor_id) state.cursorId = payload.cursor_id;
    } catch (err) {
      console.error(err);
    }
    state.manualIssuesDirty = true;
    if (state.activeEditor || state.fetching) {
      state.pendingRefresh = true;
      updateLiveStatus();
      return;
    }
    fetchPeople({ silent: true });
  });
}

tableBody.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (target.getAttribute("data-action") !== "select-row") return;
  const rid = (target.getAttribute("data-id") || "").trim();
  if (!rid) return;
  if (target.checked) {
    state.selectedIds.add(rid);
  } else {
    state.selectedIds.delete(rid);
  }
  syncSelection(state.lastItems);
});

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

  const nid = button.getAttribute("data-nid") || "";

  if (action === "manual" || action === "edit") {
    openEditorEnsureVisible(nid);
    return;
  }

  if (action === "save-edit") {
    await saveInlineEdit(nid);
    return;
  }

  if (action === "cancel-edit") {
    closeEditor();
    return;
  }

  if (!nid) return;

  if (action === "toggle") {
    const isBlocked = button.getAttribute("data-blocked") === "1" || button.classList.contains("success");
    await toggleBlock(nid, isBlocked);
  }

  if (action === "delete") {
    await deletePerson(nid);
  }

  await fetchPeople({ silent: true });
});

manualIssuesList?.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const action = button.getAttribute("data-action") || "manual";
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
  openEditorEnsureVisible(nid);
});

searchInput.addEventListener("input", () => {
  clearTimeout(searchInput._timer);
  searchInput._timer = setTimeout(() => {
    state.page = 1;
    fetchPeople({ silent: true });
  }, 400);
});

refreshBtn.addEventListener("click", () => fetchPeople());

selectAllRows?.addEventListener("change", () => {
  if (!selectAllRows) return;
  const checkboxes = document.querySelectorAll('input[data-action="select-row"]');
  state.selectedIds.clear();
  checkboxes.forEach(cb => {
    const rid = (cb.getAttribute("data-id") || "").trim();
    cb.checked = selectAllRows.checked;
    if (selectAllRows.checked && rid) {
      state.selectedIds.add(rid);
    }
  });
  updateSelectedCount();
  selectAllRows.indeterminate = false;
});

rotateCcwBtn?.addEventListener("click", () => sendReprocess("ccw"));
rotateCwBtn?.addEventListener("click", () => sendReprocess("cw"));

pagePrevBtn?.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    fetchPeople({ silent: true });
  }
});

pageNextBtn?.addEventListener("click", () => {
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (state.page < totalPages) {
    state.page += 1;
    fetchPeople({ silent: true });
  }
});

pageSizeSelect?.addEventListener("change", () => {
  const nextSize = parseInt(pageSizeSelect.value, 10);
  if (!Number.isNaN(nextSize)) {
    state.pageSize = nextSize;
    state.page = 1;
    fetchPeople({ silent: true });
  }
});

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
    return new Intl.DateTimeFormat("ar-EG", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Africa/Cairo"
    }).format(parsed);
  } catch (err) {
    return parsed.toLocaleString();
  }
}
