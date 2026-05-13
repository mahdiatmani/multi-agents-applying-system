import os
import hashlib
from datetime import datetime
from urllib.parse import urljoin
from langgraph.graph import StateGraph, END
from state import AgentState
from agent.nodes import evaluate_node
from agent.browser import BrowserManager
from tools.playwright_actions import (
    login_if_needed,
    search_jobs,
    get_job_details,
    search_people,
    extract_profile_details,
    send_connection_request,
    send_empty_connection,
    check_connection_status,
    send_dm_to_profile,
    search_posts,
    random_sleep,
)
from tools.apply_actions import apply_easy_apply
from tools.gmail_actions import create_gmail_draft
from tools.history import is_processed, mark_processed
from tools.post_extractor import expand_see_more, extract_emails, extract_author_url
from tools import pending as pending_db
from tools import applications as applications_db
from tools.run_control import checkpoint as _run_checkpoint

DEFAULT_MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "50"))
DEFAULT_WATCH_MAX_ITERATIONS = int(os.getenv("MAX_WATCH_ITERATIONS", "1000"))
MAX_EMPTY_STREAK = int(os.getenv("MAX_EMPTY_STREAK", "3"))
WATCH_SEARCH_TYPES = {"POST", "PERSON"}
ERROR_SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "state", "errors")


def _roles_list(state) -> list[str]:
    raw = state.get("search_role", "AI Engineer")
    if isinstance(raw, list):
        roles = [str(r).strip() for r in raw if str(r).strip()]
    else:
        roles = [r.strip() for r in str(raw or "").split(",") if r.strip()]
    return roles or ["AI Engineer"]


def _pick_role(state) -> str:
    roles = _roles_list(state)
    idx = int(state.get("iterations", 0)) % len(roles)
    return roles[idx]


def _linkedin_url(href: str | None) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else urljoin("https://www.linkedin.com", href)


def _snapshot(page, label: str) -> None:
    try:
        os.makedirs(ERROR_SCREENSHOT_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(ERROR_SCREENSHOT_DIR, f"{label}-{stamp}.png")
        page.screenshot(path=path)
        print(f"[Snapshot] Saved error screenshot: {path}")
    except Exception as exc:
        print(f"[Snapshot] Failed to save screenshot: {exc}")


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _safe_visible(locator) -> bool:
    try:
        return locator.is_visible(timeout=500)
    except Exception:
        return False


def _safe_attr(locator, attr: str) -> str | None:
    try:
        return locator.get_attribute(attr)
    except Exception:
        return None


def _pause_gate(node_name: str) -> None:
    """Block while paused; raises StopRequested if /api/stop was hit."""
    _run_checkpoint(node_name)


def init_browser_node(state: AgentState) -> dict:
    _pause_gate("init")
    headless = state.get("headless", True)
    bm = BrowserManager(headless=headless)
    page = bm.get_page()
    username = os.getenv("LINKEDIN_USERNAME")
    password = os.getenv("LINKEDIN_PASSWORD")
    if not username or not password:
        return {"errors": ["Credentials not set in .env. Set LINKEDIN_USERNAME and LINKEDIN_PASSWORD."]}
    success = login_if_needed(page, username, password)
    if not success:
        _snapshot(page, "login")
        return {"errors": ["Login failed. Please use the 'Login to LinkedIn' button in the sidebar to authenticate manually first."]}
    bm.save_state()
    return {"iterations": 0, "empty_streak": 0}


def _bump_iteration(state: AgentState, found: bool) -> dict:
    iterations = int(state.get("iterations", 0)) + 1
    empty_streak = 0 if found else int(state.get("empty_streak", 0)) + 1
    return {"iterations": iterations, "empty_streak": empty_streak}


def _empty_backoff(streak: int) -> tuple[int, int]:
    """15-25s on first empty, 25-40s on second, 40-60s on third+ — avoids LinkedIn rate-limiting."""
    if streak <= 1:
        return (15, 25)
    if streak == 2:
        return (25, 40)
    return (40, 60)


def search_job_node(state: AgentState) -> dict:
    _pause_gate("search_job")
    bm = BrowserManager()
    page = bm.get_page()
    role = _pick_role(state)
    locations = state.get("search_locations", ["Worldwide"])
    workplace_types = state.get("workplace_types", ["Remote"])
    # Pagination state: reset to first page on role rotation; otherwise advance after empty pages.
    last_role = state.get("_last_role")
    page_start = 0 if last_role != role else int(state.get("job_page_start", 0) or 0)
    url = search_jobs(page, role, locations, workplace_types, start=page_start)

    details: dict = {}
    jobs = page.locator(".job-card-container").all()
    for job in jobs:
        try:
            link_el = job.locator("a.job-card-container__link").first
            if not _safe_visible(link_el):
                continue
            href = _safe_attr(link_el, "href")
            if not href:
                continue
            job_id = href.split("?")[0]
            source_url = _linkedin_url(href)

            if is_processed("jobs", job_id):
                continue

            job.click()
            random_sleep(2, 4)
            details = get_job_details(page)
            if details:
                details.update({
                    "identifier": job_id,
                    "source_url": source_url or page.url,
                    "search_url": url,
                })
                mark_processed("jobs", job_id)
                break
        except Exception:
            continue

    if details:
        next_page_start = page_start  # Stay on the same page until exhausted.
    else:
        # Empty page → advance pagination next iteration, then sleep with backoff.
        next_page_start = page_start + 25 if page_start < 975 else 0
        streak = int(state.get("empty_streak", 0)) + 1
        lo, hi = _empty_backoff(streak)
        print(f"[JOB] No new jobs at start={page_start} for role={role!r}. Sleeping {lo}-{hi}s (streak={streak})...", flush=True)
        random_sleep(lo, hi)

    bump = _bump_iteration(state, bool(details))
    return {
        "current_url": url,
        "job_details": details,
        "profile_details": {},
        "post_details": {},
        "action_taken": "SEARCHED_JOB" if details else "SEARCHED_EMPTY",
        "job_page_start": next_page_start,
        "_last_role": role,
        **bump,
    }


def search_person_node(state: AgentState) -> dict:
    _pause_gate("search_person")
    bm = BrowserManager()
    page = bm.get_page()
    company = state.get("target_company", "Any")
    role = _pick_role(state)
    url = search_people(page, company, role)

    details: dict = {}
    people = page.locator("li.reusable-search__result-container").all()
    for person in people:
        try:
            link = person.locator("a.app-aware-link").first
            if not _safe_visible(link):
                continue
            href = _safe_attr(link, "href")
            if not href:
                continue
            person_id = href.split("?")[0]
            source_url = _linkedin_url(href)

            if is_processed("people", person_id):
                continue

            link.click()
            random_sleep(3, 5)
            details = extract_profile_details(page)
            if details.get("name"):
                details.update({
                    "identifier": person_id,
                    "source_url": page.url or source_url,
                    "search_url": url,
                })
                mark_processed("people", person_id)
                break
        except Exception:
            continue

    found = bool(details.get("name"))
    if not found:
        streak = int(state.get("empty_streak", 0)) + 1
        lo, hi = _empty_backoff(streak)
        print(f"[PERSON] No new profiles for role={role!r} @ {company!r}. Sleeping {lo}-{hi}s (streak={streak})...", flush=True)
        random_sleep(lo, hi)

    bump = _bump_iteration(state, found)
    return {
        "current_url": url,
        "profile_details": details,
        "job_details": {},
        "post_details": {},
        "action_taken": "SEARCHED_PERSON" if found else "SEARCHED_EMPTY",
        **bump,
    }


def search_post_node(state: AgentState) -> dict:
    _pause_gate("search_post")
    bm = BrowserManager()
    page = bm.get_page()
    role = _pick_role(state)
    multi_role = len(_roles_list(state)) > 1

    url = page.url
    if "search/results/content" not in url or multi_role:
        # Rotate the search URL whenever roles change; otherwise just scroll for new posts.
        url = search_posts(page, f"hiring {role}")
    else:
        page.mouse.wheel(0, 1000)
        random_sleep(2, 4)

    details: dict = {}
    posts = page.locator(".feed-shared-update-v2").all()
    for post in posts:
        try:
            urn = _safe_attr(post, "data-urn")
            try:
                snippet = post.inner_text()
            except Exception:
                snippet = ""
            post_id = urn or f"post:{_hash(snippet)}"
            if is_processed("posts", post_id):
                continue
            try:
                post.scroll_into_view_if_needed()
            except Exception:
                pass

            # Expand "see more" so we capture the full post body (where the email usually lives).
            expand_see_more(post)
            random_sleep(1, 2)

            author_el = post.locator(".update-components-actor__name").first
            content_el = post.locator(".update-components-text").first
            author_text = ""
            content_text = ""
            try:
                if _safe_visible(author_el):
                    author_text = (author_el.inner_text() or "").strip()
            except Exception:
                pass
            try:
                if _safe_visible(content_el):
                    content_text = (content_el.inner_text() or "").strip()
            except Exception:
                pass

            if content_text:
                emails = extract_emails(content_text)
                author_url = extract_author_url(post)
                details = {
                    "author": author_text,
                    "author_url": author_url,
                    "content": content_text,
                    "emails": emails,
                    "primary_email": emails[0] if emails else "",
                    "identifier": post_id,
                    "source_url": page.url,
                    "search_url": url,
                }
                mark_processed("posts", post_id)
                break
        except Exception:
            continue

    if not details:
        streak = int(state.get("empty_streak", 0)) + 1
        lo, hi = _empty_backoff(streak)
        print(f"[POST] No new posts for role={role!r}. Sleeping {lo}-{hi}s (streak={streak})...", flush=True)
        random_sleep(lo, hi)
        url = search_posts(page, f"hiring {role}")

    bump = _bump_iteration(state, bool(details))
    return {
        "current_url": url,
        "post_details": details,
        "job_details": {},
        "profile_details": {},
        "action_taken": "SEARCHED_POST" if details else "SEARCHED_EMPTY",
        **bump,
    }


def apply_node(state: AgentState) -> dict:
    _pause_gate("apply")
    job = state.get("job_details") or {}
    if not applications_db.can_apply_today():
        cap_msg = (
            f"Daily application cap reached ({applications_db.DEFAULT_DAILY_CAP}/day). "
            f"Skipping {job.get('title') or '?'} @ {job.get('company') or '?'}."
        )
        print(f"[Apply] {cap_msg}", flush=True)
        return {"action_taken": "SKIP", "errors": state.get("errors", []) + [cap_msg]}

    if state.get("dry_run"):
        title = job.get("title") or "?"
        company = job.get("company") or "?"
        url = job.get("source_url") or job.get("url") or ""
        msg = f"[DRY_RUN] Would APPLY → {title} @ {company} ({url})"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_APPLY", "errors": state.get("errors", []) + [msg]}

    bm = BrowserManager()
    page = bm.get_page()
    success, reason = apply_easy_apply(page, job, llm_model=state.get("llm_model"))
    if success:
        new_total = applications_db.record_application()
        print(f"[Apply] APPLIED — today's total: {new_total}/{applications_db.DEFAULT_DAILY_CAP}", flush=True)
        return {"action_taken": "APPLIED"}
    # Use only the failure tag (before any space/parens) for the screenshot filename.
    short_reason = (reason or "unknown").split(" ", 1)[0].split("(", 1)[0].strip() or "unknown"
    _snapshot(page, f"apply-{short_reason}")
    title = job.get("title") or "?"
    company = job.get("company") or "?"
    url = job.get("source_url") or job.get("url") or ""
    job_ctx = f"{title} @ {company}" + (f" — {url}" if url else "")
    if (reason or "").startswith("external_apply"):
        # Not a true failure — surface as a lead so the user can apply manually on the ATS.
        return {
            "action_taken": "EXTERNAL_LEAD",
            "errors": state.get("errors", []) + [f"External ATS lead [{job_ctx}]: {reason}"],
        }
    return {
        "action_taken": "APPLY_FAILED",
        "errors": state.get("errors", []) + [f"Apply failed [{job_ctx}]: {reason or 'unknown'}"],
    }


def network_node(state: AgentState) -> dict:
    _pause_gate("network")
    if state.get("dry_run"):
        name = state.get("profile_details", {}).get("name", "?")
        msg = f"[DRY_RUN] Would CONNECT → {name}"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_NETWORK", "errors": state.get("errors", []) + [msg]}

    bm = BrowserManager()
    page = bm.get_page()
    template = "Hi [Name], I noticed your work at [Company] and would love to connect!"
    name = state.get("profile_details", {}).get("name", "there")
    success = send_connection_request(page, template, name, "your company")
    if success:
        return {"action_taken": "NETWORKED"}
    _snapshot(page, "network")
    return {"action_taken": "NETWORK_FAILED", "errors": state.get("errors", []) + ["Network failed"]}


def draft_email_node(state: AgentState) -> dict:
    _pause_gate("draft_email")
    to_email = state.get("extracted_email")
    draft_msg = state.get("draft_message")

    if not to_email or not draft_msg:
        return {"action_taken": "DRAFT_FAILED", "errors": state.get("errors", []) + ["Missing email or draft message"]}

    if state.get("dry_run"):
        msg = f"[DRY_RUN] Would DRAFT EMAIL → {to_email} ({len(draft_msg)} chars)"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_EMAIL", "errors": state.get("errors", []) + [msg]}

    subject = "Application / networking follow-up (via Apply Agent)"
    success = create_gmail_draft(to_email, subject, draft_msg)

    if success:
        return {"action_taken": "DRAFTED_EMAIL"}
    return {"action_taken": "DRAFT_FAILED", "errors": state.get("errors", []) + ["Failed to create draft"]}


def draft_dm_node(state: AgentState) -> dict:
    """For posts with no email: send empty connection to the post author and queue the DM for after acceptance."""
    _pause_gate("draft_dm")
    draft_msg = state.get("draft_message") or ""
    post = state.get("post_details") or {}
    profile_url = post.get("author_url") or ""
    author_name = post.get("author") or ""

    if not draft_msg:
        return {"action_taken": "DRAFT_FAILED", "errors": state.get("errors", []) + ["Missing DM draft message"]}
    if not profile_url:
        return {"action_taken": "DRAFT_FAILED", "errors": state.get("errors", []) + ["No author profile URL on post"]}

    if pending_db.has_pending(profile_url):
        return {"action_taken": "DRAFTED_DM"}

    if not pending_db.can_send_today():
        msg = f"Daily connection cap reached ({pending_db.DEFAULT_DAILY_CAP}/day). Skipping {author_name}."
        print(f"[Connect] {msg}", flush=True)
        return {"action_taken": "SKIP", "errors": state.get("errors", []) + [msg]}

    if state.get("dry_run"):
        msg = f"[DRY_RUN] Would CONNECT+QUEUE_DM → {author_name} ({profile_url})"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_DM", "errors": state.get("errors", []) + [msg]}

    bm = BrowserManager()
    page = bm.get_page()
    ok, reason = send_empty_connection(page, profile_url)
    if not ok:
        _snapshot(page, f"connect-{reason}")
        return {
            "action_taken": "NETWORK_FAILED",
            "errors": state.get("errors", []) + [f"Connect failed [{author_name} — {profile_url}]: {reason}"],
        }

    pending_db.add_pending(
        profile_url=profile_url,
        name=author_name,
        post_id=post.get("identifier") or "",
        post_content=post.get("content") or "",
        queued_dm=draft_msg,
    )
    print(f"[Connect] Sent empty invite to {author_name} ({profile_url}); DM queued.", flush=True)
    return {"action_taken": "DRAFTED_DM"}


def check_pending_connections(headless: bool = True, max_to_dm: int = 20) -> dict:
    """Standalone sweep: visit each pending profile, send queued DM if connection is now accepted."""
    items = pending_db.list_items(status="pending")
    if not items:
        return {"checked": 0, "accepted": 0, "dm_sent": 0, "dm_failed": 0, "still_pending": 0}

    bm = BrowserManager(headless=headless)
    page = bm.get_page()
    username = os.getenv("LINKEDIN_USERNAME")
    password = os.getenv("LINKEDIN_PASSWORD")
    if username and password:
        login_if_needed(page, username, password)

    checked = accepted = dm_sent = dm_failed = still_pending = 0
    for it in items[:max_to_dm]:
        profile_url = it.get("profile_url") or ""
        if not profile_url:
            continue
        checked += 1
        status = check_connection_status(page, profile_url)
        if status == "accepted":
            accepted += 1
            ok, reason = send_dm_to_profile(page, profile_url, it.get("queued_dm") or "")
            if ok:
                pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
                dm_sent += 1
                print(f"[CheckPending] DM sent to {it.get('name')} ({profile_url})", flush=True)
            else:
                pending_db.update_status(profile_url, "dm_failed")
                dm_failed += 1
                print(f"[CheckPending] DM failed for {it.get('name')}: {reason}", flush=True)
        elif status == "pending":
            still_pending += 1
            pending_db.update_status(profile_url, "pending")
        else:
            # Could mean declined, withdrawn, or page change
            still_pending += 1
        random_sleep(3, 6)
    return {
        "checked": checked,
        "accepted": accepted,
        "dm_sent": dm_sent,
        "dm_failed": dm_failed,
        "still_pending": still_pending,
    }


SEARCH_ACTIONS = {"SEARCHED_JOB", "SEARCHED_PERSON", "SEARCHED_POST"}
LOOP_DESTINATIONS = {"JOB": "search_job", "PERSON": "search_person", "POST": "search_post"}


def _terminal(state: AgentState) -> bool:
    search_type = state.get("search_type", "JOB")
    is_watch = search_type in WATCH_SEARCH_TYPES
    max_iters = int(
        state.get("max_iterations")
        or (DEFAULT_WATCH_MAX_ITERATIONS if is_watch else DEFAULT_MAX_ITERATIONS)
    )
    if int(state.get("iterations", 0)) >= max_iters:
        print(f"[Router] Reached max iterations ({max_iters}). Ending.")
        return True
    if is_watch:
        # Watch mode: keep polling the feed/people search until user stops.
        return False
    if int(state.get("empty_streak", 0)) >= MAX_EMPTY_STREAK:
        print(f"[Router] No new items for {MAX_EMPTY_STREAK} iterations. Ending.")
        return True
    return False


def router(state: AgentState) -> str:
    errors = state.get("errors", [])
    if any("Login failed" in e or "Credentials not set" in e for e in errors):
        return "end"

    action = state.get("action_taken", "")
    search_type = state.get("search_type", "JOB")
    loop_target = LOOP_DESTINATIONS.get(search_type, "search_job")

    if not action:
        return loop_target

    if action == "SEARCHED_EMPTY":
        if _terminal(state):
            return "end"
        return loop_target

    if action in SEARCH_ACTIONS:
        if _terminal(state):
            return "end"
        return "evaluate"

    if action in ("APPLY", "NETWORK", "DRAFT_EMAIL", "DRAFT_DM"):
        return {
            "APPLY": "apply",
            "NETWORK": "network",
            "DRAFT_EMAIL": "draft_email",
            "DRAFT_DM": "draft_dm",
        }[action]

    if _terminal(state):
        return "end"
    return loop_target


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("init", init_browser_node)
    workflow.add_node("search_job", search_job_node)
    workflow.add_node("search_person", search_person_node)
    workflow.add_node("search_post", search_post_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("apply", apply_node)
    workflow.add_node("network", network_node)
    workflow.add_node("draft_email", draft_email_node)
    workflow.add_node("draft_dm", draft_dm_node)

    workflow.set_entry_point("init")

    workflow.add_conditional_edges(
        "init",
        router,
        {"search_job": "search_job", "search_person": "search_person", "search_post": "search_post", "end": END},
    )
    workflow.add_conditional_edges("search_job", router, {"evaluate": "evaluate", "search_job": "search_job", "end": END})
    workflow.add_conditional_edges("search_person", router, {"evaluate": "evaluate", "search_person": "search_person", "end": END})
    workflow.add_conditional_edges("search_post", router, {"evaluate": "evaluate", "search_post": "search_post", "end": END})

    workflow.add_conditional_edges(
        "evaluate",
        router,
        {
            "apply": "apply",
            "network": "network",
            "draft_email": "draft_email",
            "draft_dm": "draft_dm",
            "search_job": "search_job",
            "search_person": "search_person",
            "search_post": "search_post",
            "end": END,
        },
    )

    for node in ("apply", "network", "draft_email", "draft_dm"):
        workflow.add_conditional_edges(
            node,
            router,
            {"search_job": "search_job", "search_person": "search_person", "search_post": "search_post", "end": END},
        )

    return workflow.compile()
