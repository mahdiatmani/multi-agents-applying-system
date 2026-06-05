import threading
import sys
import json
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
import os

thread_local = threading.local()
state_lock = threading.Lock()

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "browser_state.json")


def _display_available() -> bool:
    if sys.platform != "linux":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def has_valid_session() -> bool:
    try:
        if not os.path.exists(STATE_FILE):
            return False
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for cookie in data.get("cookies", []):
            if cookie.get("name") == "li_at" and cookie.get("value"):
                return True
        return False
    except Exception:
        return False


def do_manual_login(username: str, password: str, timeout_ms: int = 120000) -> tuple[bool, str]:
    print("[BrowserManager] Starting manual login flow with visible browser...")

    try:
        pw = sync_playwright().start()
    except Exception as e:
        return False, f"Playwright failed to start: {e}. Run 'playwright install chromium' first."

    browser = None
    try:
        browser = pw.chromium.launch(headless=False)
    except Exception as e:
        pw.stop()
        error_msg = str(e)
        if "Executable doesn't exist" in error_msg or "browserType.launch" in error_msg:
            return False, f"Chromium browser not found. Please run: playwright install chromium\n\nFull error: {error_msg}"
        if "Missing X server" in error_msg or "DISPLAY" in error_msg:
            return False, "Cannot open browser window — no display available. If running in Docker, use the login_helper.py script on your host machine instead."
        return False, f"Browser failed to launch: {error_msg}"

    try:
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        try:
            page.wait_for_selector("#username", timeout=10000)
            if username:
                page.fill("#username", username)
            if password:
                page.fill("#password", password)
        except Exception:
            pass

        try:
            page.wait_for_url("**/feed**", timeout=timeout_ms)
            print("[BrowserManager] Login successful! Saving session...")
        except Exception:
            current = page.url
            if any(path in current for path in ["/feed", "/mynetwork", "/jobs", "/messaging", "/in/"]):
                print(f"[BrowserManager] Login successful (landed on {current}). Saving session...")
            else:
                print(f"[BrowserManager] Login may have failed. Current URL: {current}")
                browser.close()
                pw.stop()
                return False, f"Login not completed. Browser ended at: {current}. Please try again and complete the login within 2 minutes."

        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        context.storage_state(path=STATE_FILE)

        browser.close()
        pw.stop()

        if has_valid_session():
            print("[BrowserManager] Session saved with valid li_at cookie!")
            return True, "Login successful! Session saved with valid LinkedIn session cookie."
        else:
            print("[BrowserManager] WARNING: Session saved but no li_at cookie found.")
            return True, "Session saved, but no li_at cookie detected. The bot may still fail to authenticate. Try logging in again."

    except Exception as e:
        print(f"[BrowserManager] Manual login error: {e}")
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        pw.stop()
        return False, f"Login error: {str(e)}"


class BrowserManager:
    def __new__(cls, headless: bool = True):
        existing = getattr(thread_local, "instance", None)
        if existing is not None:
            if existing.headless != headless:
                # Caller asked for a different mode — replace cleanly.
                existing.close()
            else:
                return existing
        instance = super().__new__(cls)
        instance._init_browser(headless)
        thread_local.instance = instance
        return instance

    def _init_browser(self, headless: bool):
        self.playwright = sync_playwright().start()

        if not headless and not _display_available():
            print("[BrowserManager] WARNING: No display detected — forcing headless=True")
            headless = True

        self.headless = headless
        self.browser: Browser = self.playwright.chromium.launch(headless=headless)

        context_args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 720},
        }

        with state_lock:
            if os.path.exists(STATE_FILE):
                context_args["storage_state"] = STATE_FILE
                print(f"[BrowserManager] Loading saved session (valid={has_valid_session()})")

        self.context: BrowserContext = self.browser.new_context(**context_args)

        # Clipboard read/write is required for the post-permalink fallback in
        # tools/post_extractor.resolve_post_url_via_dialog — it clicks LinkedIn's
        # 'Copy link to post' button in the share dialog and reads the URL back
        # via navigator.clipboard.readText(). Granted only on linkedin.com.
        try:
            self.context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.linkedin.com",
            )
        except Exception as exc:
            print(f"[BrowserManager] clipboard permission grant failed: {exc}", flush=True)

        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        self.page: Page = self.context.new_page()

    def get_page(self) -> Page:
        return self.page

    def save_state(self):
        with state_lock:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            self.context.storage_state(path=STATE_FILE)

    def close(self):
        for closer in (self.save_state, self.context.close, self.browser.close, self.playwright.stop):
            try:
                closer()
            except Exception:
                pass
        if getattr(thread_local, "instance", None) is self:
            del thread_local.instance
