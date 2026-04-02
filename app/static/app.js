const state = {
  year: null,
  month: null,
  weekStart: window.APP_CONFIG.currentUser?.weekStart || "sunday",
  showWeekNumbers: Boolean(window.APP_CONFIG.currentUser?.showWeekNumbers),
};

function qs(selector) {
  return document.querySelector(selector);
}

function qsa(selector) {
  return [...document.querySelectorAll(selector)];
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function openModal(id) {
  const node = qs(`#${id}`);
  if (node) node.classList.remove("hidden");
}

function closeModal(id) {
  const node = qs(`#${id}`);
  if (node) node.classList.add("hidden");
}

function formatDateRange(startDate, endDate) {
  if (startDate === endDate) return startDate;
  return `${startDate} to ${endDate}`;
}

function renderMiniCalendar(year, month, weekStart) {
  const label = qs("#miniCalendarLabel");
  const grid = qs("#miniCalendarGrid");
  if (!label || !grid) return;
  const firstWeekday = weekStart === "sunday" ? 0 : 1;
  const jsFirstDay = new Date(year, month - 1, 1);
  const offset = (jsFirstDay.getDay() - firstWeekday + 7) % 7;
  const start = new Date(year, month - 1, 1 - offset);
  label.textContent = jsFirstDay.toLocaleString(undefined, { month: "long", year: "numeric" });
  const weekdays = weekStart === "sunday"
    ? ["S", "M", "T", "W", "T", "F", "S"]
    : ["M", "T", "W", "T", "F", "S", "S"];

  const parts = weekdays.map((day) => `<div class="mini-weekday">${day}</div>`);
  for (let index = 0; index < 42; index += 1) {
    const current = new Date(start);
    current.setDate(start.getDate() + index);
    const currentIso = current.toISOString().slice(0, 10);
    const classes = ["mini-day"];
    if (current.getMonth() !== month - 1) classes.push("other-month");
    if (currentIso === new Date().toISOString().slice(0, 10)) classes.push("today");
    parts.push(`<button type="button" class="${classes.join(" ")}" data-mini-date="${currentIso}">${current.getDate()}</button>`);
  }
  grid.innerHTML = `<div class="mini-grid">${parts.join("")}</div>`;
}

function renderCalendar(data) {
  const mount = qs("#calendarMount");
  const title = qs("#calendarTitle");
  if (title) title.textContent = `${data.monthName} ${data.year}`;
  renderMiniCalendar(data.year, data.month, data.weekStart);
  if (!mount) return;
  const classes = ["calendar-grid"];
  if (data.showWeekNumbers) classes.push("with-weeks");
  const header = [];
  if (data.showWeekNumbers) header.push('<div class="weekday-label">Week</div>');
  for (const label of data.weekdayLabels) {
    header.push(`<div class="weekday-label">${label}</div>`);
  }
  const body = [];
  for (const week of data.weeks) {
    if (data.showWeekNumbers) body.push(`<div class="week-number">${week.weekNumber}</div>`);
    for (const day of week.days) {
      const classNames = ["day-cell"];
      if (!day.isCurrentMonth) classNames.push("other-month");
      if (day.isToday) classNames.push("today");
      const slots = day.slots
        .map((slot) => `<div class="slot-pill ${slot.occupied ? "occupied" : ""}" title="${slot.name || "Open slot"}">${slot.label || ""}</div>`)
        .join("");
      body.push(`
        <button type="button" class="${classNames.join(" ")}" data-day="${day.date}">
          <div class="day-number">${day.day}</div>
          <div class="slot-list">${slots}</div>
        </button>
      `);
    }
  }
  mount.innerHTML = `<div class="${classes.join(" ")}">${header.join("")}${body.join("")}</div>`;
}

async function loadCalendar() {
  const params = new URLSearchParams({
    year: String(state.year),
    month: String(state.month),
    weekStart: state.weekStart,
    showWeekNumbers: String(state.showWeekNumbers),
  });
  const data = await fetchJson(`/api/calendar?${params.toString()}`);
  renderCalendar(data);
}

async function loadDayDetails(dayIso) {
  const data = await fetchJson(`/api/day/${dayIso}`);
  qs("#dayModalTitle").textContent = `Vacation requests for ${data.date}`;
  const content = qs("#dayModalContent");
  if (!data.requests.length) {
    content.innerHTML = '<p class="empty-state">No requests for this day yet.</p>';
  } else {
    content.innerHTML = data.requests.map((item) => `
      <div class="day-detail-row">
        <div>#${item.rank}</div>
        <div>
          <strong>${item.physician}</strong>
          <div class="subtle">@${item.username} • ${item.startDate} to ${item.endDate}</div>
        </div>
        <div class="status ${item.status}">${item.status}</div>
      </div>
    `).join("");
  }
  openModal("dayModal");
}

async function loadHistory() {
  const list = qs("#historyList");
  if (!list) return;
  const data = await fetchJson("/api/requests");
  if (!data.requests.length) {
    list.innerHTML = '<div class="empty-state">No vacation requests yet.</div>';
    return;
  }
  list.innerHTML = data.requests.map((item) => `
    <article class="history-item">
      <div>
        <strong>${formatDateRange(item.startDate, item.endDate)}</strong>
        <div class="subtle">Requested ${item.createdAt.replace("T", " ")}</div>
      </div>
      <div class="inline-actions">
        <span class="status ${item.status}">${item.status}</span>
        ${item.status !== "withdrawn" ? `<button class="secondary-button" type="button" data-cancel-request="${item.id}">Cancel</button>` : ""}
      </div>
    </article>
  `).join("");
}

async function loadAdminRequests() {
  const list = qs("#adminRequests");
  if (!list) return;
  const data = await fetchJson("/api/admin/requests");
  if (!data.requests.length) {
    list.innerHTML = '<div class="empty-state">No pending or historical requests found.</div>';
    return;
  }
  list.innerHTML = data.requests.map((item) => `
    <article class="admin-request-row">
      <div>
        <strong>${item.physician}</strong>
        <div class="subtle">${formatDateRange(item.startDate, item.endDate)}</div>
        <div class="subtle">Requested ${item.createdAt.replace("T", " ")}</div>
      </div>
      <div class="inline-actions">
        <span class="status ${item.status}">${item.status}</span>
        ${item.status !== "withdrawn" ? `<button class="secondary-button" type="button" data-admin-status="${item.id}" data-status-value="confirmed">Confirm</button>` : ""}
        ${item.status !== "withdrawn" ? `<button class="secondary-button" type="button" data-admin-status="${item.id}" data-status-value="unavailable">Unavailable</button>` : ""}
      </div>
    </article>
  `).join("");
}

async function loadAdminUsers() {
  const list = qs("#adminUsers");
  if (!list) return;
  const data = await fetchJson("/api/admin/users");
  list.innerHTML = data.users.map((user) => `
    <article class="admin-user-row">
      <div>
        <strong>${user.fullName}</strong>
        <div class="subtle">@${user.username} • ${user.email} • ${user.role}</div>
      </div>
      <div class="inline-actions">
        <span class="status ${user.isActive ? "confirmed" : "unavailable"}">${user.isActive ? "active" : "inactive"}</span>
        <button class="secondary-button" type="button" data-edit-user='${JSON.stringify(user).replace(/'/g, "&#39;")}'>Edit</button>
        <button class="secondary-button" type="button" data-toggle-user="${user.id}">${user.isActive ? "Disable" : "Enable"}</button>
        <button class="secondary-button danger-button" type="button" data-delete-user="${user.id}">Delete</button>
      </div>
    </article>
  `).join("");
}

function attachGlobalEvents() {
  qsa("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.dataset.closeModal));
  });

  qs("#settingsButton")?.addEventListener("click", () => openModal("settingsPanel"));

  qs("#openRequestModal")?.addEventListener("click", () => {
    if (!window.APP_CONFIG.currentUser) {
      window.location.href = "/login";
      return;
    }
    openModal("requestModal");
  });

  qs("#prevMonth")?.addEventListener("click", async () => {
    state.month -= 1;
    if (state.month === 0) {
      state.month = 12;
      state.year -= 1;
    }
    await loadCalendar();
  });

  qs("#nextMonth")?.addEventListener("click", async () => {
    state.month += 1;
    if (state.month === 13) {
      state.month = 1;
      state.year += 1;
    }
    await loadCalendar();
  });

  qs("#todayButton")?.addEventListener("click", async () => {
    const today = new Date();
    state.year = today.getFullYear();
    state.month = today.getMonth() + 1;
    await loadCalendar();
  });

  qs("#miniPrev")?.addEventListener("click", async () => {
    state.month -= 1;
    if (state.month === 0) {
      state.month = 12;
      state.year -= 1;
    }
    await loadCalendar();
  });

  qs("#miniNext")?.addEventListener("click", async () => {
    state.month += 1;
    if (state.month === 13) {
      state.month = 1;
      state.year += 1;
    }
    await loadCalendar();
  });

  qs("#miniPrevYear")?.addEventListener("click", async () => {
    state.year -= 1;
    await loadCalendar();
  });

  qs("#miniNextYear")?.addEventListener("click", async () => {
    state.year += 1;
    await loadCalendar();
  });

  qsa("[data-admin-panel-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.adminPanelButton;
      qsa("[data-admin-panel-button]").forEach((node) => node.classList.toggle("active", node === button));
      qsa("[data-admin-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.adminPanel === target);
      });
    });
  });

  document.body.addEventListener("click", async (event) => {
    const dayButton = event.target.closest("[data-day]");
    if (dayButton) {
      await loadDayDetails(dayButton.dataset.day);
      return;
    }
    const miniButton = event.target.closest("[data-mini-date]");
    if (miniButton) {
      await loadDayDetails(miniButton.dataset.miniDate);
      return;
    }
    const cancelButton = event.target.closest("[data-cancel-request]");
    if (cancelButton) {
      await fetchJson(`/api/requests/${cancelButton.dataset.cancelRequest}/cancel`, { method: "POST" });
      await Promise.all([loadHistory(), loadCalendar()]);
      return;
    }
    const adminStatusButton = event.target.closest("[data-admin-status]");
    if (adminStatusButton) {
      const formData = new FormData();
      formData.append("status", adminStatusButton.dataset.statusValue);
      await fetchJson(`/api/admin/requests/${adminStatusButton.dataset.adminStatus}/status`, { method: "POST", body: formData });
      await Promise.all([loadAdminRequests(), loadCalendar()]);
      return;
    }
    const toggleUserButton = event.target.closest("[data-toggle-user]");
    if (toggleUserButton) {
      await fetchJson(`/api/admin/users/${toggleUserButton.dataset.toggleUser}/toggle`, { method: "POST" });
      await loadAdminUsers();
      return;
    }
    const deleteUserButton = event.target.closest("[data-delete-user]");
    if (deleteUserButton) {
      const confirmed = window.confirm("Delete this user account? Historical calendar entries will stay visible.");
      if (!confirmed) return;
      await fetchJson(`/api/admin/users/${deleteUserButton.dataset.deleteUser}/delete`, { method: "POST" });
      await loadAdminUsers();
      return;
    }
    const editUserButton = event.target.closest("[data-edit-user]");
    if (editUserButton) {
      const user = JSON.parse(editUserButton.dataset.editUser);
      const fullName = window.prompt("Full name", user.fullName);
      if (!fullName) return;
      const username = window.prompt("Username", user.username);
      if (!username) return;
      const email = window.prompt("Email", user.email);
      if (!email) return;
      const role = window.prompt("Role (physician or admin)", user.role);
      if (!role) return;
      const password = window.prompt("New password (leave blank to keep current)", "");
      const formData = new FormData();
      formData.append("full_name", fullName);
      formData.append("username", username);
      formData.append("email", email);
      formData.append("role", role);
      formData.append("password", password || "");
      await fetchJson(`/api/admin/users/${user.id}`, { method: "POST", body: formData });
      await loadAdminUsers();
    }
  });

  qs("#requestForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    await fetchJson("/api/requests", { method: "POST", body: formData });
    event.currentTarget.reset();
    closeModal("requestModal");
    await Promise.all([loadCalendar(), loadHistory().catch(() => {})]);
  });

  qs("#settingsForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!window.APP_CONFIG.currentUser) {
      closeModal("settingsPanel");
      return;
    }
    const formData = new FormData(event.currentTarget);
    formData.set("show_week_numbers", formData.get("show_week_numbers") ? "true" : "false");
    state.weekStart = formData.get("week_start");
    state.showWeekNumbers = formData.get("show_week_numbers") === "true";
    await fetchJson("/api/settings", { method: "POST", body: formData });
    closeModal("settingsPanel");
    await loadCalendar();
  });

  qs("#userCreateForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    await fetchJson("/api/admin/users", { method: "POST", body: formData });
    event.currentTarget.reset();
    await loadAdminUsers();
  });
}

async function init() {
  const mount = qs("#calendarMount");
  const today = new Date();
  state.year = today.getFullYear();
  state.month = today.getMonth() + 1;
  if (mount) {
    state.year = Number(mount.dataset.year);
    state.month = Number(mount.dataset.month);
    state.weekStart = mount.dataset.weekStart;
    state.showWeekNumbers = mount.dataset.showWeekNumbers === "true";
  }
  if (mount || qs("#miniCalendarGrid")) await loadCalendar();
  await loadHistory().catch(() => {});
  await loadAdminRequests().catch(() => {});
  await loadAdminUsers().catch(() => {});
  attachGlobalEvents();
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
