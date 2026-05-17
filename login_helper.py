"""
LinkedIn Login Helper
=====================
Run this script DIRECTLY on your Windows machine (not in Docker) to log in to LinkedIn.
A browser window will open — log in, solve any CAPTCHAs, and wait until you see the feed.
The session will be saved so the bot can use it headlessly.

Usage:
    python login_helper.py
"""

import os
import sys
import json

def main():
    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("[!] python-dotenv not installed. Reading .env manually...")
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip()

    username = os.getenv("LINKEDIN_USERNAME", "")
    password = os.getenv("LINKEDIN_PASSWORD", "")

    if not username:
        print("[!] No LINKEDIN_USERNAME found in .env")
        username = input("Enter LinkedIn email: ").strip()
    if not password:
        print("[!] No LINKEDIN_PASSWORD found in .env")
        password = input("Enter LinkedIn password: ").strip()

    # Check playwright is installed
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n[ERROR] Playwright is not installed.")
        print("Run these commands first:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    state_path = os.path.join(os.path.dirname(__file__), "state", "browser_state.json")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)

    print("\n" + "=" * 60)
    print("  LinkedIn Login Helper")
    print("=" * 60)
    print(f"\n  Account: {username}")
    print(f"  State file: {state_path}")
    print("\n  A browser window will open now.")
    print("  1. Complete the login (solve CAPTCHA if needed)")
    print("  2. Wait until you see your LinkedIn feed")
    print("  3. The window will close automatically")
    print("  4. Then restart the bot — it will use the saved session")
    print("\n" + "=" * 60)
    print()

    pw = sync_playwright().start()

    try:
        browser = pw.chromium.launch(headless=False)
    except Exception as e:
        error = str(e)
        if "Executable doesn't exist" in error:
            print("[ERROR] Chromium not installed. Run: playwright install chromium")
        else:
            print(f"[ERROR] Failed to launch browser: {error}")
        pw.stop()
        sys.exit(1)

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720},
    )

    # Anti-bot stealth
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
    """)

    page = context.new_page()
    
    print("[*] Navigating to LinkedIn login...")
    page.goto("https://www.linkedin.com/login")

    # Pre-fill credentials
    try:
        page.wait_for_selector("#username", timeout=10000)
        if username:
            page.fill("#username", username)
        if password:
            page.fill("#password", password)
        print("[*] Credentials pre-filled. Complete the login in the browser window.")
    except Exception:
        print("[*] Could not pre-fill credentials. Please enter them manually.")

    # Wait for login — 5 minutes timeout
    print("[*] Waiting for you to complete login (5 minute timeout)...")
    
    auth_paths = ["/feed", "/mynetwork", "/jobs", "/messaging", "/in/", "/notifications"]
    
    try:
        page.wait_for_url("**/feed**", timeout=300000)  # 5 minutes
        print("[OK] Login detected! Saving session...")
    except Exception:
        current = page.url
        if any(path in current for path in auth_paths):
            print(f"[OK] Login detected at {current}! Saving session...")
        else:
            print(f"\n[FAIL] Login timed out. Current URL: {current}")
            print("    Please try again.")
            browser.close()
            pw.stop()
            sys.exit(1)

    # Save state
    context.storage_state(path=state_path)
    
    # Verify li_at cookie
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        cookie_names = [c["name"] for c in cookies]
        has_li_at = "li_at" in cookie_names
        
        print(f"\n[*] Saved {len(cookies)} cookies")
        print(f"[*] li_at session cookie: {'YES - FOUND' if has_li_at else 'NO - NOT FOUND'}")
        
        if has_li_at:
            print(f"\n{'=' * 60}")
            print("  SUCCESS! Session saved to: state/browser_state.json")
            print("  You can now start the bot — it will use this session.")
            print(f"{'=' * 60}")
        else:
            print("\n[!] WARNING: No li_at cookie found. Login may not have fully completed.")
            print("[!] The bot might not be able to authenticate. Try logging in again.")
    except Exception as e:
        print(f"[!] Could not verify cookies: {e}")

    browser.close()
    pw.stop()

if __name__ == "__main__":
    main()
