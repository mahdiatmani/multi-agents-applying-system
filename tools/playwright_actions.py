import re
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
    # Treat "Any", "", and whitespace-only company values as "no company filter"
    # — otherwise LinkedIn literally searches for profiles containing the word
    # "Any" and almost always returns nothing.
    company_clean = (company or "").strip()
    if company_clean.lower() in {"", "any"}:
        query = (keywords or "").strip()
    else:
        query = f"{(keywords or '').strip()} {company_clean}".strip()
    q = urllib.parse.quote(query)
    url = f"https://www.linkedin.com/search/results/people/?keywords={q}"
    page.goto(url)
    random_sleep(4, 8)
    return page.url


def _first_text(page, selectors: tuple[str, ...]) -> str:
    """Return inner_text of the first visible match across selectors, or ''."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if not _visible(loc):
                continue
            txt = (loc.inner_text(timeout=800) or "").strip()
            if txt:
                return txt
        except Exception:
            continue
    return ""


def _meta_content(page, *props_or_names: str) -> str:
    """Read <meta property=X content=...> or <meta name=X content=...> for any
    of the given keys. Stable extraction path that survives CSS-class churn."""
    for key in props_or_names:
        for sel in (f"meta[property='{key}']", f"meta[name='{key}']"):
            try:
                loc = page.locator(sel).first
                if not loc.count():
                    continue
                content = loc.get_attribute("content")
                if content and content.strip():
                    return content.strip()
            except Exception:
                continue
    return ""


def _name_from_page_title(page) -> str:
    """LinkedIn profile <title> follows 'NAME - HEADLINE | LinkedIn'. Strip the
    notification-count prefix '(99+) ' and the ' | LinkedIn' suffix."""
    import re as _re
    try:
        raw = (page.title() or "").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    raw = _re.sub(r"^\(\d+\+?\)\s*", "", raw).strip()  # drop "(99+) " prefix
    raw = raw.replace(" | LinkedIn", "").strip()
    name = raw.split(" - ", 1)[0].split(" | ", 1)[0].strip()
    if not name or name.lower() == "linkedin":
        return ""
    return name


_PROFILE_SECTION_JS = """
(sectionKey) => {
  // sectionKey: 'about' | 'experience' | 'education' | ...
  // Three fallback strategies, in order of stability:
  //   1. id anchor (legacy DOM — div#about, div#experience, ...)
  //   2. <section componentkey="...<SectionName>TopLevelSection"> — current
  //      LinkedIn DOM. componentkey for experience looks like
  //      "com.linkedin.sdui.profile.card.refACoAA...ExperienceTopLevelSection",
  //      so substring match on the lowercased key is what works.
  //   3. <h2> with text matching the section name in any supported locale —
  //      walk up to nearest <section>. Last-resort cover for DOMs that ship
  //      neither id anchors nor componentkey-based section markers.
  //
  // Text reader: innerText only returns rendered text. LinkedIn lazy-loads
  // sections below the fold — even though the section's HTML may be present,
  // its descendants aren't rendered until scrolled into view, so innerText is
  // empty. textContent reads ALL text including unrendered nodes. We try
  // innerText first (clean, with line breaks) and fall back to textContent
  // (raw but always present). The caller still scrolls before invoking, so
  // most calls hit the innerText branch.
  const readText = (el) => {
    if (!el) return '';
    const rendered = (el.innerText || '').trim();
    if (rendered) return rendered.length > 6000 ? rendered.slice(0, 6000) : rendered;
    const raw = (el.textContent || '').replace(/\\s+/g, ' ').trim();
    return raw.length > 6000 ? raw.slice(0, 6000) : raw;
  };

  // ── Strategy 1: id anchor ──
  const anchor = document.getElementById(sectionKey);
  if (anchor) {
    let el = anchor;
    while (el && el.tagName !== 'SECTION') el = el.parentElement;
    const txt = readText(el);
    if (txt) return txt;
  }

  // ── Strategy 2: componentkey substring match ──
  const target = sectionKey.toLowerCase();
  const sections = document.querySelectorAll('section[componentkey]');
  for (const s of sections) {
    const key = (s.getAttribute('componentkey') || '').toLowerCase();
    if (key.includes(target)) {
      const txt = readText(s);
      if (txt) return txt;
    }
  }

  // ── Strategy 3: <h2> with section-name text → walk up to the entity-item
  // container (NOT to <section>). Current LinkedIn often wraps Experience in a
  // generic <div> with no <section> ancestor, which caused walks-to-<section>
  // to escape the card and grab unrelated content. The reliable structural
  // marker is `[componentkey^="entity-collection-item"]` — every employer row
  // has one. We walk up until we find a container holding at least one such
  // child, that's the section body. ──
  const NAMES = {
    about:      ['about', 'à propos', 'a propos', 'acerca de', 'über', 'uber', 'su di me', 'sobre'],
    experience: ['experience', 'expérience', 'experience pro', 'experiencia', 'erfahrung', 'esperienza', 'experiência', 'experiencia profesional'],
    education:  ['education', 'formation', 'educación', 'ausbildung', 'istruzione', 'educação', 'formación'],
  };
  const candidates = NAMES[target] || [target];

  const walkUpToCardContainer = (start) => {
    let el = start;
    for (let i = 0; i < 12 && el; i++) {
      const items = el.querySelectorAll('[componentkey^="entity-collection-item"]');
      if (items.length >= 1) return el;
      el = el.parentElement;
    }
    return null;
  };

  const h2s = document.querySelectorAll('h2');
  for (const h2 of h2s) {
    const text = (h2.innerText || h2.textContent || '').trim().toLowerCase();
    if (!text) continue;
    if (!candidates.some(n => text === n || text.startsWith(n + ' ') || text.startsWith(n))) continue;
    // Prefer the entity-item-bearing ancestor over the nearest <section>.
    const card = walkUpToCardContainer(h2);
    if (card) {
      const txt = readText(card);
      if (txt && txt.length > 30) return txt;
    }
    // Fallback: nearest <section>.
    let el = h2;
    while (el && el.tagName !== 'SECTION') el = el.parentElement;
    const txt = readText(el);
    if (txt && txt.length > 30) return txt;
  }

  // ── Strategy 4: structural fingerprint — find a container with multiple
  // entity-collection-item children AND /company/ (experience) or /school/
  // (education) links inside. This is what Kaoutar FAIZ's profile needed:
  // her Experience block has neither a `...Experience...` componentkey nor a
  // <h2>Experience</h2> heading at scrape time, but it DOES have the
  // entity-collection-item structure + /company/ links — that's invariant
  // across every LinkedIn DOM variant we've seen. ──
  if (target === 'experience' || target === 'education') {
    const linkPath = target === 'education' ? '/school/' : '/company/';
    let best = null;
    let bestScore = 0;
    const seen = new WeakSet();
    for (const item of document.querySelectorAll('[componentkey^="entity-collection-item"]')) {
      let el = item.parentElement;
      for (let i = 0; i < 8 && el; i++) {
        if (seen.has(el)) { el = el.parentElement; continue; }
        seen.add(el);
        const items = el.querySelectorAll('[componentkey^="entity-collection-item"]');
        const links = el.querySelectorAll('a[href*="' + linkPath + '"]');
        if (items.length >= 1 && links.length >= 1) {
          // Score = items*2 + links. Best ancestor is the smallest wrapper
          // holding ALL employer cards — usually the immediate parent.
          const score = items.length * 2 + links.length;
          if (score > bestScore) {
            bestScore = score;
            best = el;
          }
        }
        el = el.parentElement;
      }
    }
    if (best) {
      const txt = readText(best);
      if (txt) return txt;
    }
  }

  // ── Strategy 5: about — walk from any matching h2 to a paragraph-bearing
  // ancestor. Less aggressive than Strategy 3 because About has no
  // entity-collection-item children, just one or more <p>/<span> blobs. ──
  if (target === 'about') {
    for (const h2 of h2s) {
      const text = (h2.innerText || h2.textContent || '').trim().toLowerCase();
      if (!text) continue;
      if (!candidates.some(n => text === n || text.startsWith(n + ' '))) continue;
      let el = h2.parentElement;
      for (let i = 0; i < 6 && el; i++) {
        const paras = el.querySelectorAll('p, span');
        if (paras.length >= 2) {
          const txt = readText(el);
          if (txt && txt.length > 30) return txt;
        }
        el = el.parentElement;
      }
    }
  }

  return '';
}
"""


_SCROLL_SECTION_INTO_VIEW_JS = r"""
(sectionKey) => {
  const target = sectionKey.toLowerCase();
  // Strategy A: section with componentkey containing the section name.
  for (const s of document.querySelectorAll('section[componentkey]')) {
    const k = (s.getAttribute('componentkey') || '').toLowerCase();
    if (k.includes(target)) {
      s.scrollIntoView({behavior: 'auto', block: 'center'});
      return 'componentkey';
    }
  }
  // Strategy B: id anchor (legacy DOM).
  const anchor = document.getElementById(sectionKey);
  if (anchor) {
    anchor.scrollIntoView({behavior: 'auto', block: 'center'});
    return 'id';
  }
  // Strategy C: <h2> with matching text in any locale.
  const NAMES = {
    about:      ['about', 'à propos', 'a propos', 'acerca de', 'über', 'uber', 'su di me', 'sobre'],
    experience: ['experience', 'expérience', 'experiencia', 'erfahrung', 'esperienza', 'experiência'],
    education:  ['education', 'formation', 'educación', 'ausbildung', 'istruzione', 'educação'],
  };
  const candidates = NAMES[target] || [target];
  for (const h2 of document.querySelectorAll('h2')) {
    const text = (h2.innerText || h2.textContent || '').trim().toLowerCase();
    if (!text) continue;
    if (candidates.some(n => text === n || text.startsWith(n + ' '))) {
      h2.scrollIntoView({behavior: 'auto', block: 'center'});
      return 'h2';
    }
  }
  return '';
}
"""


def _prime_profile_lazy_load(page) -> None:
    """Force-render the sections we care about by scrolling each one into view.

    LinkedIn lazy-mounts below-the-fold sections via IntersectionObserver. A
    blind scroll-by-pixel works for About (which is right under the top card)
    but misses Experience on profiles where About is long — exactly the
    Kaoutar FAIZ failure mode where About scraped but Experience came back
    empty.

    Approach: explicitly `scrollIntoView` each target section by its
    componentkey / id / h2 text, with a 600ms settle between scrolls so React
    can mount the children. Then return to the top so subsequent top-card
    button lookups (Connect/Message) still hit the right elements."""
    try:
        # First: an incremental pre-scroll so React begins mounting things.
        for offset in (600, 1400, 2400):
            page.evaluate(f"window.scrollTo({{top: {offset}, behavior: 'auto'}})")
            page.wait_for_timeout(250)

        # Then: target each section directly. Experience first — it's the field
        # we care about most for the compatibility decision.
        for key in ("experience", "about", "education"):
            try:
                hit = page.evaluate(_SCROLL_SECTION_INTO_VIEW_JS, key)
                if hit:
                    page.wait_for_timeout(600)
            except Exception:
                continue

        page.evaluate("window.scrollTo({top: 0, behavior: 'auto'})")
        page.wait_for_timeout(250)
    except Exception as exc:
        print(f"[Profile] lazy-load scroll failed: {exc}", flush=True)


def _section_text(page, anchor_id: str) -> str:
    try:
        return (page.evaluate(_PROFILE_SECTION_JS, anchor_id) or "").strip()
    except Exception:
        return ""


# Dump diagnostic info on extraction failures so we can debug specific profiles
# without having to live-attach to the bot. Captures the URL, the title, the
# top-card text, the section componentkeys present, h2 headings, and the full
# page HTML — that's enough to reproduce a failure locally with a static fixture.
def _dump_profile_debug(page, details: dict) -> None:
    import os as _os
    from datetime import datetime as _dt
    dump_dir = _os.path.join(_os.path.dirname(__file__), "..", "state", "debug")
    _os.makedirs(dump_dir, exist_ok=True)
    stamp = _dt.now().strftime("%Y%m%d-%H%M%S")
    slug = "unknown"
    try:
        slug = (page.url or "").rstrip("/").split("/in/", 1)[-1].split("/", 1)[0] or "unknown"
    except Exception:
        pass

    probe_js = r"""
    () => {
      const out = {};
      try { out.url = location.href; } catch(e){}
      try { out.title = document.title; } catch(e){}
      const sections = Array.from(document.querySelectorAll('section[componentkey]'));
      out.sectionKeys = sections.slice(0, 30).map(s => (s.getAttribute('componentkey') || '').slice(0, 200));
      out.h2s = Array.from(document.querySelectorAll('h2')).slice(0, 30).map(h => ({
        text: (h.innerText || h.textContent || '').trim().slice(0, 80),
        parentSectionKey: (() => {
          let el = h; while (el && el.tagName !== 'SECTION') el = el.parentElement;
          return el ? (el.getAttribute('componentkey') || '').slice(0, 200) : '';
        })(),
      }));
      // Try to read the experience section right now and report its visible text.
      const expSections = sections.filter(s => (s.getAttribute('componentkey')||'').toLowerCase().includes('experience'));
      if (expSections.length) {
        const s = expSections[0];
        out.expInnerText = (s.innerText || '').slice(0, 1500);
        out.expTextContent = (s.textContent || '').slice(0, 1500);
        out.expChildCount = s.children.length;
      } else {
        out.expInnerText = '';
        out.expTextContent = '';
        out.expChildCount = 0;
      }
      return out;
    }
    """
    try:
        probe = page.evaluate(probe_js) or {}
    except Exception as exc:
        probe = {"error": str(exc)}

    # Write a JSON summary.
    import json as _json
    summary_path = _os.path.join(dump_dir, f"profile-{slug}-{stamp}.json")
    payload = {
        "url": probe.get("url"),
        "title": probe.get("title"),
        "extracted": {k: (v if isinstance(v, (str, int, float)) else str(v))[:300] if isinstance(v, str) else v
                      for k, v in details.items()},
        "section_componentkeys": probe.get("sectionKeys", []),
        "h2s": probe.get("h2s", []),
        "experience_section_probe": {
            "child_count": probe.get("expChildCount"),
            "innerText_len": len(probe.get("expInnerText") or ""),
            "textContent_len": len(probe.get("expTextContent") or ""),
            "innerText_sample": (probe.get("expInnerText") or "")[:800],
            "textContent_sample": (probe.get("expTextContent") or "")[:800],
        },
    }
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"[Profile] DEBUG: wrote diagnostic to {summary_path}", flush=True)
    except Exception as exc:
        print(f"[Profile] DEBUG: failed to write summary: {exc}", flush=True)

    # And the full HTML for offline inspection.
    html_path = _os.path.join(dump_dir, f"profile-{slug}-{stamp}.html")
    try:
        html = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[Profile] DEBUG: wrote full HTML to {html_path}", flush=True)
    except Exception as exc:
        print(f"[Profile] DEBUG: failed to write HTML: {exc}", flush=True)


def _parse_current_role_company(experience_text: str) -> tuple[str, str]:
    """Best-effort extraction of (current_role, current_company) from the raw
    text of the Experience section. LinkedIn's section layout is:

        Experience
        <role title>
        <company name> [· <employment type>]
        <date range>            (← contains "Present" / "Today" / "Aujourd'hui" ...)
        ...next role...

    The first role-block is almost always the current one (LinkedIn sorts by
    recency). We walk the lines and pick the first triple whose date-range
    line contains a present-tense marker; if no marker matches, fall back to
    the very first role-block."""
    if not experience_text:
        return "", ""
    lines = [ln.strip() for ln in experience_text.splitlines() if ln.strip()]
    if not lines:
        return "", ""
    # Drop the leading "Experience" header line.
    if lines[0].lower().startswith(("experience", "expérience", "experiência", "erfahrung", "esperienza", "experiencia")):
        lines = lines[1:]

    present_markers = (
        "present", "today", "now",                        # EN
        "aujourd'hui", "actuellement", "en cours",        # FR
        "actualidad", "actual", "presente", "hoy",        # ES / PT
        "heute", "aktuell", "derzeit",                    # DE
        "presente", "oggi",                                # IT
    )

    def looks_like_date_range(ln: str) -> bool:
        low = ln.lower()
        return any(m in low for m in present_markers) or " - " in ln or " – " in ln or " — " in ln

    # Scan windows of 3 consecutive non-empty lines: [role, company, dates].
    # Take the first window where the dates line marks a current position.
    fallback: tuple[str, str] = ("", "")
    for i in range(len(lines) - 2):
        role = lines[i]
        company = lines[i + 1].split("·", 1)[0].strip()
        dates = lines[i + 2]
        if not role or not company:
            continue
        # First viable window stored as fallback in case no "Present" found.
        if fallback == ("", ""):
            fallback = (role, company)
        if any(m in dates.lower() for m in present_markers):
            return role, company
    return fallback


def extract_profile_details(page: Page) -> dict:
    """Multi-strategy profile extractor. Each field has fallbacks because
    LinkedIn renames CSS classes across rollouts — the only stable anchors are
    <h1> inside <main>, the page <title>, og:* meta, and the section id anchors
    (div#about, div#experience, etc.).

    Returns: name, headline, about, experience (raw section text),
             current_role, current_company (parsed from experience), and
             primary_lang (heuristic — see _detect_primary_language)."""
    details = {
        "name": "", "headline": "", "about": "", "experience": "",
        "current_role": "", "current_company": "", "primary_lang": "",
    }
    try:
        # Trigger lazy-load of below-the-fold sections BEFORE extracting. The
        # Experience and About sections are intersection-observer-loaded;
        # without this scroll, innerText for those sections returns empty even
        # though the section HTML is in the DOM. This was the root cause of
        # the `[no-experience]` false skips on profiles with rich careers.
        _prime_profile_lazy_load(page)

        # ── NAME: try class chain → any H1 in <main> → page title → og:title ──
        details["name"] = _first_text(page, (
            "h1.text-heading-xlarge",          # legacy class
            "main h1",                         # current — only h1 in main is the name
            "section.pv-top-card h1",          # older variant
            "div.ph5 h1",                      # older variant
            "h1",                              # broadest fallback
        ))
        if not details["name"]:
            details["name"] = _name_from_page_title(page)
        if not details["name"]:
            details["name"] = _meta_content(page, "og:title", "profile:first_name")

        # ── HEADLINE: legacy class → element right after the H1 → og:description ──
        details["headline"] = _first_text(page, (
            "div.text-body-medium.break-words",
            "main h1 + div",                            # sibling of name h1
            "section.pv-top-card div.text-body-medium",
            "div.ph5 div.text-body-medium",
        ))
        if not details["headline"]:
            details["headline"] = _meta_content(page, "og:description")

        # ── ABOUT / EXPERIENCE: walk up from the id anchor to its <section>. ──
        details["about"] = _first_text(page, ("div#about ~ div.display-flex",)) \
            or _section_text(page, "about")
        details["experience"] = _first_text(page, ("div#experience ~ div.display-flex",)) \
            or _section_text(page, "experience")

        # If Experience came back suspiciously short (just the "Experience"
        # header, no items), the section's children haven't mounted yet. Force
        # one more scrollIntoView + re-extract. Threshold: 40 chars — covers
        # the header word in any locale ("Experience", "Expérience",
        # "Experiência", etc.) with margin.
        if details["experience"] and len(details["experience"]) < 40:
            try:
                page.evaluate(_SCROLL_SECTION_INTO_VIEW_JS, "experience")
                page.wait_for_timeout(900)
                retry = _section_text(page, "experience")
                if retry and len(retry) > len(details["experience"]):
                    print(
                        f"[Profile] Experience retry yielded {len(retry)} chars "
                        f"(was {len(details['experience'])}).",
                        flush=True,
                    )
                    details["experience"] = retry
            except Exception:
                pass

        # ── Diagnostics: log what we got + dump the full HTML when Experience
        # is empty. The latter writes to state/debug/profile-<ts>.html so we can
        # inspect the actual DOM the bot saw. Without this, "skipped with
        # [no-experience]" is a black box. ──
        try:
            print(
                f"[Profile] extracted lengths — name={len(details['name'])} "
                f"headline={len(details['headline'])} about={len(details['about'])} "
                f"experience={len(details['experience'])} "
                f"current_role={details.get('current_role','')!r} "
                f"current_company={details.get('current_company','')!r}",
                flush=True,
            )
        except Exception:
            pass

        if not details["experience"]:
            try:
                _dump_profile_debug(page, details)
            except Exception as exc:
                print(f"[Profile] debug dump failed: {exc}", flush=True)

        # ── DERIVED: current role/company + primary content language ──
        role, company = _parse_current_role_company(details["experience"])
        details["current_role"] = role
        details["current_company"] = company

        # Top card text also includes the location line ("Marrakesh, Morocco"),
        # which is crucial for francophone-region detection. Profile headlines
        # in English with a Moroccan/Tunisian/Algerian/etc. location still
        # need French DMs.
        top_card_text = ""
        try:
            card = _top_card(page)
            if card is not None:
                top_card_text = (card.inner_text(timeout=1500) or "")
        except Exception:
            pass

        # Language is binary: 'fr' or 'en'. Excludes Name (multilingual / flag
        # emojis bias the wrong way). Includes top-card location text so a
        # location like "Marrakech, Morocco" triggers French.
        details["primary_lang"] = _detect_primary_language(
            " ".join([details["headline"], details["about"], details["experience"], top_card_text])
        )
    except Exception as e:
        print(f"Error extracting profile details: {e}", flush=True)
    return details


# Cheap French detector. The bot only writes DMs in French or English, so this
# is a binary decision: French if the profile shows clear French signal, else
# English. Detects from BOTH content keywords AND francophone-region location
# tokens — a profile saying "Marrakech, Morocco" in English-looking headline
# still gets French because Morocco is overwhelmingly francophone for tech.

# French content markers — diacritics, function words, common tech titles.
_FR_CONTENT_HINTS = (
    " le ", " la ", " les ", " des ", " une ", " un ", " et ", " est ", " pour ",
    " avec ", " chez ", " dans ", " sur ", " plus ", " mais ", " donc ", " ses ",
    " nos ", " notre ", " votre ", " leurs ", " cette ", " cette ", " ces ",
    "aujourd'hui", "actuellement", "depuis", "à propos",
    "ingénieur", "ingénieure", "développeur", "développeuse",
    "responsable", "ressources humaines", "gestion", "stagiaire",
    "recruteur", "recruteuse", "recrutement",
)

# Francophone-region tokens (cities + countries). Hit ANY of these and we lean
# toward French regardless of content language — many tech profiles in these
# regions write headlines in English but communicate professionally in French.
_FR_REGION_HINTS = (
    # France
    "france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "nantes", "lille", "nice",
    # Belgium (FR-speaking part) / Switzerland (FR-speaking part)
    "bruxelles", "wallonie", "liège", "namur",
    "genève", "geneva", "lausanne", "fribourg",
    # Quebec / French Canada
    "québec", "quebec", "montréal", "montreal", "sherbrooke", "trois-rivières",
    # North Africa (Maghreb)
    "maroc", "morocco", "marrakech", "marrakesh", "casablanca", "rabat", "tanger", "tangier",
    "agadir", "fès", "fes", "meknès", "meknes", "tétouan", "oujda",
    "algérie", "algeria", "alger", "algiers", "oran", "constantine",
    "tunisie", "tunisia", "tunis", "sfax", "sousse",
    # Sub-Saharan francophone
    "côte d'ivoire", "cote d'ivoire", "abidjan", "yamoussoukro",
    "sénégal", "senegal", "dakar",
    "cameroun", "cameroon", "yaoundé", "yaounde", "douala",
    "mali", "bamako", "burkina faso", "ouagadougou",
    "madagascar", "antananarivo",
)


def _detect_primary_language(text: str) -> str:
    """Return 'fr' or 'en' — never anything else. The bot speaks only those
    two languages, so non-French profiles (including ES/IT/PT/DE/AR) all get
    English DMs. French is returned when EITHER (a) the content contains
    enough French function-word/tech-title signal, OR (b) the text mentions
    a francophone city or country. Anyone else → English."""
    if not text or len(text) < 10:
        return "en"
    low = " " + text.lower() + " "
    # Content signal — count distinct French keyword hits.
    content_score = sum(1 for h in _FR_CONTENT_HINTS if h in low)
    if content_score >= 2:
        return "fr"
    # Region signal — single match is enough for a francophone region.
    if any(r in low for r in _FR_REGION_HINTS):
        return "fr"
    return "en"


def search_posts(page: Page, query: str):
    q = urllib.parse.quote(query)
    url = f"https://www.linkedin.com/search/results/content/?keywords={q}"
    page.goto(url)
    random_sleep(4, 8)
    return page.url


def goto_home_feed(page: Page) -> str:
    """Navigate to the LinkedIn home feed (https://www.linkedin.com/feed/) and wait
    for the post scaffold to appear. Returns the resolved URL. Used by POST mode
    so the agent scrapes the user's actual timeline instead of a search query."""
    url = "https://www.linkedin.com/feed/"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"[POST] feed navigation error: {e}", flush=True)
    # Give LinkedIn's lazy loader a moment to inject the first batch of posts.
    try:
        page.wait_for_selector(
            "div[data-id^='urn:li:activity'], div[data-urn^='urn:li:activity'], "
            "div.feed-shared-update-v2, div.fie-impression-container, "
            "[data-finite-scroll-hotkey-item]",
            timeout=12000,
        )
    except Exception:
        print("[POST] feed scaffold did not appear within 12s — continuing anyway", flush=True)
    random_sleep(2, 4)
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
_DISMISS_LABELS = ("Dismiss", "Cancel", "Annuler", "Cerrar", "Abbrechen", "Annulla", "Cancelar", "Close")


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


# Profile-page top-card containers. Tried in order — the first that matches is
# scoped for action-button clicks. Necessary because the right sidebar ("More
# profiles for you") also renders Connect/Message buttons; without scoping
# we'd accidentally invite the wrong person AND report no_effect on the
# main profile (whose Connect button is still untouched).
_TOP_CARD_SELECTORS = (
    "section.pv-top-card",
    "section.scaffold-layout__top-card",
    "main > section:first-of-type",
    "main section:first-of-type",
)


def _top_card(page: Page):
    """Return a locator for the profile top card, or None if no candidate matches."""
    for sel in _TOP_CARD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and _visible(loc):
                return loc
        except Exception:
            continue
    return None


# Selectors for the Connect element, in order of stability. LinkedIn switched
# the Connect control from a <button> to an <a> linking to a server-side
# custom-invite endpoint — get_by_role("button", name="Connect") never matches
# the new DOM, which was the silent root cause of all the "no_connect_button"
# and "connect_click_no_effect" failures.
#
#   1. /preload/custom-invite/?vanityName=... — language-independent URL pattern
#      used by every locale; survives label/class renames.
#   2. aria-label combining "Invite" + "connect" (or locale equivalent). EN/FR/
#      ES/IT/PT/DE variants all share the same dual-keyword pattern, just with
#      different roots — so a single multilingual aria-label regex covers them.
#   3. <button> with role=button + Connect text — kept for the legacy DOM that
#      a few accounts may still see.
_CONNECT_HREF_SELECTOR = (
    "a[href*='/preload/custom-invite/'], "
    "a[href*='/connect-flow/'], "
    "a[href*='miniProfileUrn'][href*='invite']"
)
# Multi-locale "Invite to connect" matcher. Uses two lookaheads so the order
# of words doesn't matter — German puts the verb at the end ("X zur Vernetzung
# einladen") while EN/FR/ES/IT/PT put it at the start.
_CONNECT_ARIA_RE = re.compile(
    r"(?=.*(?:invite|inviter|invitez|invitar|invita|convid|einladen))"
    r"(?=.*(?:connect|connecter|conectar|collegar|vernetz))",
    re.IGNORECASE | re.DOTALL,
)


def _find_connect_action(scope):
    """Return a clickable locator for the Connect control, or None. Tries the
    most stable signals first (href pattern → aria-label regex → legacy button)
    so we work across LinkedIn's current and historical DOMs in any locale.

    `scope` should ideally be the profile top-card locator so we don't pick up
    Connect controls in the 'More profiles for you' sidebar."""
    # 1. Anchor with a custom-invite href — current LinkedIn, all locales.
    try:
        loc = scope.locator(_CONNECT_HREF_SELECTOR).first
        if loc.count() and _visible(loc):
            return loc
    except Exception:
        pass

    # 2. Any element whose aria-label matches an invite-to-connect phrase
    #    in any supported locale.
    try:
        cands = scope.locator("[aria-label]").all()
        for el in cands:
            try:
                label = el.get_attribute("aria-label") or ""
                if not label or not _CONNECT_ARIA_RE.search(label):
                    continue
                if not _visible(el):
                    continue
                return el
            except Exception:
                continue
    except Exception:
        pass

    # 3. Legacy: button with role=button + Connect text.
    for name in _CONNECT_LABELS:
        try:
            btn = scope.get_by_role("button", name=name).first
            if _visible(btn):
                return btn
        except Exception:
            continue

    # 4. Last-resort fallback: any <a> or <button> whose visible text is exactly Connect.
    for name in _CONNECT_LABELS:
        try:
            link = scope.get_by_role("link", name=name).first
            if _visible(link):
                return link
        except Exception:
            continue
    return None


_MESSAGE_HREF_SELECTOR = (
    "a[href*='/messaging/compose/'], "
    "a[href*='/messaging/thread/']"
)


def _find_message_action(scope):
    """Return a clickable locator for the Message control, or None. Mirrors
    `_find_connect_action`: LinkedIn switched Message to an <a> link to
    `/messaging/compose/?profileUrn=...&recipient=...`, so role=button doesn't
    match it any more. Tries href pattern → role=button (legacy) → role=link.

    Scope should ideally be the profile top card so we don't pick the sidebar's
    Message button on a recommended-profile card."""
    try:
        loc = scope.locator(_MESSAGE_HREF_SELECTOR).first
        if loc.count() and _visible(loc):
            return loc
    except Exception:
        pass
    for name in _MESSAGE_LABELS:
        try:
            btn = scope.get_by_role("button", name=name).first
            if _visible(btn):
                return btn
        except Exception:
            continue
    for name in _MESSAGE_LABELS:
        try:
            link = scope.get_by_role("link", name=name).first
            if _visible(link):
                return link
        except Exception:
            continue
    return None


def _click_locator_robust(loc) -> bool:
    """Scroll into view, then click — retrying with force=True if intercepted."""
    if loc is None:
        return False
    try:
        try:
            loc.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        try:
            loc.click(timeout=3000)
            return True
        except Exception:
            try:
                loc.click(timeout=2000, force=True)
                return True
            except Exception:
                return False
    except Exception:
        return False


def _click_top_card_button(page: Page, labels) -> bool:
    """Click the first matching button inside the profile top card. Falls back
    to a page-wide search only if the top card can't be located. Scrolls the
    button into view before clicking and retries with force=True if the normal
    click is intercepted (e.g. by the messaging widget overlay).

    This is the function to use for any profile-page action (Connect, Message,
    More) because LinkedIn renders sibling buttons with the same labels in the
    'More profiles for you' sidebar — a page-wide get_by_role would race and
    pick whichever appears first in DOM order, which is not always the main
    profile."""
    card = _top_card(page)
    target = card if card is not None else page
    for name in labels:
        try:
            btn = target.get_by_role("button", name=name).first
            if not _visible(btn):
                continue
            try:
                btn.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            try:
                btn.click(timeout=3000)
                return True
            except Exception:
                try:
                    btn.click(timeout=2000, force=True)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _post_connect_state(page: Page) -> str:
    """After clicking Connect, classify what LinkedIn did. Returns one of:
       'modal_open'   — invite-note dialog is showing, need to click Send.
       'email_modal'  — modal is asking for the recipient's email; can't proceed.
       'pending'      — no modal, profile now shows Pending → invite went through.
       'connect_gone' — Connect button vanished, no modal, no Pending; ambiguous
                        but usually means the invite went through.
       'unchanged'    — Connect still visible, no modal → click didn't take.

    Pending/Connect checks are scoped to the profile top card so we don't read
    the sidebar's 'More profiles for you' state by mistake."""
    # Modal? Try multiple selectors — LinkedIn ships a few variants.
    for sel in ("[role='dialog'].artdeco-modal", "[role='dialog']", "div.artdeco-modal"):
        try:
            modal = page.locator(sel).first
            if not _visible(modal):
                continue
            try:
                if modal.get_by_role("textbox", name=re.compile(r"e-?mail", re.I)).count() > 0:
                    return "email_modal"
                if modal.locator("input[type='email']").count() > 0:
                    return "email_modal"
            except Exception:
                pass
            return "modal_open"
        except Exception:
            continue

    card = _top_card(page)
    target = card if card is not None else page

    for name in _PENDING_LABELS:
        try:
            if _visible(target.get_by_role("button", name=name).first):
                return "pending"
        except Exception:
            continue

    for name in _CONNECT_LABELS:
        try:
            if _visible(target.get_by_role("button", name=name).first):
                return "unchanged"
        except Exception:
            continue
    return "connect_gone"


def _send_in_modal(page: Page) -> bool:
    """Click Send / Send-without-note inside the open invite modal. Scoped to
    the modal so we don't accidentally click a Send button elsewhere on the page
    (e.g. the Message composer)."""
    for sel in ("[role='dialog'].artdeco-modal", "[role='dialog']", "div.artdeco-modal"):
        try:
            modal = page.locator(sel).first
            if not _visible(modal):
                continue
            for name in _SEND_NO_NOTE_LABELS:
                try:
                    btn = modal.get_by_role("button", name=name).first
                    if _visible(btn):
                        btn.click()
                        return True
                except Exception:
                    continue
            for name in _SEND_LABELS:
                try:
                    btn = modal.get_by_role("button", name=name).first
                    if _visible(btn):
                        btn.click()
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    # Last resort: any visible Send/Send-without-note on the page.
    if _click_first_visible_button(page, _SEND_NO_NOTE_LABELS):
        return True
    if _click_first_visible_button(page, _SEND_LABELS):
        return True
    return False


def send_empty_connection(page: Page, profile_url: str) -> tuple[bool, str]:
    """Visit a profile and send a Connect request without a note.

    Handles LinkedIn's four UX paths for the Connect button:
      1. Modal opens with "Send without a note" — legacy flow.
      2. Modal opens with just "Send" — recent (the "without a note" label
         was removed for some accounts).
      3. No modal — invite is sent directly and the profile flips to Pending.
         This was the silent-success failure mode: we were calling it
         no_send_button when LinkedIn had actually accepted the invite.
      4. Email-required modal — LinkedIn asks for the recipient's email
         before sending. Dismissed cleanly with `email_required` reason.
    Returns (success, reason)."""
    if not go_to_profile(page, profile_url):
        return False, "navigation_failed"
    try:
        card = _top_card(page)
        target = card if card is not None else page

        # Pre-check: top card may already show Pending — invite was sent in a
        # prior run that crashed before recording to pending_db, or the user
        # invited them manually. Treat as success so the lead stays in queue.
        for name in _PENDING_LABELS:
            try:
                if _visible(target.get_by_role("button", name=name).first):
                    print(f"[Connect] {profile_url} already Pending — treating as success.", flush=True)
                    return True, ""
            except Exception:
                continue

        # ── Try Connect, with one retry to absorb hydration races ──
        # Two-pass approach: if the first click doesn't change state, give the
        # page a beat and retry once. Most "click had no effect" failures are
        # timing — Playwright sees the element as actionable before its React
        # handler is bound, so the click fires into the void.
        def click_connect_then_state() -> str:
            # _find_connect_action handles all of: current <a href='/preload/
            # custom-invite/...'> link, legacy <button>Connect</button>, and
            # multi-locale aria-label variants.
            connect_loc = _find_connect_action(target)
            if connect_loc is not None and _click_locator_robust(connect_loc):
                random_sleep(2, 4)
                return _post_connect_state(page)
            # Fall back to "More actions" dropdown.
            if not _click_top_card_button(page, _MORE_LABELS):
                return "no_connect_button"
            random_sleep(1, 2)
            # The dropdown lives outside the top card — search the whole page.
            dropdown = page.locator("div.artdeco-dropdown__content").first
            if _visible(dropdown):
                dropdown_connect = _find_connect_action(dropdown)
                if dropdown_connect is not None and _click_locator_robust(dropdown_connect):
                    random_sleep(2, 4)
                    return _post_connect_state(page)
            for name in _CONNECT_LABELS:
                try:
                    item = page.locator("div.artdeco-dropdown__content").get_by_text(name).first
                    if _visible(item):
                        item.click()
                        random_sleep(2, 4)
                        return _post_connect_state(page)
                except Exception:
                    continue
            return "connect_not_in_dropdown"

        state = click_connect_then_state()
        if state == "unchanged":
            print(f"[Connect] First click had no effect — retrying after settle.", flush=True)
            random_sleep(2, 3)
            state = click_connect_then_state()

        if state == "modal_open":
            if _send_in_modal(page):
                random_sleep(2, 3)
                return True, ""
            return False, "modal_open_no_send_button"

        if state == "email_modal":
            _click_first_visible_button(page, _DISMISS_LABELS)
            return False, "email_required"

        if state in ("pending", "connect_gone"):
            # LinkedIn auto-sent the invite without showing a modal (newer UX).
            return True, ""

        if state in ("no_connect_button", "connect_not_in_dropdown"):
            return False, state

        # state == "unchanged" after retry — give up cleanly.
        return False, "connect_click_no_effect"
    except Exception as e:
        print(f"[Connect] error: {e}", flush=True)
        return False, f"exception:{type(e).__name__}"


_FIRST_DEGREE_TOKENS = (
    "1st", "1°", "1er", "1ère", "1ª",  # EN / IT / FR / ES feminine
    "1.", "primero", "primeiro",       # DE-ish numeric, PT
    "1度", "1차",                       # JP / KR
)


def profile_is_pending(page: Page) -> bool:
    """True if the currently-loaded profile page shows a Pending invite badge
    in the top card. Scoped to the top card so the sidebar's Pending markers
    on recommended profiles don't false-positive. Assumes the profile page is
    already loaded — does NOT navigate."""
    try:
        card = _top_card(page)
        target = card if card is not None else page
        for name in _PENDING_LABELS:
            try:
                if _visible(target.get_by_role("button", name=name).first):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def is_first_degree_connection(page: Page, profile_url: str) -> bool:
    """True if LinkedIn shows the profile as a 1st-degree connection.

    Primary signal (most reliable across LinkedIn's redesigns + locales):
        absence of a Connect action in the top card. LinkedIn never renders
        Connect for someone you're already connected to — instead the primary
        action is Message. So `_find_connect_action(card) is None` is a strong
        positive signal for 1st-degree. We confirm with one of:
          - top-card text containing a degree token (1st / 1er / 1° / ...)
          - aria-label on a degree pill mentioning 1st-degree
          - a Pending button (means we've already invited — not 1st but also
            not someone we should re-invite, so caller treats False is fine here)
    """
    if not go_to_profile(page, profile_url):
        return False
    try:
        card = _top_card(page)
        if card is None:
            return False

        # Pending? Not 1st-degree, and caller should NOT re-invite.
        for name in _PENDING_LABELS:
            try:
                if _visible(card.get_by_role("button", name=name).first):
                    return False
            except Exception:
                continue

        # Primary signal: no Connect action visible in the top card.
        connect_loc = _find_connect_action(card)
        connect_absent = connect_loc is None

        if connect_absent:
            return True  # Connect is gone → already connected.

        # Connect IS present — check degree tokens / aria-labels as a sanity
        # confirmation. (Rare edge: some LinkedIn UI variants show Connect
        # alongside a 1st-degree badge during a brief A/B test window.)
        try:
            text = (card.inner_text(timeout=1500) or "").lower()
        except Exception:
            text = ""
        for tok in _FIRST_DEGREE_TOKENS:
            if (f" {tok} " in f" {text} " or text.startswith(tok + " ")
                    or f"\n{tok}\n" in text or f"• {tok}" in text):
                return True
        try:
            badges = card.locator("[aria-label*='1st' i], [aria-label*='1er' i], [aria-label*='1°' i]")
            if badges.count():
                return True
        except Exception:
            pass
        return False
    except Exception as exc:
        print(f"[1st-degree] check failed for {profile_url}: {exc}", flush=True)
        return False


def check_connection_status(page: Page, profile_url: str) -> str:
    """Return 'accepted' if a Message action is available, 'pending' if a
    Pending button is shown, else 'unknown'. Used by the sweeper to detect
    when a pending invite has been accepted. Scoped to the top card so the
    sidebar's Message buttons (on suggested profiles) don't falsely register
    as acceptance."""
    if not go_to_profile(page, profile_url):
        return "unknown"
    try:
        card = _top_card(page)
        target = card if card is not None else page
        if _find_message_action(target) is not None:
            return "accepted"
        for name in _PENDING_LABELS:
            try:
                if _visible(target.get_by_role("button", name=name).first):
                    return "pending"
            except Exception:
                continue
        return "unknown"
    except Exception:
        return "unknown"


# Selectors for "this conversation already has messages". LinkedIn ships the
# messaging composer as an overlay panel; if any prior message exists, it
# appears inside .msg-overlay-conversation-bubble (or the older .msg-form
# parent). We sample several known list-item selectors — the first non-zero
# count means there's a prior thread, in which case we DO NOT send a new DM
# (would stack on top of the existing conversation).
_EXISTING_MESSAGE_SELECTORS = (
    ".msg-s-message-list li",
    ".msg-s-message-list .msg-s-event-listitem",
    ".msg-s-message-list__event",
    "[data-event-urn^='urn:li:message:']",
    "[data-event-urn^='urn:li:fsd_message:']",
    ".msg-overlay-conversation-bubble .msg-s-event-listitem",
    ".msg-thread .msg-s-event-listitem",
)


def _has_existing_messages(page: Page) -> bool:
    """True if the open conversation panel already contains messages.

    The check is generous on purpose: any of the known message-list-item
    selectors yielding a non-zero count is treated as 'already messaged'.
    We'd rather skip a legitimate (but rare) re-DM than spam someone we've
    already written to."""
    for sel in _EXISTING_MESSAGE_SELECTORS:
        try:
            n = page.locator(sel).count()
            if n > 0:
                return True
        except Exception:
            continue
    return False


def send_dm_to_profile(page: Page, profile_url: str, message: str) -> tuple[bool, str]:
    """Open the Message composer on a profile and send a message.

    Returns (success, reason). Reasons that are not failures:
      'already_messaged' — a prior conversation thread exists in the panel,
                           we deliberately do NOT send anything new on top.
    """
    if not message or not message.strip():
        return False, "empty_message"
    if not go_to_profile(page, profile_url):
        return False, "navigation_failed"
    try:
        card = _top_card(page)
        target = card if card is not None else page

        msg_loc = _find_message_action(target)
        if msg_loc is None or not _click_locator_robust(msg_loc):
            return False, "no_message_button"

        random_sleep(2, 3)

        # Guard against double-DMing: if a thread already exists in the panel,
        # bail out cleanly. Caller (the sweeper, network_node) treats this as
        # a non-failure so we don't keep retrying.
        if _has_existing_messages(page):
            print(f"[DM] {profile_url} already has a conversation — skipping.", flush=True)
            return False, "already_messaged"

        editor = page.locator("div.msg-form__contenteditable[contenteditable='true']").first
        if not _visible(editor):
            return False, "no_editor"
        editor.click()
        random_sleep(0, 1)
        page.keyboard.type(message, delay=10)
        random_sleep(1, 2)
        # Send button scoped to the messaging form.
        for name in _SEND_LABELS:
            try:
                btn = page.locator(".msg-form").get_by_role("button", name=name).first
                if _visible(btn):
                    btn.click()
                    random_sleep(2, 3)
                    return True, ""
            except Exception:
                continue
        # Fallback: any visible Send button on page.
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
