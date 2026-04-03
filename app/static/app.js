const state = {
  year: null,
  month: null,
  weekStart: window.APP_CONFIG.currentUser?.weekStart || "sunday",
  showWeekNumbers: Boolean(window.APP_CONFIG.currentUser?.showWeekNumbers),
  session: {
    currentUser: window.APP_CONFIG.currentUser,
    managedPhysicians: window.APP_CONFIG.managedPhysicians || [],
    physicianDirectory: window.APP_CONFIG.physicianDirectory || [],
    rotationYears: window.APP_CONFIG.rotationYears || [],
  },
  editingRequestId: null,
  adminHolidaysYear: new Date().getFullYear(),
  rotationData: null,
  trades: [],
  historyRequests: [],
  game: null,
};

const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a", "Enter"];
let konamiIndex = 0;

function qs(selector) {
  return document.querySelector(selector);
}

function qsa(selector) {
  return [...document.querySelectorAll(selector)];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text || "Request failed" };
  }
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function openModal(id) {
  const node = qs(`#${id}`);
  if (node) {
    node.classList.remove("hidden");
    node.setAttribute("aria-hidden", "false");
  }
}

function closeModal(id) {
  const node = qs(`#${id}`);
  if (node) {
    node.classList.add("hidden");
    node.setAttribute("aria-hidden", "true");
  }
}

function notifyError(error) {
  alert(error.message || String(error));
}

function formatDateRange(startDate, endDate) {
  return startDate === endDate ? startDate : `${startDate} to ${endDate}`;
}

function currentManagedPhysicians() {
  return state.session.managedPhysicians || [];
}

async function refreshSession() {
  const data = await fetchJson("/api/session");
  state.session = {
    currentUser: data.user,
    managedPhysicians: data.managedPhysicians || [],
    physicianDirectory: data.physicianDirectory || [],
    rotationYears: data.rotationYears || [],
  };
  if (state.session.currentUser) {
    state.weekStart = state.session.currentUser.weekStart;
    state.showWeekNumbers = Boolean(state.session.currentUser.showWeekNumbers);
  }
  populatePhysicianSelects();
  populateDelegationSelect();
  populateTradeTargetUsers();
}

function populatePhysicianSelects() {
  const managed = currentManagedPhysicians();
  const selects = [qs("#requestPhysicianSelect"), qs("#assistantPhysicianSelect")].filter(Boolean);
  for (const select of selects) {
    const currentValue = select.value;
    select.innerHTML = managed.map((physician) => `<option value="${physician.id}">${escapeHtml(physician.fullName)}</option>`).join("");
    if (currentValue && managed.some((physician) => String(physician.id) === currentValue)) {
      select.value = currentValue;
    }
  }
}

function populateDelegationSelect() {
  const select = qs("#delegationSelect");
  if (!select) return;
  const userId = state.session.currentUser?.id;
  const options = (state.session.physicianDirectory || [])
    .filter((physician) => physician.id !== userId)
    .map((physician) => `<option value="${physician.id}">${escapeHtml(physician.fullName)}</option>`);
  select.innerHTML = ['<option value="">Select a physician</option>', ...options].join("");
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
  const weekdays = weekStart === "sunday" ? ["S", "M", "T", "W", "T", "F", "S"] : ["M", "T", "W", "T", "F", "S", "S"];
  const parts = weekdays.map((day) => `<div class="mini-weekday">${day}</div>`);
  const today = new Date().toISOString().slice(0, 10);
  for (let index = 0; index < 42; index += 1) {
    const current = new Date(start);
    current.setDate(start.getDate() + index);
    const currentIso = current.toISOString().slice(0, 10);
    const classes = ["mini-day"];
    if (current.getMonth() !== month - 1) classes.push("other-month");
    if (currentIso === today) classes.push("today");
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
      if (day.isHoliday) classNames.push("is-holiday");
      const holidayBadge = day.isHoliday ? `<div class="holiday-pill">${escapeHtml(day.holiday.title)}</div>` : "";
      const slots = day.slots.map((slot) => `<div class="slot-pill ${slot.occupied ? "occupied" : ""}" title="${escapeHtml(slot.name || "Open slot")}">${escapeHtml(slot.label || "")}</div>`).join("");
      body.push(`
        <button type="button" class="${classNames.join(" ")}" data-day="${day.date}">
          <div class="day-number">${day.day}</div>
          ${holidayBadge}
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
  qs("#dayModalTitle").textContent = `Calendar details for ${data.date}`;
  const content = qs("#dayModalContent");
  const parts = [];
  if (data.holiday) {
    parts.push(`
      <div class="detail-card">
        <div>
          <strong>${escapeHtml(data.holiday.title)}</strong>
          <div class="subtle">${escapeHtml(data.holiday.startDate)} to ${escapeHtml(data.holiday.endDate)}</div>
        </div>
        <span class="status pending">Protected holiday</span>
      </div>
    `);
  }
  if (!data.requests.length) {
    parts.push('<p class="empty-state">No physicians are scheduled off for this day.</p>');
  } else {
    parts.push(
      data.requests.map((item) => `
        <div class="detail-card">
          <div>
            <strong>${escapeHtml(item.physician)}</strong>
            <div class="subtle">${escapeHtml(formatDateRange(item.startDate, item.endDate))}</div>
            <div class="subtle">Scheduled by ${escapeHtml(item.requestedBy)}</div>
          </div>
          <span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        </div>
      `).join("")
    );
  }
  content.innerHTML = parts.join("");
  openModal("dayModal");
}

function renderRequestList(target, requests) {
  if (!target) return;
  state.historyRequests = requests;
  if (!requests.length) {
    target.innerHTML = '<div class="empty-state">No vacation entries yet.</div>';
    return;
  }
  target.innerHTML = requests.map((item) => `
    <article class="history-item">
      <div>
        <strong>${escapeHtml(item.physician)}</strong>
        <div class="subtle">${escapeHtml(formatDateRange(item.startDate, item.endDate))}</div>
        <div class="subtle">Created by ${escapeHtml(item.createdBy)}</div>
        ${item.note ? `<div class="subtle">${escapeHtml(item.note)}</div>` : ""}
      </div>
      <div class="inline-actions">
        <span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        <button class="secondary-button" type="button" data-edit-request="${item.id}">Edit</button>
        ${item.status !== "canceled" ? `<button class="secondary-button" type="button" data-cancel-request="${item.id}">Cancel</button>` : ""}
      </div>
    </article>
  `).join("");
}

async function loadHistory() {
  const list = qs("#historyList");
  const adminList = qs("#adminRequests");
  if (!list && !adminList) return;
  const data = await fetchJson("/api/requests");
  renderRequestList(list, data.requests);
  renderRequestList(adminList, data.requests);
}

function renderDelegations(data) {
  const owned = qs("#ownedDelegations");
  const incoming = qs("#incomingDelegations");
  if (owned) {
    owned.innerHTML = data.owned.length
      ? data.owned.map((item) => `
        <article class="delegation-row">
          <div>
            <strong>${escapeHtml(item.delegateName)}</strong>
            <div class="subtle">Added ${escapeHtml(item.createdAt)}</div>
          </div>
          <button class="secondary-button" type="button" data-remove-delegation="${item.id}">Remove</button>
        </article>
      `).join("")
      : '<div class="empty-state">No delegates added yet.</div>';
  }
  if (incoming) {
    incoming.innerHTML = data.incoming.length
      ? data.incoming.map((item) => `
        <article class="delegation-row">
          <div>
            <strong>${escapeHtml(item.ownerName)}</strong>
            <div class="subtle">You may schedule vacation for this physician.</div>
          </div>
        </article>
      `).join("")
      : '<div class="empty-state">No incoming delegations.</div>';
  }
}

async function loadDelegations() {
  if (!qs("#ownedDelegations") && !qs("#incomingDelegations")) return;
  const data = await fetchJson("/api/delegations");
  renderDelegations(data);
}

function flattenRotationGroups(groups) {
  const items = [];
  for (const group of groups || []) {
    for (const holiday of group.holidays || []) {
      for (const assignment of holiday.assignments || []) {
        items.push({
          userId: assignment.userId,
          fullName: assignment.fullName,
          holidayKey: holiday.key,
          holidayTitle: holiday.title,
          category: holiday.category,
        });
      }
    }
  }
  return items;
}

function populateTradeTargetUsers() {
  const select = qs("#tradeTargetUserSelect");
  if (!select || !state.rotationData) return;
  const currentUserId = state.session.currentUser?.id;
  const assignments = flattenRotationGroups(state.rotationData.groups);
  const users = [];
  const seen = new Set();
  for (const item of assignments) {
    if (item.userId === currentUserId || seen.has(item.userId)) continue;
    seen.add(item.userId);
    users.push(item);
  }
  select.innerHTML = ['<option value="">Select physician</option>', ...users.map((item) => `<option value="${item.userId}">${escapeHtml(item.fullName)}</option>`)].join("");
}

function populateTradeHolidayOptions() {
  const myHolidaySelect = qs("#myHolidaySelect");
  const targetUserSelect = qs("#tradeTargetUserSelect");
  const targetHolidaySelect = qs("#tradeTargetHolidaySelect");
  if (!myHolidaySelect || !targetHolidaySelect || !state.rotationData) return;

  const currentMyHoliday = myHolidaySelect.value;
  const currentRequestedHoliday = targetHolidaySelect.value;
  myHolidaySelect.innerHTML = ['<option value="">Select your holiday</option>', ...(state.rotationData.myHolidays || []).map((item) => `<option value="${item.holidayKey}" data-category="${item.category}">${escapeHtml(item.holidayTitle)}</option>`)].join("");
  if ((state.rotationData.myHolidays || []).some((item) => item.holidayKey === currentMyHoliday)) {
    myHolidaySelect.value = currentMyHoliday;
  }

  const selectedHoliday = state.rotationData.myHolidays?.find((item) => item.holidayKey === myHolidaySelect.value);
  const assignments = flattenRotationGroups(state.rotationData.groups);
  const targetUserId = Number(targetUserSelect?.value || 0);
  const targetOptions = assignments.filter((item) => item.userId === targetUserId && (!selectedHoliday || item.category === selectedHoliday.category));
  targetHolidaySelect.innerHTML = ['<option value="">Select requested holiday</option>', ...targetOptions.map((item) => `<option value="${item.holidayKey}">${escapeHtml(item.holidayTitle)}</option>`)].join("");
  if (targetOptions.some((item) => item.holidayKey === currentRequestedHoliday)) {
    targetHolidaySelect.value = currentRequestedHoliday;
  }
}

async function loadRotationData(year) {
  state.rotationData = await fetchJson(`/api/rotation?year=${year}`);
  state.session.rotationYears = state.rotationData.years || [];
  populateTradeTargetUsers();
  populateTradeHolidayOptions();
}

function renderTrades(list, trades) {
  if (!list) return;
  if (!trades.length) {
    list.innerHTML = '<div class="empty-state">No holiday trades found.</div>';
    return;
  }
  const currentUserId = state.session.currentUser?.id;
  list.innerHTML = trades.map((item) => `
    <article class="trade-row">
      <div>
        <strong>${escapeHtml(item.offeredByName)} -> ${escapeHtml(item.offeredToName)}</strong>
        <div class="subtle">${escapeHtml(item.year)}: ${escapeHtml(item.offeredHolidayTitle || item.offeredHolidayKey)} for ${escapeHtml(item.requestedHolidayTitle || item.requestedHolidayKey)}</div>
        ${item.note ? `<div class="subtle">${escapeHtml(item.note)}</div>` : ""}
      </div>
      <div class="inline-actions">
        <span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        ${item.status === "pending" && item.offeredToUserId === currentUserId ? `<button class="secondary-button" type="button" data-trade-action="accept" data-trade-id="${item.id}">Accept</button><button class="secondary-button" type="button" data-trade-action="reject" data-trade-id="${item.id}">Reject</button>` : ""}
      </div>
    </article>
  `).join("");
}

async function loadTrades() {
  const list = qs("#tradeList");
  const adminList = qs("#adminTrades");
  if (!list && !adminList) return;
  const data = await fetchJson("/api/trades");
  state.trades = data.trades;
  renderTrades(list, data.trades);
  renderTrades(adminList, data.trades);
}

function openRequestModalForCreate() {
  if (!state.session.currentUser) {
    window.location.href = "/login";
    return;
  }
  state.editingRequestId = null;
  qs("#requestModalTitle").textContent = "Schedule Vacation";
  qs("#requestForm")?.reset();
  qs("#assistantRequestForm")?.reset();
  qs('#requestForm input[name="request_id"]').value = "";
  qs("#assistantResponse").textContent = "";
  populatePhysicianSelects();
  openModal("requestModal");
}

function openRequestModalForEdit(requestId) {
  const item = state.historyRequests.find((request) => request.id === Number(requestId));
  if (!item) return;
  state.editingRequestId = item.id;
  qs("#requestModalTitle").textContent = `Edit Vacation for ${item.physician}`;
  populatePhysicianSelects();
  qs('#requestForm input[name="request_id"]').value = item.id;
  qs('#requestForm [name="physician_id"]').value = item.physicianId;
  qs('#assistantPhysicianSelect').value = item.physicianId;
  qs('#requestForm [name="start_date"]').value = item.startDate;
  qs('#requestForm [name="end_date"]').value = item.endDate;
  qs('#requestForm [name="request_note"]').value = item.note || "";
  qs("#assistantResponse").textContent = "";
  openModal("requestModal");
}

function renderUsers(users) {
  const list = qs("#adminUsers");
  if (!list) return;
  if (!users.length) {
    list.innerHTML = '<div class="empty-state">No users found.</div>';
    return;
  }
  list.innerHTML = users.map((user) => `
    <article class="admin-user-row">
      <div>
        <strong>${escapeHtml(user.fullName)}</strong>
        <div class="subtle">@${escapeHtml(user.username)} - ${escapeHtml(user.email)}</div>
        <div class="subtle">${escapeHtml(user.role)} - annual VL day limit: ${escapeHtml(user.annualDayLimit)}</div>
      </div>
      <div class="inline-actions">
        <span class="status ${user.isActive ? "active" : "inactive"}">${user.isActive ? "active" : "inactive"}</span>
        <button class="secondary-button" type="button" data-edit-user='${escapeHtml(JSON.stringify(user))}'>Edit</button>
        <button class="secondary-button" type="button" data-toggle-user="${user.id}">${user.isActive ? "Disable" : "Enable"}</button>
        <button class="secondary-button" type="button" data-delete-user="${user.id}">Delete</button>
      </div>
    </article>
  `).join("");
}

async function loadAdminUsers() {
  if (!qs("#adminUsers")) return;
  const data = await fetchJson("/api/admin/users");
  renderUsers(data.users);
}

function openUserModal(user) {
  qs("#userModalTitle").textContent = `Edit ${user.fullName}`;
  qs('#userEditForm [name="user_id"]').value = user.id;
  qs('#userEditForm [name="full_name"]').value = user.fullName;
  qs('#userEditForm [name="username"]').value = user.username;
  qs('#userEditForm [name="email"]').value = user.email;
  qs('#userEditForm [name="role"]').value = user.role;
  qs('#userEditForm [name="annual_day_limit"]').value = user.annualDayLimit;
  qs('#userEditForm [name="password"]').value = "";
  openModal("userModal");
}

function renderHolidays(holidays) {
  const list = qs("#adminHolidays");
  if (!list) return;
  if (!holidays.length) {
    list.innerHTML = '<div class="empty-state">No holidays found for that year.</div>';
    return;
  }
  list.innerHTML = holidays.map((holiday) => `
    <article class="history-item">
      <div>
        <strong>${escapeHtml(holiday.title)}</strong>
        <div class="subtle">${escapeHtml(holiday.startDate)} to ${escapeHtml(holiday.endDate)}</div>
        <div class="subtle">${escapeHtml(holiday.category)} holiday - ${holiday.isLocked ? "locked" : "not locked"}</div>
      </div>
      <div class="inline-actions">
        <button class="secondary-button" type="button" data-edit-holiday='${escapeHtml(JSON.stringify(holiday))}'>Edit</button>
        <button class="secondary-button" type="button" data-delete-holiday="${holiday.id}">Delete</button>
      </div>
    </article>
  `).join("");
}

async function loadAdminHolidays(year = state.adminHolidaysYear) {
  const list = qs("#adminHolidays");
  if (!list) return;
  state.adminHolidaysYear = year;
  const data = await fetchJson(`/api/admin/holidays?year=${year}`);
  renderHolidays(data.holidays);
}

function openHolidayModal(holiday) {
  qs("#holidayModalTitle").textContent = `Edit ${holiday.title}`;
  qs('#holidayEditForm [name="holiday_id"]').value = holiday.id;
  qs('#holidayEditForm [name="title"]').value = holiday.title;
  qs('#holidayEditForm [name="holiday_key"]').value = holiday.holidayKey;
  qs('#holidayEditForm [name="year"]').value = holiday.year;
  qs('#holidayEditForm [name="category"]').value = holiday.category;
  qs('#holidayEditForm [name="start_date"]').value = holiday.startDate;
  qs('#holidayEditForm [name="end_date"]').value = holiday.endDate;
  qs('#holidayEditForm [name="is_locked"]').checked = holiday.isLocked;
  openModal("holidayModal");
}

function renderLogTable(container, columns, rows) {
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">No log entries found.</div>';
    return;
  }
  const header = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
  const body = rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column.key] ?? "")}</td>`).join("")}</tr>`).join("");
  container.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

async function loadAdminLogs() {
  if (!qs("#activityLog") && !qs("#changeLog")) return;
  const data = await fetchJson("/api/admin/logs");
  renderLogTable(qs("#activityLog"), [
    { key: "createdAt", label: "When" },
    { key: "actor", label: "Actor" },
    { key: "eventType", label: "Event" },
    { key: "message", label: "Message" },
  ], data.activity);
  renderLogTable(qs("#changeLog"), [
    { key: "createdAt", label: "When" },
    { key: "actor", label: "Actor" },
    { key: "entityType", label: "Entity" },
    { key: "fieldName", label: "Field" },
    { key: "oldValue", label: "Old" },
    { key: "newValue", label: "New" },
  ], data.changes);
}

async function loadAdminExport(year = Number(qs("#exportYearInput")?.value || new Date().getFullYear())) {
  const wrap = qs("#exportTable");
  if (!wrap) return;
  const data = await fetchJson(`/api/admin/export?year=${year}`);
  const header = data.dates.map((dateValue) => `<th>${escapeHtml(dateValue.slice(5))}</th>`).join("");
  const rows = data.rows.map((row) => `<tr><th>${escapeHtml(row.physician)}</th>${row.cells.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("");
  wrap.innerHTML = `<table class="export-table"><thead><tr><th>Physician</th>${header}</tr></thead><tbody>${rows}</tbody></table>`;
  const download = qs("#downloadExportButton");
  if (download) download.href = `/api/admin/export.csv?year=${year}`;
}

function startDictation() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Speech dictation is not supported in this browser.");
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const textarea = qs('#assistantRequestForm textarea[name="prompt"]');
    textarea.value = textarea.value ? `${textarea.value} ${transcript}` : transcript;
  };
  recognition.start();
}

function renderGameStatus(message) {
  const status = qs("#gameStatus");
  if (status) status.textContent = message;
}

function destroyGame() {
  if (state.game?.frameId) {
    cancelAnimationFrame(state.game.frameId);
  }
  state.game = null;
}

function startBreakoutGame() {
  destroyGame();
  const canvas = qs("#breakoutCanvas");
  if (!canvas) return;
  openModal("gameOverlay");
  const context = canvas.getContext("2d");
  const occupiedCells = qsa(".slot-pill.occupied").length || 1;
  const brickCount = Math.max(1, Math.min(8, occupiedCells));
  const bricks = [];
  const columns = Math.min(4, brickCount);
  const rows = Math.ceil(brickCount / columns);
  const brickWidth = 140;
  const brickHeight = 28;
  const gap = 12;
  const totalWidth = columns * brickWidth + (columns - 1) * gap;
  const startX = (canvas.width - totalWidth) / 2;
  for (let index = 0; index < brickCount; index += 1) {
    const column = index % columns;
    const row = Math.floor(index / columns);
    bricks.push({ x: startX + column * (brickWidth + gap), y: 60 + row * (brickHeight + gap), width: brickWidth, height: brickHeight, alive: true });
  }

  const game = {
    paddleX: canvas.width / 2 - 60,
    paddleWidth: 120,
    paddleHeight: 14,
    ballX: canvas.width / 2,
    ballY: canvas.height - 70,
    ballDx: 3.6,
    ballDy: -4.4,
    leftPressed: false,
    rightPressed: false,
    frameId: null,
    won: false,
  };
  state.game = game;
  renderGameStatus("Konami code unlocked. Break the VL cells.");

  function draw() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#12284b";
    context.fillRect(0, 0, canvas.width, canvas.height);
    for (const brick of bricks) {
      if (!brick.alive) continue;
      context.fillStyle = "#eaf2fe";
      context.fillRect(brick.x, brick.y, brick.width, brick.height);
      context.strokeStyle = "#78a7ec";
      context.strokeRect(brick.x, brick.y, brick.width, brick.height);
      context.fillStyle = "#143d73";
      context.font = "bold 14px Segoe UI";
      context.fillText("VL", brick.x + brick.width / 2 - 10, brick.y + 18);
    }
    context.fillStyle = "#f0c36e";
    context.fillRect(game.paddleX, canvas.height - 30, game.paddleWidth, game.paddleHeight);
    context.beginPath();
    context.arc(game.ballX, game.ballY, 9, 0, Math.PI * 2);
    context.fillStyle = "#ffffff";
    context.fill();

    if (game.leftPressed) game.paddleX -= 7;
    if (game.rightPressed) game.paddleX += 7;
    if (!game.leftPressed && !game.rightPressed) {
      const target = game.ballX - game.paddleWidth / 2;
      game.paddleX += Math.sign(target - game.paddleX) * Math.min(5, Math.abs(target - game.paddleX));
    }
    game.paddleX = Math.max(0, Math.min(canvas.width - game.paddleWidth, game.paddleX));
    game.ballX += game.ballDx;
    game.ballY += game.ballDy;
    if (game.ballX < 9 || game.ballX > canvas.width - 9) game.ballDx *= -1;
    if (game.ballY < 9) game.ballDy *= -1;
    if (game.ballY > canvas.height - 40 && game.ballX >= game.paddleX && game.ballX <= game.paddleX + game.paddleWidth) {
      game.ballDy = -Math.abs(game.ballDy);
    }
    if (game.ballY > canvas.height) {
      game.ballX = canvas.width / 2;
      game.ballY = canvas.height - 70;
      game.ballDx = 3.6;
      game.ballDy = -4.4;
    }
    for (const brick of bricks) {
      if (!brick.alive) continue;
      if (game.ballX > brick.x && game.ballX < brick.x + brick.width && game.ballY > brick.y && game.ballY < brick.y + brick.height) {
        brick.alive = false;
        game.ballDy *= -1;
      }
    }
    if (bricks.every((brick) => !brick.alive) && !game.won) {
      game.won = true;
      renderGameStatus("Congradulations! You beat the Emergency Department. You may retire now. :)");
      return;
    }
    game.frameId = requestAnimationFrame(draw);
  }

  draw();
}

function handleKonami(event) {
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (key === KONAMI[konamiIndex]) {
    konamiIndex += 1;
    if (konamiIndex === KONAMI.length) {
      konamiIndex = 0;
      startBreakoutGame();
    }
  } else {
    konamiIndex = key === KONAMI[0] ? 1 : 0;
  }
}

function attachGlobalEvents() {
  document.addEventListener("keydown", handleKonami);
  document.addEventListener("keydown", (event) => {
    if (!state.game) return;
    if (event.key === "ArrowLeft") state.game.leftPressed = true;
    if (event.key === "ArrowRight") state.game.rightPressed = true;
  });
  document.addEventListener("keyup", (event) => {
    if (!state.game) return;
    if (event.key === "ArrowLeft") state.game.leftPressed = false;
    if (event.key === "ArrowRight") state.game.rightPressed = false;
  });

  qsa("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.dataset.closeModal));
  });

  qs("#closeGameOverlay")?.addEventListener("click", () => {
    closeModal("gameOverlay");
    destroyGame();
  });

  qs("#settingsButton")?.addEventListener("click", () => openModal("settingsPanel"));
  qs("#openRequestModal")?.addEventListener("click", openRequestModalForCreate);
  qs("#openRequestModalInline")?.addEventListener("click", openRequestModalForCreate);
  qs("#dictateButton")?.addEventListener("click", startDictation);

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
      qsa("[data-admin-panel-button]").forEach((node) => node.classList.toggle("active", node === button));
      qsa("[data-admin-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.adminPanel === button.dataset.adminPanelButton));
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
    const editRequest = event.target.closest("[data-edit-request]");
    if (editRequest) {
      openRequestModalForEdit(editRequest.dataset.editRequest);
      return;
    }
    const cancelRequest = event.target.closest("[data-cancel-request]");
    if (cancelRequest) {
      await fetchJson(`/api/requests/${cancelRequest.dataset.cancelRequest}/cancel`, { method: "POST" });
      await Promise.all([loadHistory(), loadCalendar()]);
      return;
    }
    const removeDelegation = event.target.closest("[data-remove-delegation]");
    if (removeDelegation) {
      await fetchJson(`/api/delegations/${removeDelegation.dataset.removeDelegation}/delete`, { method: "POST" });
      await loadDelegations();
      return;
    }
    const tradeAction = event.target.closest("[data-trade-action]");
    if (tradeAction) {
      const formData = new FormData();
      formData.append("action", tradeAction.dataset.tradeAction);
      await fetchJson(`/api/trades/${tradeAction.dataset.tradeId}/respond`, { method: "POST", body: formData });
      await Promise.all([loadTrades(), loadRotationData(qs("#tradeYearSelect")?.value || new Date().getFullYear()).catch(() => {})]);
      return;
    }
    const editUser = event.target.closest("[data-edit-user]");
    if (editUser) {
      openUserModal(JSON.parse(editUser.dataset.editUser));
      return;
    }
    const toggleUser = event.target.closest("[data-toggle-user]");
    if (toggleUser) {
      await fetchJson(`/api/admin/users/${toggleUser.dataset.toggleUser}/toggle`, { method: "POST" });
      await Promise.all([loadAdminUsers(), refreshSession()]);
      return;
    }
    const deleteUser = event.target.closest("[data-delete-user]");
    if (deleteUser) {
      if (!window.confirm("Delete this user?")) return;
      await fetchJson(`/api/admin/users/${deleteUser.dataset.deleteUser}/delete`, { method: "POST" });
      await Promise.all([loadAdminUsers(), refreshSession()]);
      return;
    }
    const editHoliday = event.target.closest("[data-edit-holiday]");
    if (editHoliday) {
      openHolidayModal(JSON.parse(editHoliday.dataset.editHoliday));
      return;
    }
    const deleteHoliday = event.target.closest("[data-delete-holiday]");
    if (deleteHoliday) {
      if (!window.confirm("Delete this holiday definition?")) return;
      await fetchJson(`/api/admin/holidays/${deleteHoliday.dataset.deleteHoliday}/delete`, { method: "POST" });
      await loadAdminHolidays(Number(qs("#holidayYearFilter")?.value || state.adminHolidaysYear));
      return;
    }
  });

  qs("#requestForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const requestId = formData.get("request_id");
    if (requestId) {
      await fetchJson(`/api/requests/${requestId}`, { method: "POST", body: formData });
    } else {
      await fetchJson("/api/requests", { method: "POST", body: formData });
    }
    closeModal("requestModal");
    form.reset();
    state.editingRequestId = null;
    await Promise.all([loadCalendar(), loadHistory()]);
  });

  qs("#assistantRequestForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const result = await fetchJson("/api/requests/assistant", { method: "POST", body: formData });
    qs("#assistantResponse").textContent = result.parsed?.explanation || "Vacation scheduled.";
    form.reset();
    closeModal("requestModal");
    await Promise.all([loadCalendar(), loadHistory()]);
  });

  qs("#settingsForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    formData.set("show_week_numbers", formData.get("show_week_numbers") ? "true" : "false");
    state.weekStart = formData.get("week_start");
    state.showWeekNumbers = formData.get("show_week_numbers") === "true";
    await fetchJson("/api/settings", { method: "POST", body: formData });
    closeModal("settingsPanel");
    await loadCalendar();
  });

  qs("#delegationForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await fetchJson("/api/delegations", { method: "POST", body: new FormData(event.currentTarget) });
    event.currentTarget.reset();
    await loadDelegations();
  });

  qs("#tradeYearSelect")?.addEventListener("change", async (event) => {
    await loadRotationData(event.currentTarget.value);
  });
  qs("#myHolidaySelect")?.addEventListener("change", populateTradeHolidayOptions);
  qs("#tradeTargetUserSelect")?.addEventListener("change", populateTradeHolidayOptions);

  qs("#tradeForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await fetchJson("/api/trades", { method: "POST", body: new FormData(event.currentTarget) });
    event.currentTarget.reset();
    await Promise.all([loadTrades(), loadRotationData(qs("#tradeYearSelect")?.value || new Date().getFullYear())]);
  });

  qs("#userCreateForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await fetchJson("/api/admin/users", { method: "POST", body: new FormData(event.currentTarget) });
    event.currentTarget.reset();
    await Promise.all([loadAdminUsers(), refreshSession()]);
  });

  qs("#userEditForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const userId = form.querySelector('[name="user_id"]').value;
    await fetchJson(`/api/admin/users/${userId}`, { method: "POST", body: new FormData(form) });
    closeModal("userModal");
    await Promise.all([loadAdminUsers(), refreshSession()]);
  });

  qs("#holidayCreateForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await fetchJson("/api/admin/holidays", { method: "POST", body: new FormData(event.currentTarget) });
    const year = Number(event.currentTarget.querySelector('[name="year"]').value);
    await Promise.all([loadAdminHolidays(year), loadCalendar()]);
    event.currentTarget.reset();
  });

  qs("#holidayEditForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const holidayId = form.querySelector('[name="holiday_id"]').value;
    const formData = new FormData(form);
    formData.set("is_locked", form.querySelector('[name="is_locked"]').checked ? "true" : "false");
    await fetchJson(`/api/admin/holidays/${holidayId}`, { method: "POST", body: formData });
    closeModal("holidayModal");
    await Promise.all([loadAdminHolidays(Number(qs("#holidayYearFilter")?.value || state.adminHolidaysYear)), loadCalendar()]);
  });

  qs("#reloadHolidayList")?.addEventListener("click", async () => {
    const year = Number(qs("#holidayYearFilter")?.value || state.adminHolidaysYear);
    await loadAdminHolidays(year);
  });

  qs("#loadExportButton")?.addEventListener("click", async () => {
    await loadAdminExport();
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

  attachGlobalEvents();
  await refreshSession().catch(() => {});
  populatePhysicianSelects();
  populateDelegationSelect();
  if (mount || qs("#miniCalendarGrid")) await loadCalendar();
  await Promise.allSettled([
    loadHistory(),
    loadDelegations(),
    loadTrades(),
    loadAdminUsers(),
    loadAdminHolidays(Number(qs("#holidayYearFilter")?.value || new Date().getFullYear())),
    loadAdminLogs(),
    loadAdminExport(),
  ]);
  if (qs("#tradeYearSelect")) {
    await loadRotationData(qs("#tradeYearSelect").value || new Date().getFullYear()).catch(() => {});
  }

  setInterval(() => {
    if (document.hidden) return;
    loadCalendar().catch(() => {});
    loadHistory().catch(() => {});
    loadTrades().catch(() => {});
    loadAdminLogs().catch(() => {});
  }, 45000);
}

init().catch((error) => {
  console.error(error);
  notifyError(error);
});

window.addEventListener("unhandledrejection", (event) => {
  console.error(event.reason);
  notifyError(event.reason);
  event.preventDefault();
});
