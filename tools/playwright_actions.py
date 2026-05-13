import time
import random
import urllib.parse
from playwright.sync_api import Page

AUTH_PATHS = ("/feed", "/mynetwork", "/jobs", "/messaging", "/in/", "/notifications")


def random_sleep(min_sec=3, max_sec=7):
    time.sleep(random.uniform(min_sec, max_sec))


def _is_authenticated_url(url: str) -> bool:
    return any(path in url for path in AUTH_PATHS)


def _visible(locator) -> bool:
    try:
        return locator.is_visible(timeout=500)
    except Exception:
        return False


def _text(locator) -> str:
    if not _visible(locator):
        return ""
    try:
        return (locator.inner_text() or "").strip()
    except Exception:
        return ""


def login_if_needed(page: Page, username, password):
    print("[Login] Checking if already logged in via saved session...")
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        random_sleep(2, 4)
    except Exception as e:
        print(f"[Login] Navigation error: {e}")

    if _is_authenticated_url(page.url):
        print(f"[Login] Already logged in! Current URL: {page.url}")
        return True

    print("[Login] Not logged in. Attempting credential-based login...")
    try:
        if "/login" not in page.url and "/checkpoint" not in page.url:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
            random_sleep(2, 4)

        username_field = page.locator("#username")
        if _visible(username_field):
            username_field.fill(username)
            random_sleep(1, 3)

        password_field = page.locator("#password")
        if _visible(password_field):
            password_field.fill(password)
            random_sleep(1, 3)

        submit_btn = page.locator("button[type='submit']")
        if _visible(submit_btn):
            submit_btn.click()
            random_sleep(5, 10)

        try:
            page.wait_for_url("**/feed**", timeout=90000)
            print(f"[Login] Login successful! URL: {page.url}")
            return True
        except Exception:
            if _is_authenticated_url(page.url):
                print(f"[Login] Login successful (redirected to {page.url})")
                return True

            current_url = page.url
            if "/checkpoint" in current_url:
                print(f"[Login] BLOCKED: LinkedIn security challenge at {current_url}")
                print("[Login] TIP: Use the 'Login to LinkedIn' button in the UI to log in manually first.")
            elif "/login" in current_url:
                print("[Login] FAILED: Still on login page. Credentials may be incorrect.")
            else:
                print(f"[Login] FAILED: Ended up at unexpected URL: {current_url}")
            return False

    except Exception as e:
        print(f"[Login] Error during login: {e}")
        print(f"[Login] Current URL: {page.url}")
        return False


def search_jobs(page: Page, query: str, locations: list, workplace_types: list, start: int = 0):
    q = urllib.parse.quote(query)

    loc_str = ", ".join(locations) if locations else "Worldwide"
    loc = urllib.parse.quote(loc_str)

    wt_map = {"On-site": "1", "Remote": "2", "Hybrid": "3"}
    wt_vals = [wt_map[wt] for wt in workplace_types if wt in wt_map]
    wt_param = f"&f_WT={'%2C'.join(wt_vals)}" if wt_vals else ""
    start_param = f"&start={start}" if start else ""

    url = f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}&f_AL=true{wt_param}{start_param}"
    page.goto(url)
    random_sleep(4, 8)

    for _ in range(3):
        page.mouse.wheel(0, 500)
        random_sleep(1, 2)

    return page.url


def _first_nonempty(page: Page, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            text = _text(page.locator(sel).first)
            if text:
                return text
        except Exception:
            continue
    return ""


def get_job_details(page: Page) -> dict:
    details: dict = {}
    try:
        title_text = _first_nonempty(page, [
            "h1.job-details-jobs-unified-top-card__job-title",
            ".job-details-jobs-unified-top-card__job-title",
            ".job-details-jobs-unified-top-card__content-title",
            "h1.t-24",
            ".jobs-unified-top-card__job-title",
            ".job-card-container__title",
        ])
        if title_text and title_text.lower() != "linkedin":
            details["title"] = title_text

        company_text = _first_nonempty(page, [
            ".job-details-jobs-unified-top-card__company-name a",
            ".job-details-jobs-unified-top-card__company-name",
            ".jobs-unified-top-card__company-name a",
            ".jobs-unified-top-card__company-name",
            ".job-details-jobs-unified-top-card__primary-description-container a",
            "a[data-test-app-aware-link][href*='/company/']",
        ])
        if company_text:
            details["company"] = company_text.splitlines()[0].strip()

        primary = _first_nonempty(page, [
            ".job-details-jobs-unified-top-card__primary-description-container",
            ".job-details-jobs-unified-top-card__primary-description",
            ".jobs-unified-top-card__primary-description",
            ".job-details-jobs-unified-top-card__tertiary-description-container",
        ])
        if primary:
            # LinkedIn packs "Company · Location · posted X days ago · N applicants" here.
            parts = [p.strip() for p in primary.replace("·", "•").split("•") if p.strip()]
            company_lc = (details.get("company") or "").lower()
            location_candidates = [p for p in parts if p.lower() != company_lc
                                   and not any(w in p.lower() for w in ("applicant", "ago", "posted", "promoted", "viewer"))]
            if location_candidates:
                details["location"] = location_candidates[0]
            elif parts:
                details["location"] = parts[-1]

        desc_text = _first_nonempty(page, [
            "div.jobs-description__content",
            ".jobs-description-content__text",
            "article.jobs-description__container",
            "article",
        ])
        if desc_text:
            details["description"] = desc_text
    except Exception as e:
        print(f"Error getting job details: {e}", flush=True)
    return details


def search_people(page: Page, company: str, keywords: str):
    q = urllib.parse.quote(f"{keywords} {company}")
    url = f"https://www.linkedin.com/search/results/people/?keywords={q}"
    page.goto(url)
    random_sleep(4, 8)
    return page.url


def extract_profile_details(page: Page) -> dict:
    details = {"name": "", "headline": "", "about": "", "experience": ""}
    try:
        details["name"] = _text(page.locator("h1.text-heading-xlarge").first)
        details["headline"] = _text(page.locator("div.text-body-medium.break-words").first)
        details["about"] = _text(page.locator("div#about ~ div.display-flex").first)
        details["experience"] = _text(page.locator("div#experience ~ div.display-flex").first)
    except Exception as e:
        print(f"Error extracting profile details: {e}")
    return details


def search_posts(page: Page, query: str):
    q = urllib.parse.quote(query)
    url = f"https://www.linkedin.com/search/results/content/?keywords={q}"
    page.goto(url)
    random_sleep(4, 8)
    return page.url


def extract_post_details(page: Page) -> dict:
    details = {"author": "", "content": ""}
    try:
        post_el = page.locator(".feed-shared-update-v2").first
        if _visible(post_el):
            details["author"] = _text(post_el.locator(".update-components-actor__name").first)
            details["content"] = _text(post_el.locator(".update-components-text").first)
    except Exception as e:
        print(f"Error extracting post details: {e}")
    return details


_CONNECT_LABELS = ("Connect", "Se connecter", "Conectar", "Vernetzen", "Collegati", "Conectar-se")
_MORE_LABELS = ("More actions", "Plus", "Más", "Mas", "Mehr", "Altro", "Mais")
_SEND_NO_NOTE_LABELS = ("Send without a note", "Envoyer sans note", "Enviar sin nota", "Ohne Nachricht senden", "Invia senza nota", "Enviar sem nota")
_SEND_LABELS = ("Send invitation", "Send", "Envoyer l'invitation", "Envoyer", "Enviar invitación", "Enviar", "Einladung senden", "Senden", "Invia invito", "Invia")
_MESSAGE_LABELS = ("Message", "Envoyer un message", "Mensaje", "Nachricht", "Messaggio", "Mensagem")
_PENDING_LABELS = ("Pending", "En attente", "Pendiente", "Ausstehend", "In attesa", "Pendente")


def go_to_profile(page: Page, profile_url: str) -> bool:
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        random_sleep(2, 4)
        return True
    except Exception as e:
        print(f"[Profile] navigation error for {profile_url}: {e}", flush=True)
        return False


def _click_first_visible_button(page: Page, labels) -> bool:
    for name in labels:
        try:
            btn = page.get_by_role("button", name=name).first
            if _visible(btn):
                btn.click()
                return True
        except Exception:
            continue
    return False


def send_empty_connection(page: Page, profile_url: str) -> tuple[bool, str]:
    """Visit a profile and send a Connect request without a note. Returns (success, reason)."""
    if not go_to_profile(page, profile_url):
        return False, "navigation_failed"
    try:
        # Direct Connect button first
        clicked = _click_first_visible_button(page, _CONNECT_LABELS)
        if not clicked:
            # Fall back to "More actions" dropdown
            if not _click_first_visible_button(page, _MORE_LABELS):
                return False, "no_connect_or_more_button"
            random_sleep(1, 2)
            for name in _CONNECT_LABELS:
                try:
                    item = page.locator("div.artdeco-dropdown__content").get_by_text(name).first
                    if _visible(item):
                        item.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                return False, "connect_not_in_dropdown"
        random_sleep(2, 4)

        # Modal: prefer "Send without a note", else any "Send"
        if _click_first_visible_button(page, _SEND_NO_NOTE_LABELS):
            random_sleep(2, 3)
            return True, ""
        if _click_first_visible_button(page, _SEND_LABELS):
            random_sleep(2, 3)
            return True, ""
        return False, "no_send_button"
    except Exception as e:
        print(f"[Connect] error: {e}", flush=True)
        return False, f"exception:{type(e).__name__}"


def check_connection_status(page: Page, profile_url: str) -> str:
    """Return 'accepted' if Message button is available, 'pending' if Pending shown, else 'unknown'."""
    if not go_to_profile(page, profile_url):
        return "unknown"
    try:
        for name in _MESSAGE_LABELS:
            btn = page.get_by_role("button", name=name).first
            if _visible(btn):
                return "accepted"
        for name in _PENDING_LABELS:
            btn = page.get_by_role("button", name=name).first
            if _visible(btn):
                return "pending"
        return "unknown"
    except Exception:
        return "unknown"


def send_dm_to_profile(page: Page, profile_url: str, message: str) -> tuple[bool, str]:
    """Open the Message composer on a profile and send a message. Returns (success, reason)."""
    if not message or not message.strip():
        return False, "empty_message"
    if not go_to_profile(page, profile_url):
        return False, "navigation_failed"
    try:
        if not _click_first_visible_button(page, _MESSAGE_LABELS):
            return False, "no_message_button"
        random_sleep(2, 3)
        editor = page.locator("div.msg-form__contenteditable[contenteditable='true']").first
        if not _visible(editor):
            return False, "no_editor"
        editor.click()
        random_sleep(0, 1)
        page.keyboard.type(message, delay=10)
        random_sleep(1, 2)
        # Send button — typically scoped to the messaging window
        for name in _SEND_LABELS:
            try:
                btn = page.locator(".msg-form").get_by_role("button", name=name).first
                if _visible(btn):
                    btn.click()
                    random_sleep(2, 3)
                    return True, ""
            except Exception:
                continue
        # Fallback: any visible Send button on page
        if _click_first_visible_button(page, _SEND_LABELS):
            random_sleep(2, 3)
            return True, ""
        return False, "no_send_button"
    except Exception as e:
        print(f"[DM] error: {e}", flush=True)
        return False, f"exception:{type(e).__name__}"


def send_connection_request(page: Page, template: str, name: str, company: str) -> bool:
    try:
        connect_btn = page.get_by_role("button", name="Connect").first
        if not _visible(connect_btn):
            more_btn = page.get_by_role("button", name="More actions").first
            if _visible(more_btn):
                more_btn.click()
                random_sleep(1, 2)
                connect_menu_btn = page.locator("div.artdeco-dropdown__content").get_by_text("Connect").first
                if _visible(connect_menu_btn):
                    connect_menu_btn.click()
                else:
                    return False
            else:
                return False
        else:
            connect_btn.click()

        random_sleep(2, 4)

        add_note_btn = page.get_by_role("button", name="Add a note").first
        if _visible(add_note_btn):
            add_note_btn.click()
            random_sleep(1, 2)

            message = template.replace("[Name]", name).replace("[Company]", company)
            note_field = page.locator("textarea#custom-message, textarea[name='message']").first
            if not _visible(note_field):
                return False
            note_field.fill(message)
            random_sleep(1, 2)

            send_btn = page.get_by_role("button", name="Send").first
            if not _visible(send_btn):
                return False
            send_btn.click()
            random_sleep(2, 3)
            return True

        return False
    except Exception as e:
        print(f"Error sending request: {e}")
        return False
