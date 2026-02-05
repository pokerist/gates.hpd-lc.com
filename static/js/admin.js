const tableBody = document.querySelector("#peopleTable tbody");
const searchInput = document.getElementById("searchInput");
const refreshBtn = document.getElementById("refreshBtn");

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
    row.innerHTML = `<td colspan="6">لا توجد نتائج</td>`;
    tableBody.appendChild(row);
    return;
  }

  items.forEach(person => {
    const row = document.createElement("tr");
    const statusBadge = person.blocked
      ? '<span class="badge blocked">محظور</span>'
      : '<span class="badge allowed">مسموح</span>';

    row.innerHTML = `
      <td>${person.full_name || "—"}</td>
      <td>${person.national_id}</td>
      <td>${statusBadge}</td>
      <td>${person.block_reason || "—"}</td>
      <td>${person.visits ?? 0}</td>
      <td>${person.last_seen_at || "—"}</td>
      <td>
        <button class="btn btn-secondary" data-action="toggle" data-nid="${person.national_id}">
          ${person.blocked ? "إلغاء الحظر" : "حظر"}
        </button>
        <button class="btn btn-danger" data-action="delete" data-nid="${person.national_id}">حذف</button>
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
  const nid = button.getAttribute("data-nid");
  if (!action || !nid) return;

  if (action === "toggle") {
    const isBlocked = button.textContent.includes("إلغاء");
    await toggleBlock(nid, isBlocked);
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

fetchPeople();
