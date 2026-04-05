import os
import re
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "app" / "static" / "screenshots"
BASE_URL = "http://127.0.0.1:5123"
KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a", "Enter"]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True)
        self.server = make_server(host, port, app)

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()


def query_one(db_path: Path, sql: str, params=()):
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(sql, params).fetchone()


def query_all(db_path: Path, sql: str, params=()):
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(sql, params).fetchall()


def seed_logs(db_path: Path, *, actor_user_id: int, count: int = 130):
    with closing(sqlite3.connect(db_path)) as connection:
        for index in range(count):
            connection.execute(
                """
                INSERT INTO activity_log (actor_user_id, event_type, message, entity_type, entity_id, created_at)
                VALUES (?, ?, ?, 'user', ?, CURRENT_TIMESTAMP)
                """,
                (actor_user_id, "playwright-seed", f"Seeded activity entry {index}", actor_user_id),
            )
            connection.execute(
                """
                INSERT INTO change_log (activity_log_id, actor_user_id, entity_type, entity_id, field_name, old_value, new_value, created_at)
                VALUES (NULL, ?, 'user', ?, 'seed_field', ?, ?, CURRENT_TIMESTAMP)
                """,
                (actor_user_id, actor_user_id, f"before-{index}", f"after-{index}"),
            )
        connection.commit()


def wait_for_toast(page, text: str | None = None):
    toast = (
        page.locator("#toastStack .toast").last
        if text is None
        else page.locator("#toastStack .toast").filter(has_text=re.compile(re.escape(text), re.IGNORECASE)).last
    )
    expect(toast).to_be_visible(timeout=8000)
    if text:
        expect(toast).to_contain_text(re.compile(re.escape(text), re.IGNORECASE), timeout=8000)
    return toast.inner_text()


def login(page, username: str, password: str):
    page.goto(f"{BASE_URL}/login")
    page.fill('.auth-card input[name="username"]', username)
    page.fill('.auth-card input[name="password"]', password)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url(f"{BASE_URL}/")
    page.wait_for_timeout(400)


def logout(page):
    page.get_by_role("button", name="Log out").click()
    page.wait_for_url(f"{BASE_URL}/login")
    page.wait_for_timeout(300)


def navigate_mini_to(page, year: int, month: int):
    for _ in range(36):
        current = page.evaluate("() => ({ year: window.__VACATION_SCHEDULER_STATE__.year, month: window.__VACATION_SCHEDULER_STATE__.month })")
        if current["year"] == year and current["month"] == month:
            return
        current_key = current["year"] * 12 + current["month"]
        target_key = year * 12 + month
        page.locator("#miniNext" if current_key < target_key else "#miniPrev").click()
        page.wait_for_timeout(150)
    raise AssertionError(f"Unable to navigate mini calendar to {year}-{month:02d}")


def open_day_from_mini(page, day_iso: str):
    year, month = (int(part) for part in day_iso.split("-")[:2])
    navigate_mini_to(page, year, month)
    page.locator(f'[data-mini-date="{day_iso}"]').click()
    page.wait_for_selector("#dayModal:not(.hidden)")


def open_request_modal(page):
    trigger = page.locator("#openRequestModalInline")
    if trigger.count() == 0 or not trigger.first.is_visible():
        trigger = page.locator("#openRequestModal")
    trigger.first.click()
    page.wait_for_selector("#requestModal:not(.hidden)")


def create_manual_request(page, physician_label: str, start_date: str, end_date: str, note: str, *, expect_toast: str | None = None, expect_error: str | None = None):
    open_request_modal(page)
    if page.locator("#requestPhysicianField").is_visible():
        page.select_option("#requestPhysicianSelect", label=physician_label)
    page.fill('#requestForm input[name="start_date"]', start_date)
    page.fill('#requestForm input[name="end_date"]', end_date)
    page.fill('#requestForm textarea[name="request_note"]', note)
    page.get_by_role("button", name="Save vacation").click()
    if expect_error:
        wait_for_toast(page, expect_error)
        expect(page.locator("#requestModal:not(.hidden)")).to_be_visible()
        return
    page.wait_for_selector("#requestModal.hidden", state="attached")
    if expect_toast:
        wait_for_toast(page, expect_toast)


def submit_assistant_request(page, physician_label: str, prompt: str, *, expect_toast: str | None = None):
    open_request_modal(page)
    if page.locator("#assistantPhysicianField").is_visible():
        page.select_option("#assistantPhysicianSelect", label=physician_label)
    page.fill('#assistantRequestForm textarea[name="prompt"]', prompt)
    page.get_by_role("button", name="Add vacation").click()
    page.wait_for_selector("#requestModal.hidden", state="attached")
    if expect_toast:
        wait_for_toast(page, expect_toast)


def submit_assistant_request_with_error(page, physician_label: str, prompt: str, expected_error: str):
    open_request_modal(page)
    if page.locator("#assistantPhysicianField").is_visible():
        page.select_option("#assistantPhysicianSelect", label=physician_label)
    page.fill('#assistantRequestForm textarea[name="prompt"]', prompt)
    page.get_by_role("button", name="Add vacation").click()
    expect(page.locator("#requestModal:not(.hidden)")).to_be_visible()
    expect(page.locator("#assistantResponse")).to_contain_text(re.compile(re.escape(expected_error), re.IGNORECASE))
    wait_for_toast(page, expected_error)


def create_trade(page, note: str, *, year: str, my_holiday_key: str, target_user_id: str, target_holiday_key: str):
    page.select_option("#tradeYearSelect", year)
    page.select_option("#myHolidaySelect", my_holiday_key)
    page.select_option("#tradeTargetUserSelect", target_user_id)
    page.wait_for_timeout(250)
    page.select_option("#tradeTargetHolidaySelect", target_holiday_key)
    page.fill('#tradeForm textarea[name="note"]', note)
    page.get_by_role("button", name="Send trade offer").click()
    wait_for_toast(page, "Trade offer sent.")
    page.reload()
    page.wait_for_timeout(600)


def drag_select_dates(page, start_day: str, end_day: str):
    start = page.locator(f'[data-day="{start_day}"]').first
    end = page.locator(f'[data-day="{end_day}"]').first
    start.hover()
    start.dispatch_event("pointerdown", {"button": 0})
    end.hover()
    page.locator("body").dispatch_event("pointerup")
    page.wait_for_timeout(250)


def main():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "playwright_e2e.db"
        os.environ["DATABASE_PATH"] = str(db_path)
        os.environ["SECRET_KEY"] = "playwright-secret"
        os.environ.setdefault("ZEN_API_KEY", "")
        os.environ["SMTP_HOST"] = ""
        os.environ["GMAIL_CLIENT_ID"] = ""
        os.environ["GMAIL_CLIENT_SECRET"] = ""
        os.environ["GMAIL_REFRESH_TOKEN"] = ""

        from app import create_app

        app = create_app()
        server = ServerThread(app, "127.0.0.1", 5123)
        server.start()

        try:
            admin_user = query_one(db_path, "SELECT id, username FROM users WHERE username = 'admin'")
            assert admin_user is not None
            seed_logs(db_path, actor_user_id=admin_user["id"])

            physician_rows = query_all(
                db_path,
                """
                SELECT id, username, full_name, email
                FROM users
                WHERE role = 'physician'
                ORDER BY full_name COLLATE NOCASE ASC
                """,
            )
            afifi_user = query_one(db_path, "SELECT id, username, full_name, email FROM users WHERE username = 'afifi'")
            waitlist_physicians = physician_rows[:8]
            assert len(waitlist_physicians) == 8
            afifi_major = query_one(
                db_path,
                """
                SELECT hra.holiday_key, hra.holiday_title
                FROM holiday_rotation_assignments hra
                JOIN users u ON u.id = hra.user_id
                WHERE hra.year = 2026 AND hra.category = 'major' AND u.username = 'afifi'
                ORDER BY hra.holiday_key ASC
                LIMIT 1
                """,
            )
            trade_target = query_one(
                db_path,
                """
                SELECT u.id, u.username, u.full_name, u.email, hra.holiday_key, hra.holiday_title
                FROM holiday_rotation_assignments hra
                JOIN users u ON u.id = hra.user_id
                WHERE hra.year = 2026
                  AND hra.category = 'major'
                  AND u.username <> 'afifi'
                  AND hra.holiday_key <> ?
                ORDER BY u.full_name COLLATE NOCASE ASC
                LIMIT 1
                """,
                (afifi_major["holiday_key"],),
            )
            assert afifi_major is not None
            assert trade_target is not None
            assert afifi_user is not None

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 960})
                page = context.new_page()
                page.add_init_script(
                    """
                    class MockSpeechRecognition {
                      start() {
                        this.onstart?.();
                        setTimeout(() => {
                          this.onresult?.({ results: [[{ transcript: "schedule vacation by voice" }]] });
                          this.onend?.();
                        }, 50);
                      }
                      stop() {
                        this.onend?.();
                      }
                    }
                    window.SpeechRecognition = MockSpeechRecognition;
                    window.webkitSpeechRecognition = MockSpeechRecognition;
                    """
                )

                page.goto(f"{BASE_URL}/login")
                expect(page.locator(".topbar")).to_have_count(0)
                expect(page.locator(".brand")).to_have_count(0)
                expect(page.get_by_text("Open the standalone reset page")).to_have_count(0)
                expect(page.locator('.auth-card input[name="password"]')).to_have_attribute("type", "password")
                expect(page.locator(".password-toggle svg").first).to_be_visible()
                toggle_styles = page.evaluate(
                    """
                    () => {
                      const styles = getComputedStyle(document.querySelector('.password-toggle'));
                      return { borderTopWidth: styles.borderTopWidth, backgroundColor: styles.backgroundColor };
                    }
                    """
                )
                assert toggle_styles["borderTopWidth"] == "0px", toggle_styles
                page.locator(".password-toggle").first.click()
                expect(page.locator('.auth-card input[name="password"]')).to_have_attribute("type", "text")
                page.locator(".password-toggle").first.click()
                expect(page.locator('.auth-card input[name="password"]')).to_have_attribute("type", "password")

                page.goto(f"{BASE_URL}/holiday-rotation")
                expect(page.locator(".year-toggle-button.active")).to_have_text("2026")
                expect(page.get_by_role("link", name="2028")).to_be_visible()

                page.set_viewport_size({"width": 1280, "height": 760})
                page.goto(f"{BASE_URL}/")
                page.wait_for_selector("#calendarMount .day-cell")
                expect(page.locator(".topbar")).to_have_count(0)
                expect(page.locator("#openRequestModal")).to_have_count(0)
                expect(page.locator(".calendar-utility-bar")).to_contain_text("South Bay ED VL Schedule")
                expect(page.locator(".calendar-utility-bar")).not_to_contain_text("Live Schedule")
                expect(page.locator(".sidebar-links").get_by_role("link", name="South Bay ED VL Schedule")).to_be_visible()
                mini_prev_box = page.locator("#miniPrev").bounding_box()
                mini_prev_year_box = page.locator("#miniPrevYear").bounding_box()
                mini_next_box = page.locator("#miniNext").bounding_box()
                mini_next_year_box = page.locator("#miniNextYear").bounding_box()
                assert mini_prev_box is not None and mini_prev_year_box is not None
                assert mini_next_box is not None and mini_next_year_box is not None
                assert mini_prev_year_box["y"] < mini_prev_box["y"]
                assert mini_next_year_box["y"] < mini_next_box["y"]
                assert page.locator("#miniCalendarLabel .mini-calendar-year").is_visible()
                mini_font_sizes = page.evaluate(
                    """
                    () => {
                      const year = getComputedStyle(document.querySelector('#miniCalendarLabel .mini-calendar-year')).fontSize;
                      const month = getComputedStyle(document.querySelector('#miniCalendarLabel .mini-calendar-month')).fontSize;
                      return { year: parseFloat(year), month: parseFloat(month) };
                    }
                    """
                )
                assert mini_font_sizes["month"] > mini_font_sizes["year"], mini_font_sizes
                weekday_height = page.locator(".weekday-label").first.bounding_box()
                assert weekday_height is not None
                assert weekday_height["height"] <= 22, weekday_height
                home_fit = page.evaluate(
                    "() => ({ scrollHeight: document.documentElement.scrollHeight, innerHeight: window.innerHeight })"
                )
                assert home_fit["scrollHeight"] <= home_fit["innerHeight"] + 8, home_fit
                layout_match = page.evaluate(
                    """
                    () => {
                      const sidebar = document.querySelector('.sidebar')?.getBoundingClientRect();
                      const calendar = document.querySelector('.calendar-shell')?.getBoundingClientRect();
                      return {
                        sidebarBottom: sidebar?.bottom ?? 0,
                        calendarBottom: calendar?.bottom ?? 0,
                      };
                    }
                    """
                )
                assert abs(layout_match["sidebarBottom"] - layout_match["calendarBottom"]) <= 12, layout_match
                page.locator("#nextMonth").click()
                expect(page.locator(".day-cell.is-holiday", has_text="Memorial Day").first).to_be_visible()
                expect(page.locator(".day-cell.is-holiday", has_text="Memorial Day").first.locator(".slot-pill")).to_have_count(0)
                page.goto(f"{BASE_URL}/instructions")
                page.wait_for_selector(".screenshot-grid")
                page.goto(f"{BASE_URL}/")
                page.wait_for_selector("#calendarMount .day-cell")
                page.screenshot(path=str(SCREENSHOT_DIR / "home.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 960})

                login(page, "admin", "Admin123!")
                for path, heading in [
                    ("/history", "Vacation history"),
                    ("/holiday-rotation", "Guaranteed holiday time off"),
                    ("/legacy-calendars", "Legacy VL calendars"),
                    ("/instructions", "Instructions"),
                    ("/vacation-guidelines", "Vacation guidelines"),
                    ("/admin", "Admin console"),
                ]:
                    page.goto(f"{BASE_URL}{path}")
                    expect(page.locator(".topbar")).to_have_count(0)
                    expect(page.locator(".page-utility-bar")).to_be_visible()
                    expect(page.locator(".subpage-hero-panel")).to_be_visible()
                    expect(page.locator(".subpage-hero-panel h1")).to_contain_text(heading)
                    header_styles = page.evaluate(
                        """
                        () => ({
                          utilityBar: getComputedStyle(document.querySelector('.page-utility-bar')).backgroundImage,
                          hero: getComputedStyle(document.querySelector('.subpage-hero-panel')).backgroundImage,
                          sidebarTop: document.querySelector('.sidebar')?.getBoundingClientRect().top ?? null,
                          utilityTop: document.querySelector('.page-utility-bar')?.getBoundingClientRect().top ?? null,
                        })
                        """
                    )
                    assert "gradient" in header_styles["utilityBar"].lower(), header_styles
                    assert "gradient" in header_styles["hero"].lower(), header_styles
                    assert header_styles["sidebarTop"] is not None and header_styles["utilityTop"] is not None
                    assert abs(header_styles["sidebarTop"] - header_styles["utilityTop"]) <= 8, header_styles
                page.goto(f"{BASE_URL}/admin")
                page.get_by_role("button", name="Users", exact=True).click()
                expect(page.locator(".admin-user-group-title", has_text="Admin accounts")).to_be_visible()
                expect(page.locator(".admin-user-group", has_text="Scheduler Admin")).to_be_visible()
                expect(page.locator('input[name="annual_day_limit"]')).to_have_count(0)
                expect(page.locator("#userCreateForm")).not_to_contain_text("annual VL day limit")
                admin_padding = page.evaluate(
                    """
                    () => {
                      const panel = document.querySelector('[data-admin-panel="users"]')?.getBoundingClientRect();
                      const heading = document.querySelector('[data-admin-panel="users"] h2')?.getBoundingClientRect();
                      return { offset: panel && heading ? heading.left - panel.left : 0 };
                    }
                    """
                )
                assert admin_padding["offset"] >= 18, admin_padding
                user_form_width = page.locator('#userCreateForm input[name="full_name"]').bounding_box()
                assert user_form_width is not None
                assert user_form_width["width"] < 420
                expect(page.locator("#userProvisioningManualToggle")).not_to_be_checked()
                expect(page.locator("#userCreatePasswordField")).to_be_hidden()
                expect(page.locator("#userCreateConfirmPasswordField")).to_be_hidden()

                page.fill('#userCreateForm input[name="full_name"]', "Playwright Admin")
                page.fill('#userCreateForm input[name="username"]', "padmin")
                page.fill('#userCreateForm input[name="email"]', "padmin@example.com")
                page.locator("#userProvisioningManualToggle").check()
                expect(page.locator("#userCreatePasswordField")).to_be_visible()
                expect(page.locator("#userCreateConfirmPasswordField")).to_be_visible()
                page.fill('#userCreateForm input[name="password"]', "AdminEdge123!")
                page.fill('#userCreateForm input[name="confirm_password"]', "AdminEdge123!")
                page.select_option('#userCreateForm select[name="role"]', "admin")
                page.get_by_role("button", name="Create user").click()
                wait_for_toast(page, "manually set password")
                admin_row = page.locator(".admin-user-row", has_text="Playwright Admin")
                expect(admin_row).to_be_visible()
                admin_row.get_by_role("button", name="Edit / reset password").click()
                page.wait_for_selector("#userModal:not(.hidden)")
                page.fill('#userEditForm input[name="password"]', "AdminEdge999!")
                page.fill('#userEditForm input[name="confirm_password"]', "AdminEdge999!")
                page.get_by_role("button", name="Save user").click()
                wait_for_toast(page, "Updated Playwright Admin.")

                page.fill('#userCreateForm input[name="full_name"]', "Playwright Doctor")
                page.fill('#userCreateForm input[name="username"]', "pdoctor")
                page.fill('#userCreateForm input[name="email"]', "pdoctor@example.com")
                page.select_option('#userCreateForm select[name="role"]', "physician")
                page.get_by_role("button", name="Create user").click()
                wait_for_toast(page, "password setup email was not sent")
                expect(page.locator("#adminUsers")).to_contain_text("Playwright Doctor")
                created_user_email = query_one(
                    db_path,
                    "SELECT recipient, purpose, delivery_status FROM email_log WHERE recipient = ? ORDER BY id DESC LIMIT 1",
                    ("pdoctor@example.com",),
                )
                assert created_user_email is not None
                assert created_user_email["purpose"] == "new-user-reset-link"
                assert created_user_email["delivery_status"] == "logged-only"

                page.fill('#userCreateForm input[name="full_name"]', "Delete Doctor")
                page.fill('#userCreateForm input[name="username"]', "delete_doc")
                page.fill('#userCreateForm input[name="email"]', "delete_doc@example.com")
                page.locator("#userProvisioningManualToggle").check()
                expect(page.locator("#userCreatePasswordField")).to_be_visible()
                expect(page.locator("#userCreateConfirmPasswordField")).to_be_visible()
                generated_password = page.locator('#userCreateForm input[name="password"]').input_value()
                assert generated_password == ""
                page.get_by_role("button", name="Generate random password").click()
                regenerated_password = page.locator('#userCreateForm input[name="password"]').input_value()
                regenerated_confirm = page.locator('#userCreateForm input[name="confirm_password"]').input_value()
                assert len(regenerated_password) >= 12
                assert regenerated_password == regenerated_confirm
                page.get_by_role("button", name="Create user").click()
                wait_for_toast(page, "manually set password")
                delete_row = page.locator(".admin-user-row", has_text="Delete Doctor")
                expect(delete_row).to_be_visible()
                page.evaluate("() => { window.confirm = () => true; }")
                delete_row.get_by_role("button", name="Delete").click()
                wait_for_toast(page, "User deleted.")
                expect(page.locator(".admin-user-row", has_text="Delete Doctor")).to_have_count(0)
                page.fill('#userCreateForm input[name="full_name"]', "Delete Doctor Recreated")
                page.fill('#userCreateForm input[name="username"]', "delete_doc")
                page.fill('#userCreateForm input[name="email"]', "delete_doc@example.com")
                page.locator("#userProvisioningManualToggle").check()
                page.get_by_role("button", name="Generate random password").click()
                page.get_by_role("button", name="Create user").click()
                wait_for_toast(page, "manually set password")
                expect(page.locator(".admin-user-row", has_text="Delete Doctor Recreated")).to_be_visible()

                pdoctor_row = page.locator(".admin-user-row", has_text="Playwright Doctor")
                pdoctor_row.get_by_role("button", name="Edit / reset password").click()
                page.wait_for_selector("#userModal:not(.hidden)")
                header_box = page.locator("#userModal .modal-header").bounding_box()
                assert header_box is not None
                page.mouse.move(header_box["x"] + 20, header_box["y"] + 20)
                page.mouse.down()
                page.mouse.move(header_box["x"] + 120, header_box["y"] + 80, steps=12)
                page.mouse.up()
                drag_x = page.locator("#userModal .modal-card").evaluate("el => el.style.getPropertyValue('--drag-x')")
                assert drag_x not in ("", "0px")
                page.fill('#userEditForm input[name="password"]', "AdminReset123!")
                page.fill('#userEditForm input[name="confirm_password"]', "AdminReset123!")
                page.get_by_role("button", name="Save user").click()
                wait_for_toast(page, "Updated Playwright Doctor.")
                page.screenshot(path=str(SCREENSHOT_DIR / "admin.png"), full_page=True)

                page.get_by_role("button", name="Holidays", exact=True).click()
                page.fill('#holidayCreateForm input[name="title"]', "Smoke Holiday")
                page.fill('#holidayCreateForm input[name="year"]', "2026")
                page.select_option('#holidayCreateForm select[name="category"]', "minor")
                page.fill('#holidayCreateForm input[name="start_date"]', "2026-08-17")
                page.fill('#holidayCreateForm input[name="end_date"]', "2026-08-18")
                page.get_by_role("button", name="Add holiday").click()
                wait_for_toast(page, "Holiday added.")
                expect(page.locator("#adminHolidays")).to_contain_text("Smoke Holiday")

                page.goto(f"{BASE_URL}/")
                page.wait_for_selector("#calendarMount .day-cell")
                navigate_mini_to(page, 2026, 8)
                expect(page.locator(".day-cell.is-holiday", has_text="Smoke Holiday").first).to_be_visible()
                expect(page.locator(".day-cell.is-holiday", has_text="Smoke Holiday").first.locator(".slot-pill")).to_have_count(0)

                page.goto(f"{BASE_URL}/admin")
                page.get_by_role("button", name="Holidays", exact=True).click()
                page.locator(".history-item", has_text="Smoke Holiday").get_by_role("button", name="Edit").click()
                page.wait_for_selector("#holidayModal:not(.hidden)")
                page.fill('#holidayEditForm input[name="title"]', "Updated Smoke Holiday")
                page.get_by_role("button", name="Save holiday").click()
                wait_for_toast(page, "Holiday updated.")
                expect(page.locator("#adminHolidays")).to_contain_text("Updated Smoke Holiday")

                page.goto(f"{BASE_URL}/")
                page.wait_for_selector("#calendarMount .day-cell")
                navigate_mini_to(page, 2026, 8)
                expect(page.locator(".day-cell.is-holiday", has_text="Updated Smoke Holiday").first).to_be_visible()

                page.goto(f"{BASE_URL}/admin")
                page.get_by_role("button", name="Holidays", exact=True).click()
                page.evaluate("() => { window.confirm = () => true; }")
                page.locator(".history-item", has_text="Updated Smoke Holiday").get_by_role("button", name="Delete").click()
                wait_for_toast(page, "Holiday deleted.")
                expect(page.locator(".history-item", has_text="Updated Smoke Holiday")).to_have_count(0)

                logout(page)
                login(page, "padmin", "AdminEdge999!")
                expect(page.locator(".calendar-utility-bar")).to_contain_text("padmin")
                logout(page)
                login(page, "pdoctor", "AdminReset123!")
                logout(page)

                page.get_by_role("button", name="Forgot password?").click()
                page.wait_for_selector("#forgotPasswordModal:not(.hidden)")
                page.fill('#loginForgotPasswordForm input[name="identifier"]', "pdoctor")
                page.get_by_role("button", name="Send reset link").click()
                wait_for_toast(page, "password reset link was generated")
                expect(page.locator("#forgotPasswordModal")).to_be_hidden()
                token_row = query_one(db_path, "SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1")
                password_reset_email = query_one(
                    db_path,
                    "SELECT recipient, purpose, delivery_status FROM email_log WHERE purpose = 'password-reset' AND recipient = ? ORDER BY id DESC LIMIT 1",
                    ("pdoctor@example.com",),
                )
                assert token_row is not None
                assert password_reset_email is not None
                assert password_reset_email["delivery_status"] == "logged-only"
                page.goto(f"{BASE_URL}/reset-password/{token_row['token']}")
                page.fill('.auth-card input[name="password"]', "Reset12345!")
                page.fill('.auth-card input[name="confirm_password"]', "Reset12345!")
                page.get_by_role("button", name="Update password").click()
                page.wait_for_url(f"{BASE_URL}/login")

                login(page, "pdoctor", "Reset12345!")
                page.locator("#settingsButton").click()
                page.wait_for_selector("#settingsPanel:not(.hidden)")
                expect(page.locator('[data-settings-section="appearance"]')).to_be_visible()
                expect(page.locator('[data-settings-section="password"]')).to_be_hidden()
                settings_metrics = page.evaluate(
                    """
                    () => {
                      const card = document.querySelector('#settingsPanel .settings-card');
                      const rect = card.getBoundingClientRect();
                      const maxRight = [...card.querySelectorAll('*')]
                        .filter((el) => !el.hidden && getComputedStyle(el).display !== 'none')
                        .reduce((value, el) => Math.max(value, el.getBoundingClientRect().right), rect.right);
                      return {
                        width: rect.width,
                        height: rect.height,
                        scrollHeight: card.scrollHeight,
                        clientHeight: card.clientHeight,
                        overflowRight: maxRight - rect.right,
                      };
                    }
                    """
                )
                assert settings_metrics["scrollHeight"] <= settings_metrics["clientHeight"] + 2, settings_metrics
                assert settings_metrics["overflowRight"] <= 2, settings_metrics
                assert page.locator(".theme-option").count() >= 21
                page.locator(".theme-option", has_text="Paper Garden").click()
                page.get_by_role("button", name="Save settings").click()
                wait_for_toast(page, "Settings updated.")
                expect(page.locator("body")).to_have_attribute("data-theme-selection", "paper-garden")

                page.locator("#settingsButton").click()
                page.wait_for_selector("#settingsPanel:not(.hidden)")
                page.get_by_role("tab", name="Appearance").click()
                page.locator(".theme-option", has_text="Random").click()
                page.get_by_role("button", name="Save settings").click()
                wait_for_toast(page, "Settings updated.")
                expect(page.locator("body")).to_have_attribute("data-theme-selection", "random")
                assert page.locator("body").get_attribute("data-theme") != "random"

                page.locator("#settingsButton").click()
                page.wait_for_selector("#settingsPanel:not(.hidden)")
                page.get_by_role("tab", name="Password").click()
                expect(page.locator('[data-settings-section="appearance"]')).to_be_hidden()
                expect(page.locator('[data-settings-section="password"]')).to_be_visible()
                password_settings_metrics = page.evaluate(
                    """
                    () => {
                      const card = document.querySelector('#settingsPanel .settings-card');
                      const form = document.querySelector('#settingsPasswordForm');
                      const rect = card.getBoundingClientRect();
                      const formRect = form.getBoundingClientRect();
                      const maxRight = [...card.querySelectorAll('*')]
                        .filter((el) => !el.hidden && getComputedStyle(el).display !== 'none')
                        .reduce((value, el) => Math.max(value, el.getBoundingClientRect().right), rect.right);
                      return {
                        width: rect.width,
                        height: rect.height,
                        formHeight: formRect.height,
                        scrollHeight: card.scrollHeight,
                        clientHeight: card.clientHeight,
                        overflowRight: maxRight - rect.right,
                      };
                    }
                    """
                )
                assert abs(password_settings_metrics["width"] - settings_metrics["width"]) < 2, password_settings_metrics
                assert abs(password_settings_metrics["height"] - settings_metrics["height"]) < 2, password_settings_metrics
                assert password_settings_metrics["formHeight"] < password_settings_metrics["height"] * 0.82, password_settings_metrics
                assert password_settings_metrics["scrollHeight"] <= password_settings_metrics["clientHeight"] + 2, password_settings_metrics
                assert password_settings_metrics["overflowRight"] <= 2, password_settings_metrics
                page.fill('#settingsPasswordForm input[name="current_password"]', "Reset12345!")
                page.fill('#settingsPasswordForm input[name="new_password"]', "Self12345!")
                page.fill('#settingsPasswordForm input[name="confirm_password"]', "Wrong12345!")
                expect(page.locator('#settingsPasswordForm .password-toggle svg').nth(1)).to_be_visible()
                page.get_by_role("button", name="Update password").click()
                expect(page.locator("#settingsPasswordForm [data-password-feedback]")).to_contain_text("Passwords do not match.")
                page.fill('#settingsPasswordForm input[name="confirm_password"]', "Self12345!")
                page.get_by_role("button", name="Update password").click()
                wait_for_toast(page, "Password updated.")
                logout(page)
                login(page, "pdoctor", "Self12345!")

                page.goto(f"{BASE_URL}/history")
                open_request_modal(page)
                expect(page.locator("#requestPhysicianField")).to_be_hidden()
                expect(page.locator("#assistantPhysicianField")).to_be_hidden()
                expect(page.locator("#dictateButton")).to_have_count(0)
                expect(page.get_by_role("button", name="Add vacation")).to_be_visible()
                page.locator('#assistantRequestForm textarea[name="prompt"]').fill("Schedule afifi off 2026-10-02 to 2026-10-03")
                page.locator('#assistantRequestForm textarea[name="prompt"]').press("Enter")
                expect(page.locator("#requestModal:not(.hidden)")).to_be_visible()
                wait_for_toast(page, "permission to add vacation")
                expect(page.locator("#assistantResponse")).to_contain_text("permission to add vacation")
                page.locator('#requestModal [data-close-modal="requestModal"]').click()

                page.select_option("#delegationSelect", str(afifi_user["id"]))
                page.get_by_role("button", name="Add delegate").click()
                wait_for_toast(page, "Delegate added.")
                expect(page.locator("#ownedDelegations")).to_contain_text(afifi_user["full_name"])

                page.goto(f"{BASE_URL}/")
                navigate_mini_to(page, 2026, 10)
                page.locator('[data-day="2026-10-20"]').click()
                expect(page.locator("#dayModal")).to_be_hidden()
                expect(page.locator("#selectionToolbar")).to_be_visible()
                expect(page.locator("#clearSelectionButton")).to_have_count(0)
                expect(page.locator("#selectionLabel")).to_contain_text("2026-10-20")
                toolbar_position = page.evaluate(
                    """
                    () => {
                      const toolbar = document.querySelector('#selectionToolbar')?.getBoundingClientRect();
                      const mount = document.querySelector('#calendarMount')?.getBoundingClientRect();
                      return { toolbarBottom: toolbar?.bottom ?? 0, mountTop: mount?.top ?? 0 };
                    }
                    """
                )
                assert toolbar_position["toolbarBottom"] <= toolbar_position["mountTop"], toolbar_position
                pre_drag_state = page.evaluate(
                    """
                    () => ({
                      toolbarHeight: document.querySelector('#selectionToolbar')?.getBoundingClientRect().height ?? 0,
                      mountTop: document.querySelector('#calendarMount')?.getBoundingClientRect().top ?? 0,
                    })
                    """
                )
                drag_select_dates(page, "2026-10-20", "2026-10-22")
                expect(page.locator("#selectionToolbar")).to_be_visible()
                expect(page.locator("#selectionLabel")).to_contain_text("2026-10-20 to 2026-10-22")
                post_drag_state = page.evaluate(
                    """
                    () => ({
                      toolbarHeight: document.querySelector('#selectionToolbar')?.getBoundingClientRect().height ?? 0,
                      mountTop: document.querySelector('#calendarMount')?.getBoundingClientRect().top ?? 0,
                    })
                    """
                )
                assert abs(post_drag_state["mountTop"] - pre_drag_state["mountTop"]) <= 1, {"before": pre_drag_state, "after": post_drag_state}
                assert post_drag_state["toolbarHeight"] <= 34, post_drag_state
                page.locator("#calendarTitle").click()
                expect(page.locator("#selectionToolbar")).to_be_hidden()
                page.locator('[data-day="2026-10-20"]').click()
                expect(page.locator("#selectionToolbar")).to_be_visible()
                drag_select_dates(page, "2026-10-20", "2026-10-22")
                expect(page.locator("#selectionLabel")).to_contain_text("2026-10-20 to 2026-10-22")
                page.keyboard.press("Enter")
                wait_for_toast(page, "Vacation scheduled.")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-10-20 to 2026-10-22")

                page.goto(f"{BASE_URL}/")
                navigate_mini_to(page, 2026, 10)
                drag_select_dates(page, "2026-10-21", "2026-10-21")
                page.get_by_role("button", name="Unassign me", exact=True).click()
                wait_for_toast(page, "Removed the selected range")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-10-20")
                expect(page.locator("#historyList")).to_contain_text("2026-10-22")

                page.goto(f"{BASE_URL}/")
                navigate_mini_to(page, 2026, 10)
                drag_select_dates(page, "2026-10-20", "2026-10-22")
                page.keyboard.press("Delete")
                wait_for_toast(page, "Removed the selected range")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator(".history-item", has_text="2026-10-20").locator(".status")).to_have_text("canceled")
                expect(page.locator(".history-item", has_text="2026-10-22").locator(".status")).to_have_text("canceled")

                submit_assistant_request(page, "Playwright Doctor", "Schedule Playwright Doctor off 2026-10-05 to 2026-10-07 for conference", expect_toast="Vacation scheduled.")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-10-05 to 2026-10-07")

                submit_assistant_request_with_error(page, "Playwright Doctor", "Please sort that doctor out sometime later", "usable date")
                page.locator('#requestModal [data-close-modal="requestModal"]').click()

                create_manual_request(page, "Playwright Doctor", "2027-05-01", "2027-05-02", "Too far ahead", expect_error="1 year in advance")
                page.locator('#requestModal [data-close-modal="requestModal"]').click()
                submit_assistant_request_with_error(page, "Playwright Doctor", "Schedule Playwright Doctor off 2027-05-01 to 2027-05-02", "1 year in advance")
                page.locator('#requestModal [data-close-modal="requestModal"]').click()

                submit_assistant_request(page, "Playwright Doctor", "Move Playwright Doctor vacation from 2026-10-05 to 2026-10-07 to 2026-10-08 to 2026-10-10", expect_toast="Vacation updated.")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-10-08 to 2026-10-10")

                submit_assistant_request(page, "Playwright Doctor", "Remove 2026-10-09 from Playwright Doctor vacation on 2026-10-08 to 2026-10-10")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-10-08")
                expect(page.locator("#historyList")).to_contain_text("2026-10-10")

                submit_assistant_request(page, "Playwright Doctor", "Delete Playwright Doctor vacation on 2026-10-10")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-10-08")

                create_manual_request(page, "Playwright Doctor", "2026-11-10", "2026-11-12", "Delegated removal range", expect_toast="Vacation scheduled.")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-11-10 to 2026-11-12")

                create_manual_request(page, "Playwright Doctor", "2026-12-23", "2026-12-24", "Holiday block", expect_error="protected holiday")
                page.locator('#requestModal [data-close-modal="requestModal"]').click()

                logout(page)
                login(page, "afifi", "ChangeMe123!")
                open_request_modal(page)
                expect(page.locator("#requestPhysicianField")).to_be_visible()
                expect(page.locator("#assistantPhysicianField")).to_be_visible()
                page.locator('#requestModal [data-close-modal="requestModal"]').click()

                submit_assistant_request(page, "Playwright Doctor", "Remove 2026-11-11 from Playwright Doctor vacation on 2026-11-10 to 2026-11-12")
                page.goto(f"{BASE_URL}/history")
                expect(page.locator("#historyList")).to_contain_text("2026-11-10")
                expect(page.locator("#historyList")).to_contain_text("2026-11-12")

                create_trade(
                    page,
                    "Cancel this offer",
                    year="2026",
                    my_holiday_key=afifi_major["holiday_key"],
                    target_user_id=str(trade_target["id"]),
                    target_holiday_key=trade_target["holiday_key"],
                )
                trade_offer_email = query_one(
                    db_path,
                    "SELECT recipient, purpose, delivery_status FROM email_log WHERE purpose = 'holiday-trade-offer' AND recipient = ? ORDER BY id DESC LIMIT 1",
                    (trade_target["email"],),
                )
                assert trade_offer_email is not None
                assert trade_offer_email["delivery_status"] == "logged-only"
                cancel_offer_row = page.locator(".trade-row", has_text="Cancel this offer")
                expect(cancel_offer_row).to_be_visible()
                cancel_offer_row.get_by_role("button", name="Cancel offer").click()
                wait_for_toast(page, "Trade offer canceled.")
                expect(cancel_offer_row).to_contain_text("canceled")

                create_trade(
                    page,
                    "Admin bulk cancel",
                    year="2026",
                    my_holiday_key=afifi_major["holiday_key"],
                    target_user_id=str(trade_target["id"]),
                    target_holiday_key=trade_target["holiday_key"],
                )
                expect(page.locator(".trade-row", has_text="Admin bulk cancel")).to_contain_text("pending")
                logout(page)

                login(page, "admin", "Admin123!")
                page.goto(f"{BASE_URL}/admin")
                page.locator('[data-admin-panel-button="schedule"]').click()
                page.get_by_role("button", name="Cancel all pending").click()
                wait_for_toast(page, "Canceled 1 pending trade")
                expect(page.locator("#adminTrades")).to_contain_text("Admin bulk cancel")
                expect(page.locator(".trade-row", has_text="Admin bulk cancel")).to_contain_text("canceled")

                waitlist_day = "2026-09-10"
                for index, physician in enumerate(waitlist_physicians[:6], start=1):
                    create_manual_request(page, physician["full_name"], waitlist_day, waitlist_day, f"Fill slot {index}", expect_toast="Vacation scheduled.")

                create_manual_request(page, waitlist_physicians[6]["full_name"], waitlist_day, waitlist_day, "Waitlist first physician", expect_toast="waitlisted")
                create_manual_request(page, waitlist_physicians[7]["full_name"], waitlist_day, waitlist_day, "Waitlist second physician", expect_toast="waitlisted")
                page.goto(f"{BASE_URL}/admin")
                page.locator('[data-admin-panel-button="schedule"]').click()
                expect(page.locator("#adminWaitlist")).to_contain_text(waitlist_physicians[6]["full_name"])
                expect(page.locator("#adminWaitlist")).to_contain_text(waitlist_physicians[7]["full_name"])
                expect(page.locator(".history-item.waitlist-card", has_text=waitlist_physicians[6]["full_name"])).to_contain_text("waitlisted")

                page.goto(f"{BASE_URL}/")
                page.wait_for_selector("#calendarMount .day-cell")
                navigate_mini_to(page, 2026, 9)
                expect(page.locator(f'[data-day="{waitlist_day}"] .slot-pill.occupied')).to_have_count(6)
                visibility = page.evaluate(
                    """
                    ({ day, openDay }) => {
                      const cell = document.querySelector(`[data-day="${day}"]`);
                      const openCell = document.querySelector(`[data-day="${openDay}"]`);
                      const slots = [...cell.querySelectorAll('.slot-pill.occupied')];
                      const openSlots = [...openCell.querySelectorAll('.slot-pill')];
                      const cellRect = cell.getBoundingClientRect();
                      const lastSlot = slots.at(-1)?.getBoundingClientRect();
                      return {
                        count: slots.length,
                        clipped: slots.some((slot) => slot.getBoundingClientRect().bottom > cellRect.bottom + 0.5),
                        bottomGap: lastSlot ? cellRect.bottom - lastSlot.bottom : null,
                        openHeights: openSlots.map((slot) => slot.getBoundingClientRect().height),
                      };
                    }
                    """,
                    {"day": waitlist_day, "openDay": "2026-09-11"},
                )
                assert visibility["count"] == 6
                assert not visibility["clipped"], visibility
                assert visibility["bottomGap"] is not None and 4 <= visibility["bottomGap"] <= 22, visibility
                assert max(visibility["openHeights"]) - min(visibility["openHeights"]) < 1.5, visibility
                expect(page.locator(f'[data-day="{waitlist_day}"] .waitlist-badge')).to_have_text("W2")

                open_day_from_mini(page, waitlist_day)
                expect(page.locator("#dayModalContent")).to_contain_text("Waitlist")
                page.locator('[data-edit-request]').first.click()
                page.wait_for_selector("#requestModal:not(.hidden)")
                expect(page.locator('#requestForm input[name="start_date"]')).to_have_value(waitlist_day)
                page.locator('#requestModal [data-close-modal="requestModal"]').click()
                open_day_from_mini(page, waitlist_day)
                page.locator('[data-remove-request-day]').first.click()
                wait_for_toast(page, f"Removed {waitlist_day} from the vacation schedule.")
                page.locator('[data-close-modal="dayModal"]').click()

                page.goto(f"{BASE_URL}/admin")
                page.locator('[data-admin-panel-button="schedule"]').click()
                expect(page.locator(".history-item", has_text=waitlist_physicians[6]["full_name"])).to_contain_text("scheduled")
                expect(page.locator(".history-item.waitlist-card", has_text=waitlist_physicians[7]["full_name"])).to_contain_text("waitlisted")

                page.goto(f"{BASE_URL}/")
                open_day_from_mini(page, waitlist_day)
                page.locator('[data-remove-request-day]').first.click()
                wait_for_toast(page, f"Removed {waitlist_day} from the vacation schedule.")
                page.locator('[data-close-modal="dayModal"]').click()

                page.goto(f"{BASE_URL}/admin")
                page.locator('[data-admin-panel-button="schedule"]').click()
                expect(page.locator(".history-item", has_text=waitlist_physicians[7]["full_name"])).to_contain_text("scheduled")
                promoted_waitlist_email = query_one(
                    db_path,
                    "SELECT recipient, purpose, delivery_status FROM email_log WHERE purpose = 'waitlist-promoted' AND recipient = ? ORDER BY id DESC LIMIT 1",
                    (waitlist_physicians[6]["email"],),
                )
                assert promoted_waitlist_email is not None
                assert promoted_waitlist_email["delivery_status"] == "logged-only"

                page.get_by_role("button", name="Logs", exact=True).click()
                expect(page.locator("#logTable")).to_contain_text("Seeded activity entry")
                page_two_button = page.locator("#logPagination").get_by_role("button", name="2", exact=True)
                expect(page_two_button).to_be_visible()
                page_two_button.click()
                expect(page.locator('#logPagination .pagination-button.active')).to_have_text("2")
                page.get_by_role("button", name="Detailed change log").click()
                page.locator("#logPagination").get_by_role("button", name="1", exact=True).click()
                expect(page.locator("#logTable")).to_contain_text("Field")
                expect(page.locator("#logTable")).to_contain_text("Old")
                expect(page.locator("#logTable")).to_contain_text("New")
                expect(page.locator("#logTable")).to_contain_text("delivery_provider")
                assert query_one(db_path, "SELECT 1 FROM change_log WHERE field_name = 'source_prompt' LIMIT 1") is not None
                assert query_one(db_path, "SELECT 1 FROM change_log WHERE field_name = 'assistant_parser_mode' LIMIT 1") is not None
                assistant_prompt_log = query_one(
                    db_path,
                    "SELECT new_value FROM change_log WHERE field_name = 'source_prompt' AND new_value LIKE ? ORDER BY id DESC LIMIT 1",
                    ("%Please sort that doctor out sometime later%",),
                )
                assert assistant_prompt_log is not None

                page.goto(f"{BASE_URL}/legacy-calendars?year=2024")
                page.wait_for_selector(".legacy-table")

                page.goto(f"{BASE_URL}/admin")
                page.get_by_role("button", name="Export", exact=True).click()
                page.select_option("#exportMonthSelect", "9")
                page.get_by_role("button", name="Load table").click()
                page.wait_for_selector(".export-table")
                expect(page.locator(".export-table thead th")).to_have_count(31)
                export_wrap_box = page.locator("#exportTable").bounding_box()
                assert export_wrap_box is not None
                assert export_wrap_box["width"] <= 1400
                with page.expect_download() as download_info:
                    page.get_by_role("link", name="Download CSV").click()
                assert download_info.value.suggested_filename.endswith(".csv")
                logout(page)

                login(page, "afifi", "ChangeMe123!")
                page.goto(f"{BASE_URL}/history")
                create_trade(
                    page,
                    "Accept this offer",
                    year="2026",
                    my_holiday_key=afifi_major["holiday_key"],
                    target_user_id=str(trade_target["id"]),
                    target_holiday_key=trade_target["holiday_key"],
                )
                logout(page)

                login(page, trade_target["username"], "ChangeMe123!")
                page.goto(f"{BASE_URL}/history")
                accept_offer_row = page.locator(".trade-row", has_text="Accept this offer")
                accept_offer_row.get_by_role("button", name="Accept").click()
                wait_for_toast(page, "Trade accepted.")
                expect(page.locator(".trade-row", has_text="Accept this offer")).to_contain_text("accepted")
                page.goto(f"{BASE_URL}/holiday-rotation")
                expect(page.locator(".year-toggle-button.active")).to_have_text("2026")
                expect(page.locator(".rotation-column", has_text=trade_target["holiday_title"]).locator(f"text={afifi_user['full_name']}")).to_be_visible()

                page.goto(f"{BASE_URL}/")
                for key in KONAMI:
                    page.keyboard.press(key)
                page.wait_for_selector("#gameOverlay:not(.hidden)")
                assert page.evaluate("() => window.__VACATION_SCHEDULER_STATE__.game.lives") == 3
                assert page.evaluate("() => window.__VACATION_SCHEDULER_STATE__.game.bricks[0].label") != "VL"
                expect(page.locator("#gameHighScoreValue")).to_be_visible()
                page.evaluate(
                    """
                    () => {
                      const game = window.__VACATION_SCHEDULER_STATE__.game;
                      const gold = game.bricks.find((brick) => brick.isGolden);
                      game.ballX = gold.x + gold.width / 2;
                      game.ballY = gold.y + gold.height / 2;
                      game.ballDx = 0.4;
                      game.ballDy = 2.4;
                    }
                    """
                )
                page.wait_for_function("() => window.__VACATION_SCHEDULER_STATE__.game.balls.length === 3", timeout=10000)
                page.evaluate(
                    """
                    () => {
                      const game = window.__VACATION_SCHEDULER_STATE__.game;
                      game.paddleX = 280;
                      game.ballX = game.paddleX + game.paddleWidth / 2;
                      game.ballY = 381;
                      game.ballDx = 1.8;
                      game.ballDy = 4.4;
                    }
                    """
                )
                page.wait_for_timeout(160)
                center_velocity = page.evaluate(
                    "() => ({ dx: window.__VACATION_SCHEDULER_STATE__.game.ballDx, dy: window.__VACATION_SCHEDULER_STATE__.game.ballDy })"
                )
                assert abs(center_velocity["dx"]) < 1.2, center_velocity
                assert center_velocity["dy"] < 0, center_velocity
                page.evaluate(
                    """
                    () => {
                      const game = window.__VACATION_SCHEDULER_STATE__.game;
                      game.paddleX = 280;
                      game.ballX = game.paddleX + 8;
                      game.ballY = 381;
                      game.ballDx = 1.6;
                      game.ballDy = 4.4;
                    }
                    """
                )
                page.wait_for_timeout(160)
                edge_velocity = page.evaluate(
                    "() => ({ dx: window.__VACATION_SCHEDULER_STATE__.game.ballDx, dy: window.__VACATION_SCHEDULER_STATE__.game.ballDy })"
                )
                assert edge_velocity["dx"] < -1.2, edge_velocity
                assert edge_velocity["dy"] < 0, edge_velocity
                page.evaluate(
                    """
                    () => {
                      const game = window.__VACATION_SCHEDULER_STATE__.game;
                      const activeBallCount = Math.max(1, game.balls.length);
                      game.lives = activeBallCount;
                      game.balls = game.balls.map((ball, index) => ({
                        ...ball,
                        y: 999 + index * 12,
                        dy: Math.abs(ball.dy || 4.4),
                      }));
                    }
                    """
                )
                page.wait_for_function(
                    "() => (document.querySelector('#gameStatus')?.textContent || '').includes('You lost. You need to go see more patients.')",
                    timeout=10000,
                )
                page.get_by_role("button", name="Close").click()
                expect(page.locator("#gameOverlay")).to_be_hidden()

                for key in KONAMI:
                    page.keyboard.press(key)
                page.wait_for_selector("#gameOverlay:not(.hidden)")
                page.evaluate(
                    """
                    () => {
                      const game = window.__VACATION_SCHEDULER_STATE__.game;
                      game.startedAt = performance.now() - 1200;
                      game.paddleHits = 1;
                      game.lives = 3;
                      game.bricks.forEach((brick) => { brick.alive = false; });
                    }
                    """
                )
                page.wait_for_function(
                    "() => (document.querySelector('#gameHighScoreValue')?.textContent || '') !== 'No score yet'",
                    timeout=10000,
                )
                expect(page.locator("#confettiLayer .confetti-piece")).to_have_count(56)
                breakout_row = query_one(
                    db_path,
                    "SELECT score, elapsed_ms, paddle_hits FROM breakout_scores bs JOIN users u ON u.id = bs.user_id WHERE u.username = ?",
                    (trade_target["username"],),
                )
                assert breakout_row is not None
                assert breakout_row["score"] > 0
                page.get_by_role("button", name="Close").click()
                expect(page.locator("#gameOverlay")).to_be_hidden()

                page.goto(f"{BASE_URL}/history")
                page.wait_for_function(
                    "() => Boolean(window.__VACATION_SCHEDULER_STATE__?.session?.gameHighScore)",
                    timeout=10000,
                )
                for key in KONAMI:
                    page.keyboard.press(key)
                page.wait_for_selector("#gameOverlay:not(.hidden)")
                expect(page.locator("#gameHighScoreValue")).not_to_have_text("No score yet")
                expect(page.locator("#gameHighScoreUser")).to_contain_text(trade_target["full_name"])

                browser.close()
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
