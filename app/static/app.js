const state = {
  year: null,
  month: null,
  weekStart: window.APP_CONFIG.currentUser?.weekStart || "sunday",
  showWeekNumbers: Boolean(window.APP_CONFIG.currentUser?.showWeekNumbers),
  themeSkin: window.APP_CONFIG.currentUser?.themeSkin || document.body.dataset.theme || "slate",
  session: {
    currentUser: window.APP_CONFIG.currentUser,
    managedPhysicians: window.APP_CONFIG.managedPhysicians || [],
    physicianDirectory: window.APP_CONFIG.physicianDirectory || [],
    rotationYears: window.APP_CONFIG.rotationYears || [],
    gameHighScore: window.APP_CONFIG.gameHighScore || null,
    gamePersonalBest: window.APP_CONFIG.gamePersonalBest || null,
  },
  editingRequestId: null,
  adminHolidaysYear: new Date().getFullYear(),
  rotationData: null,
  trades: [],
  historyRequests: [],
  dayRequests: [],
  waitlistRequests: [],
  adminWaitlistRequests: [],
  exportMatrix: null,
  logs: {
    kind: "activity",
    page: 1,
  },
  settings: {
    activeSection: "appearance",
  },
  selection: {
    anchor: null,
    start: null,
    end: null,
    mouseDown: false,
    didDrag: false,
    suppressClick: false,
  },
  dictation: null,
  game: null,
};

const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a", "Enter"];
const THEME_OPTIONS = window.APP_CONFIG.themeOptions || [];
let konamiIndex = 0;
window.__VACATION_SCHEDULER_STATE__ = state;

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
    if (node.contains(document.activeElement)) {
      document.activeElement?.blur();
    }
    node.classList.add("hidden");
    node.setAttribute("aria-hidden", "true");
    const card = node.querySelector(".modal-card, .game-panel");
    if (card) {
      card.style.removeProperty("--drag-x");
      card.style.removeProperty("--drag-y");
    }
  }
}

function setSettingsSection(section) {
  const target = section || "appearance";
  state.settings.activeSection = target;
  qsa("[data-settings-section-button]").forEach((button) => {
    const isActive = button.dataset.settingsSectionButton === target;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
  qsa("[data-settings-section]").forEach((panel) => {
    const isActive = panel.dataset.settingsSection === target;
    panel.classList.toggle("active", isActive);
    panel.hidden = !isActive;
  });
}

function openSettingsPanel(section = state.settings.activeSection) {
  setSettingsSection(section);
  openModal("settingsPanel");
}

function showToast(message, type = "info") {
  const stack = qs("#toastStack");
  if (!stack || !message) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  stack.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("visible"));
  const removeToast = () => {
    toast.classList.remove("visible");
    window.setTimeout(() => toast.remove(), 180);
  };
  toast.addEventListener("click", removeToast);
  window.setTimeout(removeToast, 4200);
}

function notifyError(error) {
  showToast(error?.message || String(error), "error");
}

function availableThemeOptions() {
  return THEME_OPTIONS.filter((option) => !option.isRandom);
}

function syncThemeSelection(theme) {
  qsa('#settingsForm input[name="theme_skin"]').forEach((input) => {
    input.checked = input.value === theme;
  });
}

function applyTheme(theme) {
  const available = availableThemeOptions();
  const requested = THEME_OPTIONS.some((option) => option.id === theme) ? theme : "slate";
  const resolved = requested === "random"
    ? available[Math.floor(Math.random() * available.length)] || available[0]
    : available.find((option) => option.id === requested) || available.find((option) => option.id === "slate") || available[0];
  if (!resolved) return;
  state.themeSkin = requested;
  document.body.dataset.theme = resolved.id;
  document.body.dataset.themeSelection = requested;
  for (const [key, value] of Object.entries(resolved.colors || {})) {
    const cssKey = key.replace(/[A-Z]/g, (character) => `-${character.toLowerCase()}`);
    document.body.style.setProperty(`--${cssKey}`, value);
  }
  syncThemeSelection(requested);
}

function enhancePasswordFields() {
  qsa('input[type="password"]').forEach((input) => {
    if (input.dataset.passwordEnhanced === "true") return;
    input.dataset.passwordEnhanced = "true";
    const wrapper = document.createElement("div");
    wrapper.className = "password-wrap";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "password-toggle";
    button.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M2.5 12c1.8-3.2 5.2-5.8 9.5-5.8s7.7 2.6 9.5 5.8c-1.8 3.2-5.2 5.8-9.5 5.8S4.3 15.2 2.5 12Z"></path>
        <circle cx="12" cy="12" r="3.2"></circle>
        <path class="eye-slash" d="M4 20L20 4"></path>
      </svg>
      <span class="sr-only">Show password</span>
    `;
    button.setAttribute("aria-label", "Show password");
    button.addEventListener("click", () => {
      const revealed = input.type === "text";
      input.type = revealed ? "password" : "text";
      button.classList.toggle("is-revealed", !revealed);
      button.setAttribute("aria-label", revealed ? "Show password" : "Hide password");
      const srOnly = button.querySelector(".sr-only");
      if (srOnly) srOnly.textContent = revealed ? "Show password" : "Hide password";
    });
    wrapper.appendChild(button);
  });
}

function bindPasswordValidation(form) {
  const primary = form.querySelector("[data-password-primary]");
  const confirm = form.querySelector("[data-password-confirm]");
  const feedback = form.querySelector("[data-password-feedback]");
  if (!primary || !confirm || !feedback) return;
  const updateFeedback = () => {
    if (primary.disabled || confirm.disabled) {
      confirm.setCustomValidity("");
      feedback.textContent = "";
      feedback.classList.add("hidden");
      feedback.classList.remove("is-error", "is-success");
      return;
    }
    const shouldValidate = confirm.value.length > 0 || primary.value.length > 0;
    if (!shouldValidate) {
      confirm.setCustomValidity("");
      feedback.textContent = "";
      feedback.classList.add("hidden");
      feedback.classList.remove("is-error", "is-success");
      return;
    }
    if (primary.value !== confirm.value) {
      confirm.setCustomValidity("Passwords do not match.");
      feedback.textContent = "Passwords do not match.";
      feedback.classList.remove("hidden", "is-success");
      feedback.classList.add("is-error");
      return;
    }
    confirm.setCustomValidity("");
    feedback.textContent = "Passwords match.";
    feedback.classList.remove("hidden", "is-error");
    feedback.classList.add("is-success");
  };
  primary.addEventListener("input", updateFeedback);
  confirm.addEventListener("input", updateFeedback);
  form.addEventListener("submit", (event) => {
    updateFeedback();
    if (!form.reportValidity()) {
      event.preventDefault();
    }
  });
}

function enableDraggableModals() {
  qsa(".modal, .game-overlay").forEach((overlay) => {
    const card = overlay.querySelector(".modal-card, .game-panel");
    const header = overlay.querySelector(".modal-header");
    if (!card || !header || card.dataset.draggableBound === "true") return;
    card.dataset.draggableBound = "true";
    let startX = 0;
    let startY = 0;
    let dragX = 0;
    let dragY = 0;
    let dragging = false;

    const onMove = (event) => {
      if (!dragging) return;
      card.style.setProperty("--drag-x", `${dragX + event.clientX - startX}px`);
      card.style.setProperty("--drag-y", `${dragY + event.clientY - startY}px`);
    };
    const onUp = (event) => {
      if (!dragging) return;
      dragging = false;
      dragX += event.clientX - startX;
      dragY += event.clientY - startY;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
    };
    header.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button, input, select, textarea, a")) return;
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    });
  });
}

function formatDateRange(startDate, endDate) {
  return startDate === endDate ? startDate : `${startDate} to ${endDate}`;
}

function selectionEnabled() {
  return state.session.currentUser?.role === "physician" && Boolean(qs("#selectionToolbar"));
}

function compareIsoDates(left, right) {
  return left.localeCompare(right);
}

function currentSelectionRange() {
  if (!state.selection.start || !state.selection.end) return null;
  return compareIsoDates(state.selection.start, state.selection.end) <= 0
    ? { start: state.selection.start, end: state.selection.end }
    : { start: state.selection.end, end: state.selection.start };
}

function selectionDateSet() {
  const range = currentSelectionRange();
  const dates = new Set();
  if (!range) return dates;
  const current = new Date(`${range.start}T00:00:00`);
  const end = new Date(`${range.end}T00:00:00`);
  while (current <= end) {
    dates.add(current.toISOString().slice(0, 10));
    current.setDate(current.getDate() + 1);
  }
  return dates;
}

function syncSelectionHighlights() {
  const selected = selectionDateSet();
  qsa("[data-day]").forEach((dayCell) => {
    dayCell.classList.toggle("selected", selected.has(dayCell.dataset.day));
  });
}

function renderSelectionToolbar() {
  const toolbar = qs("#selectionToolbar");
  if (!toolbar) return;
  const label = qs("#selectionLabel");
  const range = currentSelectionRange();
  if (!range) {
    toolbar.classList.add("hidden");
    toolbar.setAttribute("aria-hidden", "true");
    if (label) label.textContent = "No dates selected";
    return;
  }
  toolbar.classList.remove("hidden");
  toolbar.setAttribute("aria-hidden", "false");
  if (label) label.textContent = `Selected ${formatDateRange(range.start, range.end)}`;
}

function clearSelection() {
  state.selection.anchor = null;
  state.selection.start = null;
  state.selection.end = null;
  state.selection.mouseDown = false;
  state.selection.didDrag = false;
  state.selection.suppressClick = false;
  syncSelectionHighlights();
  renderSelectionToolbar();
}

function activeEditableElement() {
  const active = document.activeElement;
  if (!active) return null;
  if (active.isContentEditable) return active;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName)) return active;
  return null;
}

function resetFormFeedback(form) {
  if (!form) return;
  const feedback = form.querySelector("[data-password-feedback]");
  if (feedback) {
    feedback.textContent = "";
    feedback.classList.add("hidden");
    feedback.classList.remove("is-error", "is-success");
  }
  [...form.querySelectorAll("input")].forEach((input) => input.setCustomValidity(""));
}

async function assignSelectedRange() {
  const range = currentSelectionRange();
  const actor = state.session.currentUser;
  if (!range || !actor) return;
  const formData = new FormData();
  formData.set("physician_id", actor.id);
  formData.set("start_date", range.start);
  formData.set("end_date", range.end);
  formData.set("request_note", "");
  const result = await fetchJson("/api/requests", { method: "POST", body: formData });
  showToast(result.message || "Vacation saved.", /waitlist/i.test(result.message || "") ? "warning" : "success");
  clearSelection();
  await Promise.all([loadCalendar(), loadHistory()]);
}

async function unassignSelectedRange() {
  const range = currentSelectionRange();
  const actor = state.session.currentUser;
  if (!range || !actor) return;
  const formData = new FormData();
  formData.set("physician_id", actor.id);
  formData.set("start_date", range.start);
  formData.set("end_date", range.end);
  const result = await fetchJson("/api/requests/unassign-range", { method: "POST", body: formData });
  showToast(result.message || "Selected dates removed.", result.affectedCount ? "success" : "warning");
  clearSelection();
  await Promise.all([loadCalendar(), loadHistory()]);
}

function exportMonthNumber() {
  return Number(qs("#exportMonthSelect")?.value || 0);
}

function currentManagedPhysicians() {
  return state.session.managedPhysicians || [];
}

function canManageMultiplePhysicians() {
  const user = state.session.currentUser;
  return user?.role === "admin" || currentManagedPhysicians().length > 1;
}

function syncRequestModalFields() {
  const user = state.session.currentUser;
  const showPhysicianFields = canManageMultiplePhysicians();
  const fields = [qs("#requestPhysicianField"), qs("#assistantPhysicianField")].filter(Boolean);
  for (const field of fields) {
    field.hidden = !showPhysicianFields;
  }
  if (user && !showPhysicianFields) {
    qs("#requestPhysicianSelect").value = String(user.id);
    qs("#assistantPhysicianSelect").value = String(user.id);
  }
}

function setSingleDaySelection(dayIso) {
  state.selection.anchor = dayIso;
  state.selection.start = dayIso;
  state.selection.end = dayIso;
  state.selection.mouseDown = false;
  state.selection.didDrag = false;
  state.selection.suppressClick = false;
  syncSelectionHighlights();
  renderSelectionToolbar();
}

async function refreshSession() {
  const data = await fetchJson("/api/session");
  state.session = {
    currentUser: data.user,
    managedPhysicians: data.managedPhysicians || [],
    physicianDirectory: data.physicianDirectory || [],
    rotationYears: data.rotationYears || [],
    gameHighScore: data.gameHighScore || data.highScore || null,
    gamePersonalBest: data.gamePersonalBest || data.personalBest || null,
  };
  if (state.session.currentUser) {
    state.weekStart = state.session.currentUser.weekStart;
    state.showWeekNumbers = Boolean(state.session.currentUser.showWeekNumbers);
    applyTheme(state.session.currentUser.themeSkin || "slate");
  }
  if (!selectionEnabled()) {
    clearSelection();
  } else {
    renderSelectionToolbar();
  }
  populatePhysicianSelects();
  syncRequestModalFields();
  populateDelegationSelect();
  populateTradeTargetUsers();
  renderBreakoutScoreboard();
}

function populatePhysicianSelects() {
  const managed = currentManagedPhysicians();
  const selects = [qs("#requestPhysicianSelect"), qs("#assistantPhysicianSelect")].filter(Boolean);
  for (const select of selects) {
    const currentValue = select.value;
    select.innerHTML = managed.map((physician) => `<option value="${physician.id}">${escapeHtml(physician.fullName)}</option>`).join("");
    if (currentValue && managed.some((physician) => String(physician.id) === currentValue)) {
      select.value = currentValue;
    } else if (managed[0]) {
      select.value = String(managed[0].id);
    }
  }
  syncRequestModalFields();
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

function syncUserCreateProvisioningMode() {
  const form = qs("#userCreateForm");
  if (!form) return;
  const modeInput = qs("#userProvisioningMode");
  const manualToggle = qs("#userProvisioningManualToggle");
  const helpText = qs("#userProvisioningHelp");
  const mode = manualToggle?.checked ? "manual_password" : "reset_link";
  const passwordField = qs("#userCreatePasswordField");
  const confirmField = qs("#userCreateConfirmPasswordField");
  const randomActions = qs("#userCreateRandomActions");
  const passwordInput = passwordField?.querySelector('input[name="password"]');
  const confirmInput = confirmField?.querySelector('input[name="confirm_password"]');
  const usesPasswordInputs = mode === "manual_password";
  if (modeInput) modeInput.value = mode;
  if (passwordField) passwordField.hidden = !usesPasswordInputs;
  if (confirmField) confirmField.hidden = !usesPasswordInputs;
  if (randomActions) randomActions.hidden = !usesPasswordInputs;
  if (helpText) {
    helpText.textContent = usesPasswordInputs
      ? "Set the password yourself, or use the generate button to fill both fields."
      : "Default: email a setup link to the new user.";
  }
  if (passwordInput) {
    passwordInput.disabled = !usesPasswordInputs;
    passwordInput.required = usesPasswordInputs;
    if (!usesPasswordInputs) passwordInput.value = "";
  }
  if (confirmInput) {
    confirmInput.disabled = !usesPasswordInputs;
    confirmInput.required = usesPasswordInputs;
    if (!usesPasswordInputs) confirmInput.value = "";
  }
  resetFormFeedback(form);
}

function generateTemporaryPassword() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*";
  return Array.from({ length: 14 }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join("");
}

function renderMiniCalendar(year, month, weekStart) {
  const label = qs("#miniCalendarLabel");
  const grid = qs("#miniCalendarGrid");
  if (!label || !grid) return;
  const firstWeekday = weekStart === "sunday" ? 0 : 1;
  const jsFirstDay = new Date(year, month - 1, 1);
  const offset = (jsFirstDay.getDay() - firstWeekday + 7) % 7;
  const start = new Date(year, month - 1, 1 - offset);
  label.innerHTML = `
    <span class="mini-calendar-year">${jsFirstDay.getFullYear()}</span>
    <span class="mini-calendar-month">${jsFirstDay.toLocaleString(undefined, { month: "long" })}</span>
  `;
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
  const selectedDates = selectionDateSet();
  const gridClass = data.showWeekNumbers ? "calendar-grid with-weeks" : "calendar-grid";
  const subgridClass = data.showWeekNumbers ? "with-weeks" : "";
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
      if (day.waitlistCount) classNames.push("has-waitlist");
      if (selectedDates.has(day.date)) classNames.push("selected");
      const holidayBadge = day.isHoliday ? `<div class="holiday-pill">${escapeHtml(day.holiday.title)}</div>` : "";
      const waitlistBadge = day.waitlistCount ? `<div class="waitlist-badge" title="${day.waitlistCount} waitlisted request${day.waitlistCount === 1 ? "" : "s"}">W${day.waitlistCount}</div>` : "";
      const slots = day.isHoliday
        ? ""
        : day.slots.map((slot) => `<div class="slot-pill ${slot.occupied ? "occupied" : ""}" title="${escapeHtml(slot.name || "Open slot")}">${escapeHtml(slot.label || "")}</div>`).join("");
      body.push(`
        <button type="button" class="${classNames.join(" ")}" data-day="${day.date}" data-current-month="${day.isCurrentMonth}" data-holiday="${day.isHoliday}" data-waitlist-count="${day.waitlistCount || 0}">
          <div class="day-head">
            <div class="day-number">${day.day}</div>
            ${waitlistBadge}
          </div>
          ${holidayBadge}
          ${day.isHoliday ? "" : `<div class="slot-list">${slots}</div>`}
        </button>
      `);
    }
  }
  mount.innerHTML = `
    <div class="${gridClass}">
      <div class="calendar-weekdays ${subgridClass}">${header.join("")}</div>
      <div class="calendar-body ${subgridClass}" style="--calendar-week-count: ${data.weeks.length};">${body.join("")}</div>
    </div>
  `;
  renderSelectionToolbar();
  syncSelectionHighlights();
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
  state.dayRequests = [...(data.requests || []), ...(data.waitlistRequests || [])].map((item) => ({
    id: item.requestId,
    physicianId: item.physicianId,
    physician: item.physician,
    startDate: item.startDate,
    endDate: item.endDate,
    note: item.note || "",
    status: item.status,
  }));
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
        '<div class="stack"><h3>Scheduled</h3>',
        data.requests.map((item) => `
          <div class="detail-card">
            <div>
              <strong>${escapeHtml(item.physician)}</strong>
              <div class="subtle">${escapeHtml(formatDateRange(item.startDate, item.endDate))}</div>
              <div class="subtle">Scheduled by ${escapeHtml(item.requestedBy)}</div>
            </div>
            <div class="inline-actions">
              <span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
              ${item.canManage ? `<button class="secondary-button" type="button" data-edit-request="${item.requestId}">Edit</button>` : ""}
              ${item.canManage ? `<button class="secondary-button" type="button" data-remove-request-day="${item.requestId}" data-remove-day="${escapeHtml(data.date)}">Remove this day</button>` : ""}
            </div>
          </div>
        `).join(""),
        "</div>"
      );
  }
  if (data.waitlistRequests?.length) {
    parts.push(
      '<div class="stack"><h3>Waitlist</h3>',
      data.waitlistRequests.map((item) => `
        <div class="detail-card waitlist-card">
          <div>
            <strong>${escapeHtml(item.physician)}</strong>
            <div class="subtle">${escapeHtml(formatDateRange(item.startDate, item.endDate))}</div>
            <div class="subtle">Requested by ${escapeHtml(item.requestedBy)}</div>
          </div>
          <div class="inline-actions">
            <span class="status waitlisted">waitlisted</span>
            ${item.canManage ? `<button class="secondary-button" type="button" data-edit-request="${item.requestId}">Edit</button>` : ""}
            ${item.canManage ? `<button class="secondary-button" type="button" data-cancel-request="${item.requestId}">Cancel</button>` : ""}
          </div>
        </div>
      `).join(""),
      "</div>"
    );
  }
  content.innerHTML = parts.join("");
  openModal("dayModal");
}

function renderRequestList(target, requests, options = {}) {
  if (!target) return;
  const emptyText = options.emptyText || "No vacation entries yet.";
  if (!requests.length) {
    target.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    return;
  }
  target.innerHTML = requests.map((item) => `
    <article class="history-item ${item.status === "waitlisted" ? "waitlist-card" : ""}">
      <div>
        <strong>${escapeHtml(item.physician)}</strong>
        <div class="subtle">${escapeHtml(formatDateRange(item.startDate, item.endDate))}</div>
        <div class="subtle">Created by ${escapeHtml(item.createdBy)}</div>
        ${item.note ? `<div class="subtle">${escapeHtml(item.note)}</div>` : ""}
        ${item.decisionNote ? `<div class="subtle">${escapeHtml(item.decisionNote)}</div>` : ""}
      </div>
      <div class="inline-actions">
        <span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        ${item.status !== "canceled" ? `<button class="secondary-button" type="button" data-edit-request="${item.id}">Edit</button>` : ""}
        ${item.status !== "canceled" ? `<button class="secondary-button" type="button" data-cancel-request="${item.id}">Cancel</button>` : ""}
      </div>
    </article>
  `).join("");
}

async function loadHistory() {
  const list = qs("#historyList");
  const waitlistList = qs("#waitlistList");
  const adminList = qs("#adminRequests");
  const adminWaitlist = qs("#adminWaitlist");
  if (!list && !waitlistList && !adminList && !adminWaitlist) return;
  const data = await fetchJson("/api/requests");
  state.historyRequests = data.requests;
  state.waitlistRequests = data.requests.filter((item) => item.status === "waitlisted");
  state.adminWaitlistRequests = state.waitlistRequests;
  const primaryRequests = data.requests.filter((item) => item.status !== "waitlisted");
  renderRequestList(list, primaryRequests, { emptyText: "No vacation entries yet." });
  renderRequestList(waitlistList, state.waitlistRequests, { emptyText: "No waitlisted requests." });
  renderRequestList(adminList, primaryRequests, { emptyText: "No scheduled or canceled requests." });
  renderRequestList(adminWaitlist, state.adminWaitlistRequests, { emptyText: "No waitlisted requests." });
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
  const currentUserRole = state.session.currentUser?.role;
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
        ${item.status === "pending" && (item.offeredByUserId === currentUserId || currentUserRole === "admin") ? `<button class="secondary-button" type="button" data-trade-action="cancel" data-trade-id="${item.id}">Cancel offer</button>` : ""}
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
  const actor = state.session.currentUser;
  const range = currentSelectionRange();
  state.editingRequestId = null;
  qs("#requestModalTitle").textContent = "Schedule Vacation";
  qs("#requestForm")?.reset();
  qs("#assistantRequestForm")?.reset();
  qs('#requestForm input[name="request_id"]').value = "";
  qs("#assistantResponse").textContent = "";
  populatePhysicianSelects();
  if (actor.role === "physician") {
    qs("#requestPhysicianSelect").value = String(actor.id);
    qs("#assistantPhysicianSelect").value = String(actor.id);
  }
  if (range) {
    qs('#requestForm [name="start_date"]').value = range.start;
    qs('#requestForm [name="end_date"]').value = range.end;
  }
  openModal("requestModal");
}

async function openRequestModalForEdit(requestId) {
  let item = state.historyRequests.find((request) => request.id === Number(requestId));
  if (!item) {
    item = state.dayRequests.find((request) => request.id === Number(requestId));
  }
  if (!item) {
    const data = await fetchJson(`/api/requests/${requestId}`);
    item = data.request;
  }
  if (!item) return;
  state.editingRequestId = item.id;
  qs("#requestModalTitle").textContent = `Edit Vacation for ${item.physician}`;
  populatePhysicianSelects();
  qs('#requestForm input[name="request_id"]').value = item.id;
  qs('#requestForm [name="physician_id"]').value = String(item.physicianId);
  qs('#assistantPhysicianSelect').value = String(item.physicianId);
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
  const currentUserId = state.session.currentUser?.id;
  const groups = [
    { role: "admin", title: "Admin accounts" },
    { role: "physician", title: "Physician accounts" },
  ];
  list.innerHTML = groups.map((group) => {
    const groupUsers = users.filter((user) => user.role === group.role);
    if (!groupUsers.length) return "";
    return `
      <section class="admin-user-group">
        <h3 class="admin-user-group-title">${escapeHtml(group.title)}</h3>
        ${groupUsers.map((user) => `
          <article class="admin-user-row">
            <div class="admin-user-meta">
              <strong>${escapeHtml(user.fullName)}${user.id === currentUserId ? " (you)" : ""}</strong>
              <div class="subtle">@${escapeHtml(user.username)} - ${escapeHtml(user.email)}</div>
              <div class="subtle">${escapeHtml(user.role)} account</div>
            </div>
            <div class="inline-actions">
              <span class="status ${user.isActive ? "active" : "inactive"}">${user.isActive ? "active" : "inactive"}</span>
              <button class="secondary-button" type="button" data-edit-user='${escapeHtml(JSON.stringify(user))}'>Edit / reset password</button>
              <button class="secondary-button" type="button" data-toggle-user="${user.id}" ${user.id === currentUserId ? "disabled" : ""}>${user.isActive ? "Disable" : "Enable"}</button>
              <button class="secondary-button" type="button" data-delete-user="${user.id}" ${user.id === currentUserId ? "disabled" : ""}>Delete</button>
            </div>
          </article>
        `).join("")}
      </section>
    `;
  }).join("");
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
  qs('#userEditForm [name="password"]').value = "";
  qs('#userEditForm [name="confirm_password"]').value = "";
  resetFormFeedback(qs("#userEditForm"));
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

function renderLogPagination(page, pageCount) {
  const container = qs("#logPagination");
  if (!container) return;
  if (pageCount <= 1) {
    container.innerHTML = "";
    return;
  }
  const pages = new Set([1, pageCount]);
  for (let value = Math.max(1, page - 2); value <= Math.min(pageCount, page + 2); value += 1) {
    pages.add(value);
  }
  const orderedPages = [...pages].sort((left, right) => left - right);
  const parts = [
    `<button class="secondary-button pagination-button" type="button" data-log-page="${Math.max(1, page - 1)}" ${page === 1 ? "disabled" : ""}>Previous</button>`,
  ];
  for (let index = 0; index < orderedPages.length; index += 1) {
    const value = orderedPages[index];
    const previous = orderedPages[index - 1];
    if (previous && value - previous > 1) {
      parts.push('<span class="pagination-gap">...</span>');
    }
    parts.push(
      `<button class="secondary-button pagination-button ${value === page ? "active" : ""}" type="button" data-log-page="${value}">${value}</button>`
    );
  }
  parts.push(
    `<button class="secondary-button pagination-button" type="button" data-log-page="${Math.min(pageCount, page + 1)}" ${page === pageCount ? "disabled" : ""}>Next</button>`
  );
  container.innerHTML = parts.join("");
}

async function loadAdminLogs() {
  const table = qs("#logTable");
  if (!table) return;
  const data = await fetchJson(`/api/admin/logs?kind=${state.logs.kind}&page=${state.logs.page}&page_size=100`);
  state.logs.kind = data.kind;
  state.logs.page = data.page;
  qsa("[data-log-kind]").forEach((button) => {
    button.classList.toggle("active", button.dataset.logKind === data.kind);
  });
  if (data.kind === "changes") {
    renderLogTable(table, [
      { key: "createdAt", label: "When" },
      { key: "actor", label: "Actor" },
      { key: "entityType", label: "Entity" },
      { key: "entityId", label: "ID" },
      { key: "fieldName", label: "Field" },
      { key: "oldValue", label: "Old" },
      { key: "newValue", label: "New" },
    ], data.items);
  } else {
    renderLogTable(table, [
      { key: "createdAt", label: "When" },
      { key: "actor", label: "Actor" },
      { key: "eventType", label: "Event" },
      { key: "message", label: "Message" },
    ], data.items);
  }
  renderLogPagination(data.page, data.pageCount);
}

async function loadAdminExport(year = Number(qs("#exportYearInput")?.value || new Date().getFullYear())) {
  const wrap = qs("#exportTable");
  if (!wrap) return;
  state.exportMatrix = await fetchJson(`/api/admin/export?year=${year}`);
  const monthNumber = exportMonthNumber();
  const visibleIndexes = [];
  state.exportMatrix.dates.forEach((dateValue, index) => {
    if (!monthNumber || Number(dateValue.slice(5, 7)) === monthNumber) {
      visibleIndexes.push(index);
    }
  });
  const visibleDates = visibleIndexes.map((index) => state.exportMatrix.dates[index]);
  const header = visibleDates.map((dateValue) => `<th>${escapeHtml(dateValue.slice(5))}</th>`).join("");
  const rows = state.exportMatrix.rows.map((row) => {
    const cells = visibleIndexes.map((index) => `<td>${escapeHtml(row.cells[index])}</td>`).join("");
    return `<tr><th>${escapeHtml(row.physician)}</th>${cells}</tr>`;
  }).join("");
  wrap.innerHTML = `<table class="export-table"><thead><tr><th>Physician</th>${header}</tr></thead><tbody>${rows}</tbody></table>`;
  const download = qs("#downloadExportButton");
  if (download) download.href = `/api/admin/export.csv?year=${year}`;
}

function startDictation() {
  const textarea = qs('#assistantRequestForm textarea[name="prompt"]');
  if (!textarea) return;
  textarea.focus();
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showToast("Speech dictation is not supported in this browser.", "warning");
    return;
  }
  state.dictation?.stop?.();
  const recognition = new SpeechRecognition();
  state.dictation = recognition;
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.onstart = () => showToast("Dictation started. Speak into your microphone.", "info");
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    textarea.value = textarea.value ? `${textarea.value} ${transcript}` : transcript;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
    showToast("Dictation added to the assistant request.", "success");
  };
  recognition.onerror = (event) => {
    showToast(`Dictation failed: ${event.error || "unknown error"}.`, "error");
  };
  recognition.onend = () => {
    if (state.dictation === recognition) state.dictation = null;
    textarea.focus();
  };
  recognition.start();
}

function formatBreakoutScore(value) {
  return Number.isFinite(value) ? Math.max(0, Math.round(value)).toLocaleString() : "0";
}

function computeBreakoutScore({ brickCount, elapsedMs, paddleHits, livesLeft }) {
  const elapsedSeconds = elapsedMs / 1000;
  return Math.max(0, Math.round(brickCount * 520 + livesLeft * 900 - elapsedSeconds * 42 - paddleHits * 28));
}

function renderBreakoutScoreboard(currentScore = null) {
  const currentNode = qs("#gameCurrentScore");
  const highScoreValue = qs("#gameHighScoreValue");
  const highScoreUser = qs("#gameHighScoreUser");
  if (currentNode) currentNode.textContent = formatBreakoutScore(currentScore ?? state.game?.score ?? 0);
  if (highScoreValue) {
    highScoreValue.textContent = state.session.gameHighScore ? formatBreakoutScore(state.session.gameHighScore.score) : "No score yet";
  }
  if (highScoreUser) {
    if (state.session.gameHighScore) {
      const owner = state.session.gameHighScore.fullName || state.session.gameHighScore.username;
      highScoreUser.textContent = `${owner} holds the top score.`;
    } else if (state.session.currentUser) {
      highScoreUser.textContent = "Finish a winning run to claim the first score.";
    } else {
      highScoreUser.textContent = "Log in to claim the high score.";
    }
  }
}

function renderGameStatus(message) {
  const status = qs("#gameStatus");
  if (status) status.textContent = message;
}

function clearConfetti() {
  const layer = qs("#confettiLayer");
  if (!layer) return;
  layer.innerHTML = "";
}

function burstConfetti() {
  const layer = qs("#confettiLayer");
  if (!layer) return;
  clearConfetti();
  for (let index = 0; index < 56; index += 1) {
    const piece = document.createElement("span");
    piece.className = "confetti-piece";
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.animationDelay = `${Math.random() * 0.3}s`;
    piece.style.animationDuration = `${2.3 + Math.random() * 1.6}s`;
    piece.style.background = ["#ffb703", "#fb8500", "#8ecae6", "#90be6d", "#f28482", "#577590"][index % 6];
    layer.appendChild(piece);
  }
}

function destroyGame() {
  if (state.game?.frameId) {
    cancelAnimationFrame(state.game.frameId);
  }
  clearConfetti();
  state.game = null;
  renderBreakoutScoreboard(0);
}

async function submitBreakoutScore(game) {
  if (!state.session.currentUser || !game?.won || game.score <= 0) return;
  const formData = new FormData();
  formData.set("score", String(Math.round(game.score)));
  formData.set("elapsed_ms", String(Math.max(1, Math.round(game.elapsedMs))));
  formData.set("paddle_hits", String(Math.max(0, Math.round(game.paddleHits))));
  formData.set("lives_left", String(Math.max(0, Math.round(game.lives))));
  formData.set("brick_count", String(Math.max(1, Math.round(game.bricks.length))));
  try {
    const result = await fetchJson("/api/game-score", { method: "POST", body: formData });
    state.session.gameHighScore = result.highScore || null;
    state.session.gamePersonalBest = result.personalBest || null;
    renderBreakoutScoreboard(game.score);
    renderGameStatus(`Score ${formatBreakoutScore(game.score)}. ${result.message}`);
  } catch (error) {
    renderGameStatus(`Score ${formatBreakoutScore(game.score)}. ${error?.message || String(error)}`);
  }
}

function startBreakoutGame() {
  destroyGame();
  const canvas = qs("#breakoutCanvas");
  if (!canvas) return;
  openModal("gameOverlay");
  const context = canvas.getContext("2d");
  const occupiedCells = qsa(".slot-pill.occupied").length || 1;
  const physicianNames = (state.session.physicianDirectory || currentManagedPhysicians())
    .map((person) => person.fullName.split(" ").slice(-1)[0])
    .filter(Boolean);
  let seed = occupiedCells * 97 + state.month * 31 + state.year;
  const random = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  const brickCount = Math.max(18, Math.min(30, 18 + occupiedCells));
  const bricks = [];
  const columns = 6;
  const rows = Math.ceil(brickCount / columns);
  const brickWidth = 92;
  const brickHeight = 24;
  const gap = 14;
  const totalWidth = columns * brickWidth + (columns - 1) * gap;
  const startX = (canvas.width - totalWidth) / 2;
  const palette = ["#f4d35e", "#f08a5d", "#b83b5e", "#6a4c93", "#2a9d8f", "#3a86ff"];
  for (let index = 0; index < brickCount; index += 1) {
    const column = index % columns;
    const row = Math.floor(index / columns);
    bricks.push({
      x: startX + column * (brickWidth + gap) + (random() * 10 - 5),
      y: 54 + row * (brickHeight + gap) + (random() * 12 - 6),
      width: brickWidth,
      height: brickHeight,
      alive: true,
      rotation: random() * 0.18 - 0.09,
      color: palette[index % palette.length],
      label: physicianNames[index % Math.max(1, physicianNames.length)] || `Doc ${index + 1}`,
    });
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
    lives: 3,
    won: false,
    lost: false,
    message: "Konami code unlocked. Break the physician schedule blocks.",
    ballExplosion: null,
    bricks,
    startedAt: performance.now(),
    elapsedMs: 0,
    paddleHits: 0,
    score: 0,
    scoreSubmitted: false,
  };
  state.game = game;

  function updateLiveScore() {
    game.elapsedMs = Math.max(1, performance.now() - game.startedAt);
    game.score = computeBreakoutScore({
      brickCount: game.bricks.length,
      elapsedMs: game.elapsedMs,
      paddleHits: game.paddleHits,
      livesLeft: game.lives,
    });
    renderBreakoutScoreboard(game.score);
  }

  updateLiveScore();
  renderGameStatus(`Lives: ${game.lives} | Score: ${formatBreakoutScore(game.score)} | ${game.message}`);

  function resetBall() {
    game.ballX = canvas.width / 2;
    game.ballY = canvas.height - 70;
    game.ballDx = (random() > 0.5 ? 1 : -1) * 3.6;
    game.ballDy = -4.4;
  }

  function explodeBall() {
    game.ballExplosion = {
      x: game.ballX,
      y: game.ballY,
      radius: 10,
      alpha: 1,
    };
  }

  function updateStatus(message = game.message) {
    game.message = message;
    updateLiveScore();
    renderGameStatus(`Lives: ${game.lives} | Score: ${formatBreakoutScore(game.score)} | ${message}`);
  }

  function bounceOffPaddle() {
    const paddleCenter = game.paddleX + game.paddleWidth / 2;
    const normalizedHit = Math.max(-1, Math.min(1, (game.ballX - paddleCenter) / (game.paddleWidth / 2)));
    const speed = Math.max(5.6, Math.hypot(game.ballDx, game.ballDy));
    const bounceAngle = normalizedHit * (Math.PI * 0.38);
    game.ballDx = speed * Math.sin(bounceAngle);
    game.ballDy = -Math.max(2.8, speed * Math.cos(bounceAngle));
    game.ballY = canvas.height - 39;
    game.paddleHits += 1;
  }

  async function finalizeGame(message) {
    if (game.scoreSubmitted) return;
    game.scoreSubmitted = true;
    updateStatus(message);
    if (game.won) {
      await submitBreakoutScore(game);
    }
  }

  function draw() {
    updateLiveScore();
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#12284b";
    context.fillRect(0, 0, canvas.width, canvas.height);
    for (const brick of bricks) {
      if (!brick.alive) continue;
      context.save();
      context.translate(brick.x + brick.width / 2, brick.y + brick.height / 2);
      context.rotate(brick.rotation);
      context.fillStyle = brick.color;
      context.fillRect(-brick.width / 2, -brick.height / 2, brick.width, brick.height);
      context.strokeStyle = "rgba(255,255,255,0.45)";
      context.strokeRect(-brick.width / 2, -brick.height / 2, brick.width, brick.height);
      context.fillStyle = "#0f1730";
      context.font = "bold 12px Segoe UI";
      context.textAlign = "center";
      context.fillText(String(brick.label).slice(0, 11), 0, 4);
      context.restore();
    }
    context.fillStyle = "#f0c36e";
    context.fillRect(game.paddleX, canvas.height - 30, game.paddleWidth, game.paddleHeight);
    if (game.ballExplosion) {
      context.save();
      context.globalAlpha = game.ballExplosion.alpha;
      context.beginPath();
      context.arc(game.ballExplosion.x, game.ballExplosion.y, game.ballExplosion.radius, 0, Math.PI * 2);
      context.fillStyle = "#ffd166";
      context.fill();
      context.restore();
      game.ballExplosion.radius += 1.8;
      game.ballExplosion.alpha -= 0.06;
      if (game.ballExplosion.alpha <= 0) {
        game.ballExplosion = null;
      }
    } else {
      context.beginPath();
      context.arc(game.ballX, game.ballY, 9, 0, Math.PI * 2);
      context.fillStyle = "#ffffff";
      context.fill();
    }

    context.fillStyle = "rgba(255,255,255,0.9)";
    context.font = "600 14px Segoe UI";
    context.textAlign = "left";
    context.fillText(`Lives ${game.lives}`, 18, 26);
    context.textAlign = "right";
    context.fillText(`Score ${formatBreakoutScore(game.score)}`, canvas.width - 18, 26);

    if (!game.won && !game.lost) {
      if (game.leftPressed) game.paddleX -= 7;
      if (game.rightPressed) game.paddleX += 7;
      game.paddleX = Math.max(0, Math.min(canvas.width - game.paddleWidth, game.paddleX));
      game.ballX += game.ballDx;
      game.ballY += game.ballDy;
      if (game.ballX < 9 || game.ballX > canvas.width - 9) {
        game.ballDx *= -1;
        game.ballX = Math.max(9, Math.min(canvas.width - 9, game.ballX));
      }
      if (game.ballY < 9) {
        game.ballDy *= -1;
        game.ballY = 9;
      }
      const paddleTop = canvas.height - 30;
      const ballTouchesPaddle = (
        game.ballDy > 0
        && game.ballY + 9 >= paddleTop
        && game.ballY - 9 <= paddleTop + game.paddleHeight
        && game.ballX >= game.paddleX
        && game.ballX <= game.paddleX + game.paddleWidth
      );
      if (ballTouchesPaddle) {
        bounceOffPaddle();
      }
      if (game.ballY > canvas.height) {
        game.lives -= 1;
        explodeBall();
        if (game.lives <= 0) {
          game.lost = true;
          finalizeGame("You lost. You need to go see more patients.");
        } else {
          resetBall();
          updateStatus(`Missed it. ${game.lives} ${game.lives === 1 ? "life" : "lives"} left.`);
        }
      }
    }
    for (const brick of bricks) {
      if (!brick.alive || game.won || game.lost) continue;
      if (game.ballX > brick.x && game.ballX < brick.x + brick.width && game.ballY > brick.y && game.ballY < brick.y + brick.height) {
        brick.alive = false;
        game.ballDy *= -1;
      }
    }
    if (bricks.every((brick) => !brick.alive) && !game.won) {
      game.won = true;
      explodeBall();
      burstConfetti();
      finalizeGame("Congratulations! You beat the Emergency Department. You can now take early retirement :)");
    }
    if ((game.won || game.lost) && !game.ballExplosion) {
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
  document.addEventListener("keydown", async (event) => {
    if (!selectionEnabled()) return;
    if (!currentSelectionRange() || activeEditableElement()) return;
    if (event.key === "Enter") {
      event.preventDefault();
      await assignSelectedRange();
      return;
    }
    if (["Delete", "Backspace"].includes(event.key)) {
      event.preventDefault();
      await unassignSelectedRange();
    }
  });
  document.addEventListener("pointerup", () => {
    if (!state.selection.mouseDown) return;
    state.selection.mouseDown = false;
    state.selection.suppressClick = true;
    window.setTimeout(() => {
      state.selection.suppressClick = false;
    }, 0);
  });

  qsa("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.dataset.closeModal));
  });

  qs("#closeGameOverlay")?.addEventListener("click", () => {
    closeModal("gameOverlay");
    destroyGame();
  });

  qs("#settingsButton")?.addEventListener("click", () => openSettingsPanel("appearance"));
  qs("#openRequestModal")?.addEventListener("click", openRequestModalForCreate);
  qs("#openRequestModalInline")?.addEventListener("click", openRequestModalForCreate);
  qs("#openForgotPasswordModal")?.addEventListener("click", () => openModal("forgotPasswordModal"));
  qs("#assignSelectionButton")?.addEventListener("click", assignSelectedRange);
  qs("#unassignSelectionButton")?.addEventListener("click", unassignSelectedRange);
  qs("#userProvisioningManualToggle")?.addEventListener("change", syncUserCreateProvisioningMode);
  qs("#generateUserPasswordButton")?.addEventListener("click", () => {
    const passwordInput = qs('#userCreateForm input[name="password"]');
    const confirmInput = qs('#userCreateForm input[name="confirm_password"]');
    if (!passwordInput) return;
    const generatedPassword = generateTemporaryPassword();
    passwordInput.value = generatedPassword;
    if (confirmInput) confirmInput.value = generatedPassword;
    confirmInput?.dispatchEvent(new Event("input", { bubbles: true }));
    passwordInput.dispatchEvent(new Event("input", { bubbles: true }));
  });
  qsa("[data-settings-section-button]").forEach((button) => {
    button.addEventListener("click", () => setSettingsSection(button.dataset.settingsSectionButton));
  });
  qs('#assistantRequestForm textarea[name="prompt"]')?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
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
      qsa("[data-admin-panel-button]").forEach((node) => node.classList.toggle("active", node === button));
      qsa("[data-admin-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.adminPanel === button.dataset.adminPanelButton));
    });
  });
  qsa("[data-log-kind]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.logs.kind = button.dataset.logKind;
      state.logs.page = 1;
      await loadAdminLogs();
    });
  });
  qs("#exportMonthSelect")?.addEventListener("change", async () => {
    await loadAdminExport();
  });

  document.body.addEventListener("pointerdown", (event) => {
    const dayButton = event.target.closest("[data-day]");
    if (!dayButton || !selectionEnabled() || event.button !== 0) return;
    state.selection.mouseDown = true;
    state.selection.didDrag = false;
    state.selection.anchor = dayButton.dataset.day;
    state.selection.start = dayButton.dataset.day;
    state.selection.end = dayButton.dataset.day;
    syncSelectionHighlights();
    renderSelectionToolbar();
  });
  document.body.addEventListener("pointerover", (event) => {
    const dayButton = event.target.closest("[data-day]");
    if (!dayButton || !selectionEnabled() || !state.selection.mouseDown || !state.selection.anchor) return;
    if (state.selection.end !== dayButton.dataset.day) {
      state.selection.end = dayButton.dataset.day;
      state.selection.didDrag = true;
      syncSelectionHighlights();
      renderSelectionToolbar();
    }
  });

  document.body.addEventListener("click", async (event) => {
    const dayButton = event.target.closest("[data-day]");
    if (dayButton) {
      if (selectionEnabled() && state.selection.suppressClick) {
        state.selection.suppressClick = false;
        return;
      }
      if (selectionEnabled()) {
        setSingleDaySelection(dayButton.dataset.day);
        return;
      }
      await loadDayDetails(dayButton.dataset.day);
      return;
    }
    const miniButton = event.target.closest("[data-mini-date]");
    if (miniButton) {
      if (selectionEnabled()) {
        const [year, month] = miniButton.dataset.miniDate.split("-").map(Number);
        state.year = year;
        state.month = month;
        await loadCalendar();
        setSingleDaySelection(miniButton.dataset.miniDate);
        return;
      }
      await loadDayDetails(miniButton.dataset.miniDate);
      return;
    }
    if (selectionEnabled() && currentSelectionRange() && !event.target.closest("#selectionToolbar, .modal-card, .game-panel")) {
      clearSelection();
    }
    const editRequest = event.target.closest("[data-edit-request]");
    if (editRequest) {
      if (editRequest.closest("#dayModal")) {
        closeModal("dayModal");
      }
      await openRequestModalForEdit(editRequest.dataset.editRequest);
      return;
    }
    const cancelRequest = event.target.closest("[data-cancel-request]");
    if (cancelRequest) {
      const result = await fetchJson(`/api/requests/${cancelRequest.dataset.cancelRequest}/cancel`, { method: "POST" });
      showToast(result.message || "Vacation removed.", "success");
      await Promise.all([loadHistory(), loadCalendar()]);
      return;
    }
    const removeRequestDay = event.target.closest("[data-remove-request-day]");
    if (removeRequestDay) {
      const result = await fetchJson(`/api/requests/${removeRequestDay.dataset.removeRequestDay}/remove-day/${removeRequestDay.dataset.removeDay}`, { method: "POST" });
      showToast(result.message || "Removed that day from the vacation.", "success");
      await Promise.all([loadHistory(), loadCalendar(), loadDayDetails(removeRequestDay.dataset.removeDay)]);
      return;
    }
    const removeDelegation = event.target.closest("[data-remove-delegation]");
    if (removeDelegation) {
      await fetchJson(`/api/delegations/${removeDelegation.dataset.removeDelegation}/delete`, { method: "POST" });
      showToast("Delegate removed.", "success");
      await loadDelegations();
      return;
    }
    const tradeAction = event.target.closest("[data-trade-action]");
    if (tradeAction) {
      const formData = new FormData();
      formData.append("action", tradeAction.dataset.tradeAction);
      await fetchJson(`/api/trades/${tradeAction.dataset.tradeId}/respond`, { method: "POST", body: formData });
      showToast(
        tradeAction.dataset.tradeAction === "accept"
          ? "Trade accepted."
          : tradeAction.dataset.tradeAction === "reject"
            ? "Trade rejected."
            : "Trade offer canceled.",
        "success"
      );
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
      showToast("User access updated.", "success");
      await Promise.all([loadAdminUsers(), refreshSession()]);
      return;
    }
    const deleteUser = event.target.closest("[data-delete-user]");
    if (deleteUser) {
      if (!window.confirm("Delete this user?")) return;
      await fetchJson(`/api/admin/users/${deleteUser.dataset.deleteUser}/delete`, { method: "POST" });
      showToast("User deleted.", "success");
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
      showToast("Holiday deleted.", "success");
      await loadAdminHolidays(Number(qs("#holidayYearFilter")?.value || state.adminHolidaysYear));
      return;
    }
    const logPage = event.target.closest("[data-log-page]");
    if (logPage) {
      state.logs.page = Number(logPage.dataset.logPage || 1);
      await loadAdminLogs();
    }
  });

  qs("#requestForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const requestId = formData.get("request_id");
    let result;
    if (requestId) {
      result = await fetchJson(`/api/requests/${requestId}`, { method: "POST", body: formData });
    } else {
      result = await fetchJson("/api/requests", { method: "POST", body: formData });
    }
    closeModal("requestModal");
    form.reset();
    state.editingRequestId = null;
    await Promise.all([loadCalendar(), loadHistory()]);
    showToast(result.message || "Vacation saved.", /waitlist/i.test(result?.message || "") ? "warning" : "success");
  });

  qs("#assistantRequestForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const responseBox = qs("#assistantResponse");
    try {
      const formData = new FormData(form);
      const result = await fetchJson("/api/requests/assistant", { method: "POST", body: formData });
      if (responseBox) {
        responseBox.textContent = result.message || result.parsed?.explanation || "Vacation scheduled.";
      }
      form.reset();
      closeModal("requestModal");
      await Promise.all([loadCalendar(), loadHistory()]);
      showToast(result.message || result.parsed?.explanation || "Assistant request completed.", /waitlist/i.test(result?.message || "") ? "warning" : "success");
    } catch (error) {
      if (responseBox) {
        responseBox.textContent = error?.message || String(error);
      }
      notifyError(error);
    }
  });

  qs("#settingsForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    formData.set("show_week_numbers", formData.get("show_week_numbers") ? "true" : "false");
    state.weekStart = formData.get("week_start");
    state.showWeekNumbers = formData.get("show_week_numbers") === "true";
    applyTheme(formData.get("theme_skin"));
    const result = await fetchJson("/api/settings", { method: "POST", body: formData });
    closeModal("settingsPanel");
    await loadCalendar();
    showToast(result.message || "Settings updated.", "success");
  });

  qs("#settingsPasswordForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await fetchJson("/api/settings/password", { method: "POST", body: new FormData(form) });
    form.reset();
    resetFormFeedback(form);
    closeModal("settingsPanel");
    showToast(result.message || "Password updated.", "success");
  });

  qs("#delegationForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    await fetchJson("/api/delegations", { method: "POST", body: new FormData(form) });
    form.reset();
    await loadDelegations();
    showToast("Delegate added.", "success");
  });

  qs("#tradeYearSelect")?.addEventListener("change", async (event) => {
    await loadRotationData(event.currentTarget.value);
  });
  qs("#myHolidaySelect")?.addEventListener("change", populateTradeHolidayOptions);
  qs("#tradeTargetUserSelect")?.addEventListener("change", populateTradeHolidayOptions);

  qs("#tradeForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    await fetchJson("/api/trades", { method: "POST", body: new FormData(form) });
    form.reset();
    await Promise.all([loadTrades(), loadRotationData(qs("#tradeYearSelect")?.value || new Date().getFullYear())]);
    showToast("Trade offer sent.", "success");
  });

  qs("#loginForgotPasswordForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await fetchJson("/api/password-reset-request", { method: "POST", body: new FormData(form) });
    form.reset();
    closeModal("forgotPasswordModal");
    showToast(result.message || "Password reset request received.", result.toastType || "info");
  });

  qs("#userCreateForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await fetchJson("/api/admin/users", { method: "POST", body: new FormData(form) });
    form.reset();
    syncUserCreateProvisioningMode();
    resetFormFeedback(form);
    await Promise.all([loadAdminUsers(), refreshSession()]);
    showToast(result.message || "User created.", result.toastType || "success");
  });

  qs("#userEditForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const userId = form.querySelector('[name="user_id"]').value;
    const result = await fetchJson(`/api/admin/users/${userId}`, { method: "POST", body: new FormData(form) });
    closeModal("userModal");
    resetFormFeedback(form);
    await Promise.all([loadAdminUsers(), refreshSession()]);
    showToast(result.message || "User updated.", "success");
  });

  qs("#holidayCreateForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    await fetchJson("/api/admin/holidays", { method: "POST", body: new FormData(form) });
    const year = Number(form.querySelector('[name="year"]').value);
    await Promise.all([loadAdminHolidays(year), loadCalendar()]);
    form.reset();
    showToast("Holiday added.", "success");
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
    showToast("Holiday updated.", "success");
  });

  qs("#reloadHolidayList")?.addEventListener("click", async () => {
    const year = Number(qs("#holidayYearFilter")?.value || state.adminHolidaysYear);
    await loadAdminHolidays(year);
  });

  qs("#loadExportButton")?.addEventListener("click", async () => {
    await loadAdminExport();
  });

  qs("#cancelPendingTradesButton")?.addEventListener("click", async () => {
    const result = await fetchJson("/api/admin/trades/cancel-pending", { method: "POST" });
    await loadTrades();
    showToast(`Canceled ${result.canceledCount || 0} pending trade${result.canceledCount === 1 ? "" : "s"}.`, "success");
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

  applyTheme(state.themeSkin);
  renderBreakoutScoreboard();
  enhancePasswordFields();
  setSettingsSection(state.settings.activeSection);
  qsa(".password-validation-form").forEach(bindPasswordValidation);
  syncUserCreateProvisioningMode();
  enableDraggableModals();
  attachGlobalEvents();
  await refreshSession().catch(() => {});
  populatePhysicianSelects();
  populateDelegationSelect();
  renderSelectionToolbar();
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
