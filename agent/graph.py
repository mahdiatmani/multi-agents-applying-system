import os
import re
import hashlib
from datetime import datetime
from urllib.parse import urljoin, quote
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
    is_first_degree_connection,
    profile_is_pending,
    goto_home_feed,
    random_sleep,
)
from tools.apply_actions import apply_easy_apply
from tools.gmail_actions import create_gmail_draft
from tools.history import is_processed, mark_processed
from tools.post_extractor import POST_CONTAINER_SELECTORS, scrape_post, scrape_feed_via_js
from tools import pending as pending_db
from tools import applications as applications_db
from tools import external_leads
from tools import job_screener
from tools import outreach
from tools import apply_link
from tools.run_control import checkpoint as _run_checkpoint
from tools import run_control

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


# Dynamic chrome that changes between feed reloads (reaction/comment counts,
# relative timestamps). Stripped before hashing so the same post yields the
# same ID across visits.
_SOCIAL_PROOF_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:reactions?|comments?|reposts?|likes?|shares?|"
    r"r\xe9actions?|commentaires?|partages?|"      # FR
    r"reacciones?|comentarios?|veces?|"           # ES
    r"reaktionen?|kommentare?|mal geteilt|"        # DE
    r"reazioni?|commenti?|condivisioni?|"          # IT
    r"rea\xe7\xf5es?|coment\xe1rios?|partilhas?)\b",
    re.IGNORECASE,
)
_RELATIVE_TIME_RE = re.compile(
    r"\b\d+\s*(?:s|m|h|d|w|mo|y|min|hr|sec|day|week|month|year)s?\b",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_for_id(text: str) -> str:
    """Strip dynamic noise (reaction/comment counts, relative timestamps) before
    hashing — keeps the post identifier stable across feed reloads."""
    if not text:
        return ""
    text = _SOCIAL_PROOF_RE.sub(" ", text)
    text = _RELATIVE_TIME_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _stable_post_id(scraped: dict) -> str:
    """Build a dedup-stable identifier for a scraped post.

    Order of preference:
      1. post_url — canonical /feed/update/urn:li:activity:... permalink
      2. author_url + normalized body[:300] — stable across reloads
      3. normalized body[:600] — last resort
    Falls back to a content hash if nothing usable exists."""
    post_url = (scraped.get("post_url") or "").strip()
    if post_url:
        return f"post_url:{_hash(post_url)}"
    body = scraped.get("content") or ""
    normalized = _normalize_for_id(body)
    author_url = (scraped.get("author_url") or "").strip()
    if author_url and normalized:
        return f"post:{_hash(author_url + '|' + normalized[:300])}"
    if normalized:
        return f"post:{_hash(normalized[:600])}"
    return f"post:{_hash(body[:600])}" if body else ""


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


# Multi-locale markers that mean "you've already applied to this job" — shown
# in the job card's footer-state slot. Lowercased before comparison.
_APPLIED_TERMS = (
    "applied",                # EN
    "postulé", "postule",     # FR
    "candidature envoyée", "candidature envoyee",
    "solicitado", "solicitud enviada",  # ES
    "candidatura inviata",    # IT
    "beworben",               # DE
    "candidato",              # PT
)


def _card_already_applied(job) -> bool:
    """True if the job card shows an 'Applied X ago' footer-state. Multi-locale."""
    # Prefer the structured footer slot — avoids false positives on body text.
    for sel in (
        ".job-card-container__footer-job-state",
        ".job-card-list__footer-wrapper .job-card-container__footer-job-state",
        "li.job-card-container__footer-item--highlighted",
    ):
        try:
            el = job.locator(sel).first
            if not _safe_visible(el):
                continue
            text = (el.inner_text(timeout=300) or "").strip().lower()
            if not text:
                continue
            if any(term in text for term in _APPLIED_TERMS):
                return True
        except Exception:
            continue
    # Fallback: an aria-label on the card that mentions applied.
    try:
        aria = (_safe_attr(job, "aria-label") or "").lower()
        if any(term in aria for term in _APPLIED_TERMS):
            return True
    except Exception:
        pass
    return False


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
    bm = BrowserManager(headless=state.get("headless", True))
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
    skipped_applied = 0
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

            # Skip jobs LinkedIn already shows as applied — mark them processed so
            # the bot never wastes an LLM call or Easy Apply attempt on them again.
            if _card_already_applied(job):
                mark_processed("jobs", job_id)
                skipped_applied += 1
                print(f"[JOB] Skip already-applied: {job_id}", flush=True)
                continue

            # Job-fit Pre-screener — score the card BEFORE the click so we don't waste
            # a get_job_details + evaluate + Easy Apply on a clear mismatch.
            try:
                card_text = (job.inner_text(timeout=500) or "").strip()
            except Exception:
                card_text = ""
            if card_text:
                verdict = job_screener.screen(card_text, state.get("llm_model"))
                score = verdict.get("score", -1)
                if not job_screener.passes(score):
                    print(
                        f"[JOB] Screened out (score={score}): {job_id} — {verdict.get('reason','')[:120]}",
                        flush=True,
                    )
                    mark_processed("jobs", job_id)
                    continue
                elif score >= 0:
                    print(f"[JOB] Screened in  (score={score}): {job_id}", flush=True)

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


# LinkedIn renames people-search result containers across rollouts. Try each
# selector in turn — the union is deduped by canonical profile URL in _collect_people.
PEOPLE_RESULT_SELECTORS = (
    "li.reusable-search__result-container",                              # legacy
    "div.reusable-search__result-container",
    "[data-view-name='search-entity-result-universal-template']",        # current
    "div.entity-result",
    "[data-chameleon-result-urn]",
    "li.organic-search-result",
    "li[data-occludable-job-id]",
)

# Restricts profile links to actual /in/ paths. Excludes self-profile shortcuts.
_PROFILE_LINK_SELECTOR = (
    "a[href*='/in/']:not([href*='/in/me'])"
    ":not([href*='/in/edit'])"
)

# Canonical profile slug only. Strips overlays (/in/foo/overlay/about-this-profile/),
# section subpaths (/in/foo/details/experience/), recent-activity, hash fragments,
# query params. The remaining `/in/<slug>/` is what we navigate to and dedupe on.
_PROFILE_SLUG_RE = re.compile(r"^/in/([^/?#]+)")
_PROFILE_NON_SLUG = {"me", "edit", "in", "settings", "feed-settings"}


def _canonical_profile_url(href: str) -> str:
    """Normalize any LinkedIn /in/ link to https://www.linkedin.com/in/<slug>/.
    Returns "" if the href doesn't reference a real profile slug."""
    if not href:
        return ""
    path = href
    if href.startswith("http"):
        try:
            from urllib.parse import urlparse
            path = urlparse(href).path or ""
        except Exception:
            return ""
    m = _PROFILE_SLUG_RE.match(path)
    if not m:
        return ""
    slug = m.group(1).strip().lower()
    if not slug or slug in _PROFILE_NON_SLUG:
        return ""
    return f"https://www.linkedin.com/in/{slug}/"


def _collect_people(page) -> list[dict]:
    """Walk every known people-search result container, fall back to a flat
    a[href*='/in/'] scan when none match. Returns dicts with the canonical
    profile URL (no /overlay/, /details/, /recent-activity/ subpaths), deduped
    in document order."""
    by_id: dict[str, dict] = {}
    selector_counts: list[str] = []

    for sel in PEOPLE_RESULT_SELECTORS:
        try:
            cards = page.locator(sel).all()
            selector_counts.append(f"{sel}={len(cards)}")
            for card in cards:
                try:
                    link = card.locator(_PROFILE_LINK_SELECTOR).first
                    if not _safe_visible(link):
                        continue
                    href = _safe_attr(link, "href") or ""
                    canonical = _canonical_profile_url(href)
                    if not canonical or canonical in by_id:
                        continue
                    by_id[canonical] = {"id": canonical, "href": canonical}
                except Exception:
                    continue
        except Exception:
            continue

    # Last-resort fallback: no recognised container matched. Grab every /in/
    # anchor on the page, canonicalize, dedupe. Photo links, name links, and
    # section-overlay links all collapse to the same /in/<slug>/ entry.
    if not by_id:
        try:
            anchors = page.locator(_PROFILE_LINK_SELECTOR).all()
            selector_counts.append(f"flat_in={len(anchors)}")
            for link in anchors:
                try:
                    if not _safe_visible(link):
                        continue
                    href = _safe_attr(link, "href") or ""
                    canonical = _canonical_profile_url(href)
                    if not canonical or canonical in by_id:
                        continue
                    by_id[canonical] = {"id": canonical, "href": canonical}
                except Exception:
                    continue
        except Exception:
            pass

    # Annotate with pending-status detected directly in the search-result row,
    # so search_person_node can skip these BEFORE navigating + LLM.
    _annotate_pending(page, by_id)

    pending_cnt = sum(1 for v in by_id.values() if v.get("pending"))
    print(
        f"[PERSON] container scan: {', '.join(selector_counts)} → {len(by_id)} unique"
        f" ({pending_cnt} pending)",
        flush=True,
    )
    return list(by_id.values())


# JS scan associates each Pending button with the ONE profile in its card.
#
# Previous approach (walk each link up 8 ancestors, check innerText for
# 'Pending') was broken: by ~level 5 the ancestor contained the entire
# results list, so any single Pending profile poisoned the parent text and
# the scan marked ALL profiles on the page as pending → bot skipped every
# search result.
#
# New approach:
#   Pass 1 — collect every distinct profile slug on the page, default false.
#   Pass 2 — for each Pending-text element, walk UP looking for an ancestor
#            that contains at least one /in/ link. Pick the slug that appears
#            MOST FREQUENTLY in that ancestor — search-result cards link the
#            main profile 2-3x (photo + name + "View profile"), while mutual-
#            connection mentions link each side-profile only once. Mark that
#            top-frequency slug as pending. Mutual links never win.
_PENDING_IN_SEARCH_JS = r"""
() => {
  const out = {};
  const PENDING_RE = /(?:^|\W)(pending|en attente|pendiente|ausstehend|in attesa|pendente)(?:$|\W)/i;

  const slugOf = (a) => {
    // Read the raw href attribute, not link.pathname — pathname is empty if
    // the document has no base URL (e.g. in tests using set_content).
    const href = a.getAttribute('href') || a.href || '';
    const m = href.match(/\/in\/([^\/?#]+)/);
    if (!m) return null;
    const s = m[1].toLowerCase();
    if (!s || s === 'me' || s === 'edit' || s === 'in') return null;
    return s;
  };

  // Pass 1: register every profile slug on the page (default = not pending).
  for (const a of document.querySelectorAll("a[href*='/in/']")) {
    const s = slugOf(a);
    if (!s) continue;
    const canonical = 'https://www.linkedin.com/in/' + s + '/';
    if (!(canonical in out)) out[canonical] = false;
  }

  // Pass 2: every <button>-ish element whose visible text is exactly a Pending
  // marker. We check buttons first (the most reliable signal), then spans/divs
  // as fallback for DOMs that render Pending as a non-button pill.
  const findCardFor = (el) => {
    // Walk up; first ancestor that contains a /in/ link is the card. Stop at 8
    // levels — search-result rows never nest deeper than that.
    let cur = el;
    for (let i = 0; i < 8 && cur; i++) {
      const links = cur.querySelectorAll("a[href*='/in/']");
      if (links.length > 0) {
        // Tally slugs by frequency. Main profile = photo + name + (sometimes)
        // View link, so 2-3x. Mutual connections appear once each, so they
        // can't outvote the main profile.
        const counts = {};
        for (const a of links) {
          const s = slugOf(a);
          if (!s) continue;
          counts[s] = (counts[s] || 0) + 1;
        }
        let bestSlug = null, bestCount = 0;
        for (const [s, c] of Object.entries(counts)) {
          if (c > bestCount) { bestSlug = s; bestCount = c; }
        }
        if (bestSlug) return bestSlug;
      }
      cur = cur.parentElement;
    }
    return null;
  };

  const PENDING_NODE_SELECTOR = "button, [role='button'], span, div";
  const seenPendingElements = new WeakSet();
  for (const el of document.querySelectorAll(PENDING_NODE_SELECTOR)) {
    if (seenPendingElements.has(el)) continue;
    const text = (el.innerText || '').trim();
    if (!text || text.length > 30) continue;   // Pending labels are short
    if (!PENDING_RE.test(text)) continue;
    seenPendingElements.add(el);
    const slug = findCardFor(el);
    if (!slug) continue;
    const canonical = 'https://www.linkedin.com/in/' + slug + '/';
    out[canonical] = true;
  }

  return out;
}
"""


def _annotate_pending(page, by_id: dict) -> None:
    """Mark each entry in by_id with pending=True if the search-result row
    around it contains a Pending marker. Best-effort: failures leave entries
    unannotated (default treated as not-pending downstream)."""
    try:
        pending_map = page.evaluate(_PENDING_IN_SEARCH_JS) or {}
    except Exception as exc:
        print(f"[PERSON] pending-scan failed: {exc}", flush=True)
        return
    if not isinstance(pending_map, dict):
        return
    for canonical, entry in by_id.items():
        if pending_map.get(canonical):
            entry["pending"] = True


def search_person_node(state: AgentState) -> dict:
    _pause_gate("search_person")
    bm = BrowserManager(headless=state.get("headless", True))
    page = bm.get_page()
    company = state.get("target_company", "")
    role = _pick_role(state)
    url = search_people(page, company, role)

    details: dict = {}
    people = _collect_people(page)
    for entry in people:
        try:
            person_id = entry["id"]  # canonical https://www.linkedin.com/in/<slug>/

            if is_processed("people", person_id):
                continue

            # Pending detected directly in the search-result row → skip BEFORE
            # navigation. Saves a goto + sleep + extract + LLM call per
            # already-pending profile. Detected by walking up from each /in/
            # anchor and matching multi-locale 'Pending' markers (see
            # _PENDING_IN_SEARCH_JS).
            if entry.get("pending"):
                mark_processed("people", person_id)
                print(f"[PERSON] {person_id} shows Pending in search results — skipping (no navigation).", flush=True)
                continue

            # Always navigate via goto(canonical_url) — never click. Clicking the
            # card's link can hit the photo (opens a lightbox), an overlay link
            # (/overlay/about-this-profile/ scrolls to that section), or a mutual
            # connection sub-link, all of which fail to land on the actual profile.
            # goto on the canonical URL is the only reliable path.
            try:
                page.goto(person_id, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                print(f"[PERSON] goto failed for {person_id}: {exc}", flush=True)
                continue
            random_sleep(3, 5)

            # Belt-and-braces: profile page may also show Pending even if the
            # search-row scan missed it (e.g. invite was sent between scan and
            # navigation). Still cheaper than an LLM call.
            if profile_is_pending(page):
                mark_processed("people", person_id)
                print(f"[PERSON] {person_id} already has a pending invite — skipping (no LLM call).", flush=True)
                details = {}
                continue

            details = extract_profile_details(page)
            if details.get("name"):
                details.update({
                    "identifier": person_id,
                    "source_url": page.url or person_id,
                    "search_url": url,
                })
                mark_processed("people", person_id)
                break
            else:
                # Profile loaded but extractor saw nothing usable — could be a
                # private profile, deleted account, or a brand-new DOM that
                # extract_profile_details() doesn't recognise. Mark processed so
                # we don't re-visit the same dead-end every iteration.
                mark_processed("people", person_id)
                print(f"[PERSON] No usable details at {person_id} — marked processed.", flush=True)
        except Exception as exc:
            print(f"[PERSON] iteration error: {exc}", flush=True)
            continue

    found = bool(details.get("name"))
    if not found:
        company_label = company.strip() if (company or "").strip().lower() not in {"", "any"} else "no-filter"
        streak = int(state.get("empty_streak", 0)) + 1
        lo, hi = _empty_backoff(streak)
        print(f"[PERSON] No new profiles for role={role!r} @ {company_label!r}. Sleeping {lo}-{hi}s (streak={streak})...", flush=True)
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


POST_BATCH_TARGET = int(os.getenv("POST_BATCH_TARGET", "25"))
POST_BATCH_MAX_SCROLLS = int(os.getenv("POST_BATCH_MAX_SCROLLS", "8"))


def _collect_post_locators(page):
    """Try every known LinkedIn post-container selector and return the union, in
    document order, deduped by data-urn / data-id. LinkedIn renames classes across
    rollouts, so we always try several. Scoped to <main> when possible to avoid
    sidebar duplicates."""
    seen_keys: set[str] = set()
    locators: list = []
    per_selector_counts: list[str] = []
    # Search the whole page rather than scoping to <main>: LinkedIn occasionally
    # renders the feed-scroll container outside <main> during A/B tests. Sidebar
    # noise is naturally filtered out because non-post elements don't carry the
    # urn:li:activity data-attrs that drive dedup.
    for sel in POST_CONTAINER_SELECTORS:
        try:
            found = page.locator(sel).all()
            per_selector_counts.append(f"{sel}={len(found)}")
            for loc in found:
                try:
                    urn = loc.get_attribute("data-urn") or loc.get_attribute("data-id") or ""
                except Exception:
                    urn = ""
                key = urn or f"pos:{len(locators)}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                locators.append(loc)
        except Exception:
            continue
    print(f"[POST] container scan: {', '.join(per_selector_counts)} → {len(locators)} unique", flush=True)
    return locators


_DOM_PROBE_JS = """
() => {
  const main = document.querySelector('main') || document.body;
  if (!main) return { error: 'no main or body' };
  const candidates = main.querySelectorAll('*');
  const buckets = {
    total_in_main: candidates.length,
    with_data_urn: [],
    with_data_id: [],
    class_hits: [],
    aria_post: [],
    iframes_in_main: main.querySelectorAll('iframe').length,
    iframes_in_doc: document.querySelectorAll('iframe').length,
    post_text_chains: [],
    sample_classes: [],
    sample_ids: [],
  };
  const seenCls = new Set();
  const sampleSeen = new Set();
  for (const el of candidates) {
    const cls = (el.className && el.className.toString) ? el.className.toString() : '';
    const id  = el.id || '';
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const dataUrn = el.getAttribute('data-urn') || '';
    const dataId  = el.getAttribute('data-id')  || '';
    const summary = `${tag}.${cls.split(' ').slice(0,3).join('.')}#${id}`.slice(0, 160);
    if (dataUrn && buckets.with_data_urn.length < 6) {
      buckets.with_data_urn.push(`${summary} data-urn="${dataUrn.slice(0, 60)}"`);
    }
    if (dataId && buckets.with_data_id.length < 6) {
      buckets.with_data_id.push(`${summary} data-id="${dataId.slice(0, 60)}"`);
    }
    if (role === 'article' && buckets.aria_post.length < 6) {
      buckets.aria_post.push(summary);
    }
    if (/feed|update|activity|share|post|article/i.test(cls)) {
      for (const c of cls.split(' ')) {
        if (c && !seenCls.has(c) && /feed|update|activity|share|post|article/i.test(c)) {
          seenCls.add(c);
          if (seenCls.size <= 30) buckets.class_hits.push(c);
        }
      }
    }
    // Top-level sample (first 25 elements with any class) so we see naming conventions.
    if (cls && buckets.sample_classes.length < 25) {
      const first = cls.split(' ')[0];
      if (first && !sampleSeen.has(first)) {
        sampleSeen.add(first);
        buckets.sample_classes.push(first);
      }
    }
    if (id && buckets.sample_ids.length < 10 && !/^ember/.test(id)) {
      buckets.sample_ids.push(id.slice(0, 80));
    }
  }
  // Walk up from text nodes that say "reposted this" / "3rd+" to find the post-root element.
  try {
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode()) && buckets.post_text_chains.length < 2) {
      const text = (node.nodeValue || '').trim();
      if (!text) continue;
      if (!/reposted this|commented on this|liked this|^•? *3rd\\+|likes this/i.test(text)) continue;
      let el = node.parentElement;
      const chain = [];
      for (let depth = 0; depth < 12 && el; depth++) {
        const ec = (el.className && el.className.toString) ? el.className.toString() : '';
        chain.push({
          d: depth,
          tag: el.tagName.toLowerCase(),
          id: (el.id || '').slice(0, 60),
          cls: ec.slice(0, 220),
          urn: el.getAttribute('data-urn') || '',
          did: el.getAttribute('data-id') || '',
          role: el.getAttribute('role') || '',
        });
        el = el.parentElement;
      }
      buckets.post_text_chains.push({ trigger: text.slice(0, 80), chain });
    }
  } catch (e) {
    buckets.walker_error = String(e);
  }
  return buckets;
}
"""


def _diagnose_feed_state(page) -> None:
    """When 0 posts were found, dump enough about the current page to tell whether
    we hit a login wall, a checkpoint, or a DOM we don't recognise yet. Probes the
    real DOM (via page.evaluate) for any post-shaped elements + their classes."""
    try:
        url = page.url
    except Exception:
        url = "<unknown>"
    try:
        title = page.title()
    except Exception:
        title = "<unknown>"
    print(f"[POST] diagnostic — current URL: {url}", flush=True)
    print(f"[POST] diagnostic — page title: {title}", flush=True)
    lower_url = (url or "").lower()
    for marker in ("/login", "/checkpoint", "/uas/login", "/authwall"):
        if marker in lower_url:
            print(f"[POST] diagnostic — URL contains {marker!r}: session likely expired. "
                  f"Re-login via the sidebar 'Login to LinkedIn' button.", flush=True)
            break
    try:
        main_loc = page.locator("main").first
        if main_loc.count():
            text = (main_loc.inner_text(timeout=2000) or "")[:400]
            print(f"[POST] diagnostic — <main> text sample: {text!r}", flush=True)
        else:
            print("[POST] diagnostic — no <main> element found on the page", flush=True)
    except Exception as exc:
        print(f"[POST] diagnostic — <main> inspect failed: {exc}", flush=True)
    # Real DOM probe — tells us what classes/data-attrs the current LinkedIn DOM
    # actually uses on post-like elements, so we can add a matching selector.
    try:
        buckets = page.evaluate(_DOM_PROBE_JS)
        if isinstance(buckets, dict):
            print(f"[POST] diagnostic — total elements in <main>: {buckets.get('total_in_main')}", flush=True)
            print(f"[POST] diagnostic — iframes (in main / total): "
                  f"{buckets.get('iframes_in_main')} / {buckets.get('iframes_in_doc')}", flush=True)
            urns = buckets.get("with_data_urn") or []
            dids = buckets.get("with_data_id") or []
            cls_hits = buckets.get("class_hits") or []
            arts = buckets.get("aria_post") or []
            sample_cls = buckets.get("sample_classes") or []
            sample_ids = buckets.get("sample_ids") or []
            print(f"[POST] diagnostic — DOM elements with data-urn (first {len(urns)}):", flush=True)
            for s in urns:
                print(f"    {s}", flush=True)
            print(f"[POST] diagnostic — DOM elements with data-id (first {len(dids)}):", flush=True)
            for s in dids:
                print(f"    {s}", flush=True)
            print(f"[POST] diagnostic — role='article' elements: {arts}", flush=True)
            print(f"[POST] diagnostic — post-ish class tokens (up to 30): {cls_hits}", flush=True)
            print(f"[POST] diagnostic — sample of first 25 class tokens in <main>: {sample_cls}", flush=True)
            print(f"[POST] diagnostic — sample of non-ember ids in <main>: {sample_ids}", flush=True)
            chains = buckets.get("post_text_chains") or []
            for i, item in enumerate(chains):
                print(f"[POST] diagnostic — post-text chain #{i+1} trigger="
                      f"{item.get('trigger')!r}", flush=True)
                for hop in item.get("chain", []):
                    print(
                        f"    d{hop.get('d')}: <{hop.get('tag')}> "
                        f"id={hop.get('id')!r} role={hop.get('role')!r} "
                        f"urn={hop.get('urn')!r} did={hop.get('did')!r} "
                        f"cls={hop.get('cls')!r}",
                        flush=True,
                    )
            if not chains:
                print("[POST] diagnostic — no text node matched 'reposted this/commented on this/3rd+' "
                      "inside <main> — posts may be in an iframe or rendered into shadow DOM.",
                      flush=True)
        else:
            print(f"[POST] diagnostic — DOM probe returned unexpected: {buckets!r}", flush=True)
    except Exception as exc:
        print(f"[POST] diagnostic — DOM probe failed: {exc}", flush=True)
    try:
        os.makedirs(ERROR_SCREENSHOT_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(ERROR_SCREENSHOT_DIR, f"feed-empty-{stamp}.png")
        page.screenshot(path=path, full_page=True)
        print(f"[POST] diagnostic — screenshot saved: {path}", flush=True)
    except Exception as exc:
        print(f"[POST] diagnostic — screenshot failed: {exc}", flush=True)


def _scrape_feed_batch(page, search_url: str, target: int) -> list[dict]:
    """Scroll the feed until ~target new posts are scraped (or the scroll budget
    runs out). Returns a list of post-detail dicts ready for evaluation. Deduped
    via history. Uses scrape_feed_via_js() — a content-anchored JS scraper that
    survives LinkedIn's obfuscated CSS-in-JS class names."""
    batch: list[dict] = []
    seen_ids: set[str] = set()

    for scroll_i in range(POST_BATCH_MAX_SCROLLS + 1):
        scraped_posts = scrape_feed_via_js(page)
        print(f"[POST] JS scrape pass {scroll_i+1}: {len(scraped_posts)} candidates", flush=True)
        if scroll_i == 0 and not scraped_posts:
            # Selector-based fallback diagnostic — gives us obfuscated-class info
            # in case the JS scraper also failed to find Like-button anchors.
            _collect_post_locators(page)
            _diagnose_feed_state(page)

        for scraped in scraped_posts:
            try:
                content = scraped.get("content") or ""
                if not content:
                    continue
                # Prefer post_url permalink, then author_url + normalized body,
                # then normalized body — see _stable_post_id. The previous
                # naive sha1(content) hash flipped on every reload because the
                # JS scraper included reaction/comment counts and relative
                # timestamps, so the same post slipped past dedup each refill.
                urn = scraped.get("urn")
                post_id = f"post_urn:{_hash(urn)}" if urn else _stable_post_id(scraped)
                if not post_id:
                    continue
                if post_id in seen_ids:
                    continue
                if is_processed("posts", post_id):
                    seen_ids.add(post_id)
                    continue

                details = {
                    **scraped,
                    "identifier": post_id,
                    "source_url": page.url,
                    "search_url": search_url,
                }
                batch.append(details)
                seen_ids.add(post_id)
                mark_processed("posts", post_id)

                if len(batch) >= target:
                    return batch
            except Exception:
                continue

        if len(batch) >= target or scroll_i == POST_BATCH_MAX_SCROLLS:
            break
        # Scroll to load more posts. Mouse-wheel triggers LinkedIn's intersection-
        # observer-based lazy loader more reliably than evaluate-scroll.
        try:
            page.mouse.wheel(0, 2500)
        except Exception:
            pass
        random_sleep(2, 4)

    return batch


FEED_BATCH_TAG = "home_feed"
SEARCH_BATCH_TAG_PREFIX = "search"

# Appended to the role when building the search-bar fallback query.
POST_SEARCH_KEYWORDS = os.getenv("POST_SEARCH_KEYWORDS", "hiring")
# LinkedIn content-search recency filter: "past-24h" | "past-week" | "past-month" | "" (no filter).
POST_SEARCH_RECENT = os.getenv("POST_SEARCH_RECENT", "past-week")


def _build_post_search_url(role: str) -> str:
    """Build a LinkedIn content-search URL biased toward recent hiring posts."""
    query = f"{role} {POST_SEARCH_KEYWORDS}".strip()
    url = (
        f"https://www.linkedin.com/search/results/content/"
        f"?keywords={quote(query)}&sortBy=%22date_posted%22"
    )
    if POST_SEARCH_RECENT:
        url += f"&datePosted=%22{POST_SEARCH_RECENT}%22"
    return url


def _scrape_search_batch(page, role: str, target: int) -> tuple[list[dict], str]:
    """Search-bar fallback for POST mode: navigate to the LinkedIn content search
    with `<role> hiring` (recent + date-sorted) and scrape with the same JS
    scraper used on the home feed. Returns (batch, search_url)."""
    url = _build_post_search_url(role)
    print(f"[POST] Fallback → content search ({role!r}): {url}", flush=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"[POST] search navigation error: {e}", flush=True)
    random_sleep(3, 5)
    batch = _scrape_feed_batch(page, url, target)
    return batch, url


def search_post_node(state: AgentState) -> dict:
    """POST mode is batch-driven: navigate to the LinkedIn home feed, scroll to
    load ~POST_BATCH_TARGET posts into a queue, then yield ONE per call so the
    evaluate node can decide APPLY / DRAFT_EMAIL / DRAFT_DM / SKIP per post.

    NOTE: this scrapes the user's actual home feed (https://www.linkedin.com/feed/)
    rather than running a /search/results/content query. Role rotation no longer
    drives navigation — the feed is the feed."""
    _pause_gate("search_post")
    bm = BrowserManager(headless=state.get("headless", True))
    page = bm.get_page()

    queue = list(state.get("posts_queue") or [])

    # Pop next post from existing queue. This is the "evaluate one by one" path —
    # no scraping, just hand the next item to the evaluate node.
    if queue:
        details = queue.pop(0)
        bump = _bump_iteration(state, True)
        print(f"[POST] Yield queued post ({len(queue)} remaining) — {details.get('author','?')[:60]}", flush=True)
        return {
            "current_url": details.get("search_url") or page.url,
            "post_details": details,
            "job_details": {},
            "profile_details": {},
            "action_taken": "SEARCHED_POST",
            "posts_queue": queue,
            "posts_batch_role": FEED_BATCH_TAG,
            **bump,
        }

    # Queue empty: navigate to /feed/ and refill by scrolling.
    print("[POST] Refilling batch — navigating to home feed", flush=True)
    url = goto_home_feed(page)
    batch = _scrape_feed_batch(page, url, POST_BATCH_TARGET)
    print(f"[POST] Scraped batch of {len(batch)} new posts from home feed", flush=True)
    batch_tag = FEED_BATCH_TAG

    # Home feed yielded nothing new → fall back to the LinkedIn search bar,
    # biased toward recent hiring posts for the next configured role. Role
    # rotates per refill so a long empty streak hits every role in turn.
    if not batch:
        role = _pick_role(state)
        search_batch, search_url = _scrape_search_batch(page, role, POST_BATCH_TARGET)
        print(f"[POST] Scraped batch of {len(search_batch)} new posts from search (role={role!r})", flush=True)
        if search_batch:
            batch = search_batch
            url = search_url
            batch_tag = f"{SEARCH_BATCH_TAG_PREFIX}:{role}"

    if not batch:
        streak = int(state.get("empty_streak", 0)) + 1
        lo, hi = _empty_backoff(streak)
        print(f"[POST] No new posts on feed or search. Sleeping {lo}-{hi}s (streak={streak})...", flush=True)
        random_sleep(lo, hi)
        bump = _bump_iteration(state, False)
        return {
            "current_url": url,
            "post_details": {},
            "job_details": {},
            "profile_details": {},
            "action_taken": "SEARCHED_EMPTY",
            "posts_queue": [],
            "posts_batch_role": FEED_BATCH_TAG,
            **bump,
        }

    details = batch.pop(0)
    bump = _bump_iteration(state, True)
    return {
        "current_url": url,
        "post_details": details,
        "job_details": {},
        "profile_details": {},
        "action_taken": "SEARCHED_POST",
        "posts_queue": batch,
        "posts_batch_role": batch_tag,
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

    bm = BrowserManager(headless=state.get("headless", True))
    page = bm.get_page()
    success, reason = apply_easy_apply(page, job, llm_model=state.get("llm_model"))
    if success:
        new_total = applications_db.record_application()
        print(f"[Apply] APPLIED — today's total: {new_total}/{applications_db.DEFAULT_DAILY_CAP}", flush=True)
        return {"action_taken": "APPLIED"}
    # Use only the failure tag (before any space/parens) for the screenshot filename + incident kind.
    short_reason = (reason or "unknown").split(" ", 1)[0].split("(", 1)[0].strip() or "unknown"

    # LinkedIn's per-account daily-submission cap was hit. Stop the agent cleanly so we
    # don't keep clicking — the next job won't go any better today, and continuing risks
    # an account flag. The current job is also queued in Leads below for tomorrow.
    if short_reason == "daily_limit_reached":
        msg = (
            "LinkedIn daily submission limit reached. Stopping the agent — save this job and "
            "apply tomorrow. (Other jobs you may have queued today are visible in the Leads tab.)"
        )
        print(f"[Apply] {msg}", flush=True)
        try:
            external_leads.add(
                title=job.get("title") or "?",
                company=job.get("company") or "?",
                url=job.get("source_url") or job.get("url") or "",
                destination_url="",
                reason="daily_limit_reached",
                search_url=job.get("search_url", ""),
                job_identifier=job.get("identifier", ""),
            )
        except Exception:
            pass
        try:
            run_control.request_stop()
        except Exception:
            pass
        return {
            "action_taken": "SKIP",
            "errors": state.get("errors", []) + [msg],
        }

    _snapshot(page, f"apply-{short_reason}")
    title = job.get("title") or "?"
    company = job.get("company") or "?"
    url = job.get("source_url") or job.get("url") or ""
    job_ctx = f"{title} @ {company}" + (f" — {url}" if url else "")
    is_external = (reason or "").startswith("external_apply")
    # `modal_did_not_open` is almost always an external/ATS apply that we couldn't
    # detect via URL/text heuristics — treat it as a lead, not a bug.
    treat_as_lead = is_external or short_reason == "modal_did_not_open"

    # Pull the destination URL out of the reason string when present:
    # "external_apply (signal) → https://workday.com/..."
    dest = ""
    if " → " in (reason or ""):
        try:
            dest = reason.split(" → ", 1)[1].strip().split(" ", 1)[0]
        except Exception:
            dest = ""
    # ALWAYS store unrecoverable apply failures as a lead so the user has one place
    # (the Leads tab) to review every job the bot couldn't auto-submit.
    try:
        external_leads.add(
            title=title,
            company=company,
            url=url,
            destination_url=dest,
            reason=reason or short_reason,
            search_url=job.get("search_url", ""),
            job_identifier=job.get("identifier", ""),
        )
        print(f"[Apply] Stored lead for manual review: {title} @ {company} ({url})", flush=True)
    except Exception as exc:
        print(f"[Apply] Failed to store lead: {exc}", flush=True)

    if treat_as_lead:
        # External-ATS / unopenable modal — not a true apply failure.
        return {
            "action_taken": "EXTERNAL_LEAD",
            "errors": state.get("errors", []) + [f"External lead [{job_ctx}]: {reason or short_reason}"],
        }
    # Genuine apply failure (validation_error after retries, stuck_unknown_form, exception…)
    # — still moves to next job, but it's queued in the Leads tab for your attention.
    return {
        "action_taken": "APPLY_FAILED",
        "errors": state.get("errors", []) + [f"Apply failed [{job_ctx}]: {reason or 'unknown'}"],
    }


def network_node(state: AgentState) -> dict:
    """Empty invite + queued personalized DM (mirrors draft_dm_node for POST mode).

    1st-degree connections → DM the LLM-generated message directly.
    2nd/3rd-degree → send an EMPTY connection request, queue the DM in
    state/pending_connections.json. The background sweeper visits the profile
    DM_RIPENING_SECONDS after acceptance and sends the queued message — same
    pipeline used by POST-mode hiring outreach."""
    _pause_gate("network")
    profile = state.get("profile_details") or {}
    name = (profile.get("name") or "there").strip()
    profile_url = (profile.get("source_url") or "").strip()
    if not profile_url:
        # source_url isn't set when extract_profile_details ran on a stale tab;
        # normalize the identifier (which is href-stripped-of-query) as a fallback.
        profile_url = _linkedin_url(profile.get("identifier") or "")

    draft_msg = (state.get("draft_message") or "").strip()
    if not draft_msg:
        # LLM produced nothing — fall back to a minimal template so we still attempt
        # outreach. Better than dropping the lead silently.
        draft_msg = f"Hi {name}, I came across your profile and would love to connect."

    if not profile_url:
        return {
            "action_taken": "NETWORK_FAILED",
            "errors": state.get("errors", []) + [f"No profile URL for {name}"],
        }

    if pending_db.has_pending(profile_url):
        print(f"[Connect] Already pending for {name} — skipping duplicate invite.", flush=True)
        return {"action_taken": "NETWORKED"}

    if state.get("dry_run"):
        msg = f"[DRY_RUN] Would CONNECT+QUEUE_DM (or direct DM if 1st°) → {name} ({profile_url})"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_NETWORK", "errors": state.get("errors", []) + [msg]}

    bm = BrowserManager(headless=state.get("headless", True))
    page = bm.get_page()

    # 1st-degree → DM directly; no connection request needed.
    if is_first_degree_connection(page, profile_url):
        print(f"[Connect] {name} is already a 1st-degree connection — DMing directly.", flush=True)
        ok, reason = send_dm_to_profile(page, profile_url, draft_msg)
        # `already_messaged` = there's a prior conversation. Treat as success
        # so we never stack on top of an existing thread, and record it as
        # dm_sent in pending_db so we don't re-attempt next run.
        if not ok and reason == "already_messaged":
            print(f"[Connect] {name} already has an existing conversation — not sending.", flush=True)
            try:
                pending_db.add_pending(
                    profile_url=profile_url, name=name,
                    post_id="", post_content="", queued_dm=draft_msg,
                )
                pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
            except Exception:
                pass
            return {"action_taken": "NETWORKED"}
        if not ok:
            _snapshot(page, f"network-direct-dm-{reason}")
            return {
                "action_taken": "NETWORK_FAILED",
                "errors": state.get("errors", []) + [f"Direct DM failed [{name} — {profile_url}]: {reason}"],
            }
        try:
            pending_db.add_pending(
                profile_url=profile_url,
                name=name,
                post_id="",
                post_content="",
                queued_dm=draft_msg,
            )
            pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
        except Exception:
            pass
        return {"action_taken": "NETWORKED"}

    # 2nd/3rd → empty connection request; sweeper sends the queued DM after acceptance.
    if not pending_db.can_send_today():
        msg = f"Daily connection cap reached ({pending_db.DEFAULT_DAILY_CAP}/day). Skipping {name}."
        print(f"[Connect] {msg}", flush=True)
        return {"action_taken": "SKIP", "errors": state.get("errors", []) + [msg]}

    ok, reason = send_empty_connection(page, profile_url)
    if not ok:
        _snapshot(page, f"network-connect-{reason}")
        return {
            "action_taken": "NETWORK_FAILED",
            "errors": state.get("errors", []) + [f"Connect failed [{name} — {profile_url}]: {reason}"],
        }

    pending_db.add_pending(
        profile_url=profile_url,
        name=name,
        post_id="",
        post_content="",
        queued_dm=draft_msg,
    )
    print(f"[Connect] Sent empty invite to {name} ({profile_url}); DM queued for sweeper.", flush=True)
    return {"action_taken": "NETWORKED"}


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
    success, gmail_reason = create_gmail_draft(to_email, subject, draft_msg)

    # ALWAYS persist the email decision — even when Gmail fails — so the user can
    # see what the bot wanted to send. With Gmail unauthenticated, the body is
    # still useful: they can copy-paste it into a manual email.
    post = state.get("post_details") or {}
    record_status = (
        "drafted" if success
        else "gmail_unauth" if gmail_reason == "unauthenticated"
        else "gmail_failed"
    )
    try:
        outreach.record_draft(
            to_email=to_email,
            subject=subject,
            body=draft_msg,
            post_author=post.get("author") or "",
            post_url=post.get("post_url") or post.get("source_url") or "",
            post_excerpt=(post.get("content") or "")[:500],
            match_score=state.get("match_score"),
            status=record_status,
            error="" if success else gmail_reason,
        )
    except Exception as exc:
        print(f"[Email] failed to record outreach: {exc}", flush=True)

    if success:
        return {"action_taken": "DRAFTED_EMAIL"}

    # Bubble the Gmail failure to the run log so the user sees WHY no Gmail draft
    # appeared. The outreach record above already preserves the body.
    user_facing = (
        "Gmail not authenticated — set up token.json (see setup_auth.py). "
        "Drafted body saved in Outreach → Emails drafted with status gmail_unauth."
        if gmail_reason == "unauthenticated" else
        f"Gmail draft creation failed: {gmail_reason}. Body saved in Outreach."
    )
    return {
        "action_taken": "DRAFT_FAILED",
        "errors": state.get("errors", []) + [user_facing],
    }


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

    if state.get("dry_run"):
        msg = f"[DRY_RUN] Would CONNECT+QUEUE_DM (or direct DM if 1st°) → {author_name} ({profile_url})"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_DM", "errors": state.get("errors", []) + [msg]}

    bm = BrowserManager(headless=state.get("headless", True))
    page = bm.get_page()

    # 1st-degree → DM directly; no connection request needed.
    if is_first_degree_connection(page, profile_url):
        print(f"[Connect] {author_name} is already a 1st-degree connection — DMing directly.", flush=True)
        ok, reason = send_dm_to_profile(page, profile_url, draft_msg)
        # already_messaged = prior thread exists; don't stack a new DM on top.
        if not ok and reason == "already_messaged":
            print(f"[Connect] {author_name} already has an existing conversation — not sending.", flush=True)
            try:
                pending_db.add_pending(
                    profile_url=profile_url, name=author_name,
                    post_id=post.get("identifier") or "",
                    post_content=post.get("content") or "",
                    queued_dm=draft_msg,
                )
                pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
            except Exception:
                pass
            return {"action_taken": "DRAFTED_DM"}
        if not ok:
            _snapshot(page, f"dm-direct-{reason}")
            return {
                "action_taken": "DRAFT_FAILED",
                "errors": state.get("errors", []) + [f"Direct DM failed [{author_name} — {profile_url}]: {reason}"],
            }
        try:
            pending_db.add_pending(
                profile_url=profile_url,
                name=author_name,
                post_id=post.get("identifier") or "",
                post_content=post.get("content") or "",
                queued_dm=draft_msg,
            )
            pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
        except Exception:
            pass
        return {"action_taken": "DRAFTED_DM"}

    # 2nd/3rd → connection request first; DM is queued and sent by the sweeper
    # after acceptance + a 10-minute ripening delay.
    if not pending_db.can_send_today():
        msg = f"Daily connection cap reached ({pending_db.DEFAULT_DAILY_CAP}/day). Skipping {author_name}."
        print(f"[Connect] {msg}", flush=True)
        return {"action_taken": "SKIP", "errors": state.get("errors", []) + [msg]}

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
    print(f"[Connect] Sent empty invite to {author_name} ({profile_url}); DM queued for sweeper.", flush=True)
    return {"action_taken": "DRAFTED_DM"}


def external_link_node(state: AgentState) -> dict:
    """Hiring post that says 'apply here' with an external/ATS URL — persist it
    so the user can apply manually. Bot does NOT auto-click."""
    _pause_gate("external_link")
    post = state.get("post_details") or {}
    apply_url = state.get("apply_url") or post.get("attached_job_url") or ""
    if not apply_url:
        return {
            "action_taken": "SKIP",
            "errors": state.get("errors", []) + ["external_link_node called without apply_url"],
        }
    if state.get("dry_run"):
        msg = f"[DRY_RUN] Would record APPLY-LINK → {apply_url}"
        print(msg, flush=True)
        return {"action_taken": "DRY_RUN_LINK", "errors": state.get("errors", []) + [msg]}
    try:
        added = apply_link.record_link(
            apply_url=apply_url,
            post_author=post.get("author") or "",
            post_url=post.get("post_url") or post.get("source_url") or "",
            post_excerpt=(post.get("content") or "")[:500],
            match_score=state.get("match_score"),
        )
        if added:
            print(f"[Link] Recorded apply-link: {apply_url}", flush=True)
        else:
            print(f"[Link] Duplicate apply-link skipped: {apply_url}", flush=True)
    except Exception as exc:
        print(f"[Link] Failed to record apply-link: {exc}", flush=True)
        return {"action_taken": "EXTERNAL_LINK_FAILED", "errors": state.get("errors", []) + [str(exc)]}
    return {"action_taken": "EXTERNAL_LINK_RECORDED"}


DM_RIPENING_SECONDS = int(os.getenv("DM_RIPENING_SECONDS", "600"))  # 10 min by default


def check_pending_connections(headless: bool = True, max_to_dm: int = 20) -> dict:
    """Sweeper sweep. Two passes:

      1. Pending → re-check status. If LinkedIn now shows a Message button
         (acceptance), flip status to 'accepted' and stamp accepted_at.
      2. Accepted + ripened (accepted_at older than DM_RIPENING_SECONDS) →
         actually send the queued DM and flip status to 'dm_sent'.

    The 10-minute delay between acceptance and DM is the human-realism gate
    the user asked for — sending a DM the moment a connection accepts looks
    obviously bot-driven."""
    still_pending_items = pending_db.list_items(status="pending")
    ripened = pending_db.ripened_accepted_items(DM_RIPENING_SECONDS)

    if not still_pending_items and not ripened:
        return {
            "checked": 0, "accepted": 0, "dm_sent": 0,
            "dm_failed": 0, "still_pending": 0, "still_ripening": 0,
        }

    bm = BrowserManager(headless=headless)
    main_page = bm.get_page()
    username = os.getenv("LINKEDIN_USERNAME")
    password = os.getenv("LINKEDIN_PASSWORD")
    if username and password:
        login_if_needed(main_page, username, password)

    checked = accepted = dm_sent = dm_failed = still_pending = 0

    def _scoped_tab():
        """Open a fresh tab in the same browser context (shared session) so the
        main page state is preserved across sweeper visits. Caller MUST close
        it via try/finally — leaving tabs open leaks memory and clutters the
        non-headless UI."""
        return bm.context.new_page()

    # Pass 1: refresh status of every pending invite. Each check runs in its
    # own tab that gets closed before moving on.
    for it in still_pending_items[:max_to_dm]:
        profile_url = it.get("profile_url") or ""
        if not profile_url:
            continue
        checked += 1
        tab = _scoped_tab()
        try:
            status = check_connection_status(tab, profile_url)
        except Exception as exc:
            print(f"[CheckPending] status check error for {it.get('name')}: {exc}", flush=True)
            status = "unknown"
        finally:
            try:
                tab.close()
            except Exception:
                pass
        if status == "accepted":
            accepted += 1
            pending_db.update_status(profile_url, "accepted", mark_accepted=True)
            print(f"[CheckPending] Accepted: {it.get('name')} — DM will ripen for {DM_RIPENING_SECONDS//60} min.", flush=True)
        elif status == "pending":
            still_pending += 1
            pending_db.update_status(profile_url, "pending")
        else:
            still_pending += 1
        random_sleep(3, 6)

    # Pass 2: send queued DMs for entries that have ripened. Same per-tab pattern.
    for it in ripened[:max_to_dm]:
        profile_url = it.get("profile_url") or ""
        if not profile_url:
            continue
        msg = it.get("queued_dm") or ""
        if not msg.strip():
            pending_db.update_status(profile_url, "dm_failed")
            dm_failed += 1
            continue
        tab = _scoped_tab()
        try:
            ok, reason = send_dm_to_profile(tab, profile_url, msg)
        except Exception as exc:
            print(f"[CheckPending] DM exception for {it.get('name')}: {exc}", flush=True)
            ok, reason = False, f"exception:{type(exc).__name__}"
        finally:
            try:
                tab.close()
            except Exception:
                pass
        if ok:
            pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
            dm_sent += 1
            print(f"[CheckPending] DM sent (ripened) to {it.get('name')}", flush=True)
        elif reason == "already_messaged":
            pending_db.update_status(profile_url, "dm_sent", dm_sent=True)
            dm_sent += 1
            print(f"[CheckPending] {it.get('name')} already has an existing conversation — marking dm_sent.", flush=True)
        else:
            pending_db.update_status(profile_url, "dm_failed")
            dm_failed += 1
            print(f"[CheckPending] DM failed for {it.get('name')}: {reason}", flush=True)
        random_sleep(3, 6)

    still_ripening = max(0, len(pending_db.list_items(status="accepted")) - dm_sent - dm_failed)
    return {
        "checked": checked,
        "accepted": accepted,
        "dm_sent": dm_sent,
        "dm_failed": dm_failed,
        "still_pending": still_pending,
        "still_ripening": still_ripening,
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

    if action in ("APPLY", "NETWORK", "DRAFT_EMAIL", "DRAFT_DM", "EXTERNAL_LINK"):
        return {
            "APPLY": "apply",
            "NETWORK": "network",
            "DRAFT_EMAIL": "draft_email",
            "DRAFT_DM": "draft_dm",
            "EXTERNAL_LINK": "external_link",
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
    workflow.add_node("external_link", external_link_node)

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
            "external_link": "external_link",
            "search_job": "search_job",
            "search_person": "search_person",
            "search_post": "search_post",
            "end": END,
        },
    )

    for node in ("apply", "network", "draft_email", "draft_dm", "external_link"):
        workflow.add_conditional_edges(
            node,
            router,
            {"search_job": "search_job", "search_person": "search_person", "search_post": "search_post", "end": END},
        )

    return workflow.compile()
