import os
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


def login(page, username: str, password: str):
    page.goto("http://127.0.0.1:5123/login")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url("http://127.0.0.1:5123/")
    page.wait_for_timeout(1000)


def logout(page):
    page.get_by_role("button", name="Log out").click()
    page.wait_for_url("http://127.0.0.1:5123/")


def main():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "playwright_e2e.db"
        os.environ["DATABASE_PATH"] = str(db_path)
        os.environ["SECRET_KEY"] = "playwright-secret"
        os.environ["ZEN_API_KEY"] = ""
        os.environ["SMTP_HOST"] = ""

        from app import create_app

        app = create_app()
        server = ServerThread(app, "127.0.0.1", 5123)
        server.start()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()

                page.goto("http://127.0.0.1:5123/")
                page.wait_for_selector("#calendarMount .day-cell")
                page.screenshot(path=str(SCREENSHOT_DIR / "home.png"), full_page=True)

                login(page, "admin", "Admin123!")
                page.goto("http://127.0.0.1:5123/admin")
                page.get_by_role("button", name="Users", exact=True).click()
                page.fill('#userCreateForm input[name="full_name"]', "Playwright Doctor")
                page.fill('#userCreateForm input[name="username"]', "pdoctor")
                page.fill('#userCreateForm input[name="email"]', "pdoctor@example.com")
                page.fill('#userCreateForm input[name="password"]', "Play12345!")
                page.fill('#userCreateForm input[name="annual_day_limit"]', "12")
                page.get_by_role("button", name="Create user").click()
                page.wait_for_timeout(1000)
                page.reload()
                page.wait_for_timeout(1000)
                page.get_by_role("button", name="Users", exact=True).click()
                page.locator("#adminUsers").get_by_text("Playwright Doctor").wait_for()
                page.screenshot(path=str(SCREENSHOT_DIR / "admin.png"), full_page=True)

                page.get_by_role("button", name="Schedule", exact=True).click()
                page.locator("#openRequestModal").click()
                page.wait_for_selector("#requestModal:not(.hidden)")
                page.select_option("#requestPhysicianSelect", label="Playwright Doctor")
                page.fill('#requestForm input[name="start_date"]', "2026-08-17")
                page.fill('#requestForm input[name="end_date"]', "2026-08-19")
                page.fill('#requestForm textarea[name="request_note"]', "Admin created test entry")
                page.get_by_role("button", name="Save vacation").click()
                page.wait_for_timeout(1000)
                page.reload()
                page.wait_for_timeout(1000)
                page.get_by_role("button", name="Schedule", exact=True).click()
                page.locator("#adminRequests").get_by_text("Playwright Doctor").wait_for()

                logout(page)
                page.goto("http://127.0.0.1:5123/forgot-password")
                page.fill('input[name="identifier"]', "pdoctor")
                page.get_by_role("button", name="Send reset link").click()
                page.wait_for_url("http://127.0.0.1:5123/login")
                token_row = query_one(db_path, "SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1")
                assert token_row is not None, "expected password reset token"
                page.goto(f"http://127.0.0.1:5123/reset-password/{token_row['token']}")
                page.fill('input[name="password"]', "Reset12345!")
                page.fill('input[name="confirm_password"]', "Reset12345!")
                page.get_by_role("button", name="Update password").click()
                page.wait_for_url("http://127.0.0.1:5123/login")

                login(page, "pdoctor", "Reset12345!")
                page.goto("http://127.0.0.1:5123/history")
                page.wait_for_timeout(1000)
                page.select_option("#delegationSelect", label="Afifi")
                page.get_by_role("button", name="Add delegate").click()
                page.wait_for_timeout(1000)
                page.reload()
                page.wait_for_timeout(1000)
                page.locator("#ownedDelegations").get_by_text("Afifi").wait_for()

                page.locator("#openRequestModal").click()
                page.wait_for_selector("#requestModal:not(.hidden)")
                page.select_option("#assistantPhysicianSelect", label="Playwright Doctor")
                page.fill('#assistantRequestForm textarea[name="prompt"]', "Schedule Playwright Doctor off 2026-10-05 to 2026-10-07 for conference")
                page.get_by_role("button", name="Parse and schedule").click()
                page.wait_for_timeout(1000)
                page.reload()
                page.wait_for_timeout(1000)
                page.get_by_text("2026-10-05 to 2026-10-07", exact=True).wait_for()

                with page.expect_event("dialog") as dialog_info:
                    page.locator("#openRequestModal").click()
                    page.wait_for_selector("#requestModal:not(.hidden)")
                    page.select_option("#requestPhysicianSelect", label="Playwright Doctor")
                    page.fill('#requestForm input[name="start_date"]', "2026-12-23")
                    page.fill('#requestForm input[name="end_date"]', "2026-12-24")
                    page.get_by_role("button", name="Save vacation").click()
                dialog = dialog_info.value
                assert "protected holiday" in dialog.message.lower()
                dialog.accept()
                page.locator('#requestModal [data-close-modal="requestModal"]').click()

                logout(page)
                login(page, "afifi", "ChangeMe123!")
                page.goto("http://127.0.0.1:5123/history")
                page.wait_for_timeout(1000)
                target_row = query_one(
                    db_path,
                    """
                    SELECT u.username, u.full_name, hra.user_id
                    FROM holiday_rotation_assignments hra
                    JOIN users u ON u.id = hra.user_id
                    WHERE hra.year = 2026 AND hra.holiday_key = 'christmas'
                    LIMIT 1
                    """,
                )
                assert target_row is not None, "expected christmas assignment"
                page.select_option("#tradeYearSelect", "2026")
                page.select_option("#myHolidaySelect", "thanksgiving")
                page.select_option("#tradeTargetUserSelect", str(target_row["user_id"]))
                page.wait_for_timeout(300)
                page.select_option("#tradeTargetHolidaySelect", "christmas")
                page.fill('#tradeForm textarea[name="note"]', "Playwright trade test")
                page.get_by_role("button", name="Send trade offer").click()
                page.wait_for_timeout(1000)
                page.reload()
                page.wait_for_timeout(1000)
                page.locator("#tradeList").get_by_text("Playwright trade test").wait_for()

                logout(page)
                login(page, target_row["username"], "ChangeMe123!")
                page.goto("http://127.0.0.1:5123/history")
                page.wait_for_timeout(1000)
                page.get_by_role("button", name="Accept").click()
                page.wait_for_timeout(1000)
                page.reload()
                page.wait_for_timeout(1000)
                page.locator("#tradeList").get_by_text("accepted").wait_for()
                page.goto("http://127.0.0.1:5123/holiday-rotation?year=2026")
                expect(page.locator(".rotation-column").filter(has_text="Christmas").locator("text=Afifi")).to_be_visible()

                page.goto("http://127.0.0.1:5123/legacy-calendars?year=2024")
                page.wait_for_selector(".legacy-table")

                logout(page)
                login(page, "admin", "Admin123!")
                page.goto("http://127.0.0.1:5123/admin")
                page.wait_for_timeout(1000)
                page.get_by_role("button", name="Export", exact=True).click()
                page.get_by_role("button", name="Load table").click()
                page.wait_for_selector(".export-table")
                with page.expect_download() as download_info:
                    page.get_by_role("link", name="Download CSV").click()
                download = download_info.value
                assert download.suggested_filename.endswith(".csv")

                page.goto("http://127.0.0.1:5123/")
                for key in KONAMI:
                    page.keyboard.press(key)
                page.wait_for_function(
                    "() => (document.querySelector('#gameStatus')?.textContent || '').includes('Congradulations!')",
                    timeout=10000,
                )

                browser.close()
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
