import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

SEE_MORE_LABELS = (
    "see more", "...more", "…more",
    "voir plus", "...plus", "…plus",
    "ver más", "ver mas", "más", "ver mais",
    "mehr ansehen", "mehr",
    "vedi altro", "altro",
    "更多", "もっと見る",
)

# Multi-selector fallbacks — LinkedIn renames classes across A/B tests and rollouts,
# so we always try several before giving up. Most stable: data-id / data-urn anchored
# on `urn:li:activity`. Class-based selectors are kept as belt-and-braces fallbacks.
POST_CONTAINER_SELECTORS = (
    "div[data-id^='urn:li:activity']",
    "div[data-urn^='urn:li:activity']",
    "[data-finite-scroll-hotkey-item]",
    "div.feed-shared-update-v2",
    "div.fie-impression-container",
    "article.update-components-update-v2",
    "div.update-components-update-v2",
    "[role='article']",
    "div.scaffold-finite-scroll__content > div",
)

AUTHOR_NAME_SELECTORS = (
    ".update-components-actor__name span[aria-hidden='true']",
    ".update-components-actor__title span[aria-hidden='true']",
    ".update-components-actor__name",
    ".update-components-actor__title",
    ".feed-shared-actor__name",
    "span.feed-shared-actor__name",
)

AUTHOR_LINK_SELECTORS = (
    "a.update-components-actor__meta-link",
    "a.update-components-actor__container-link",
    "a.app-aware-link.update-components-actor__meta-link",
    ".update-components-actor a[href*='/in/']",
    ".update-components-actor a[href*='/company/']",
    ".feed-shared-actor a[href*='/in/']",
    ".feed-shared-actor a[href*='/company/']",
)

CONTENT_SELECTORS = (
    ".update-components-text",
    ".update-components-update-v2__commentary",
    ".feed-shared-update-v2__description",
    ".feed-shared-update-v2__description-wrapper",
    ".feed-shared-text",
    ".feed-shared-inline-show-more-text",
)

SEE_MORE_SELECTORS = (
    "button.feed-shared-inline-show-more-text__see-more-less-toggle",
    "button.inline-show-more-text__button",
    "button.feed-shared-inline-show-more-text__button",
    "button[aria-label*='see more' i]",
    "button[aria-expanded='false'][class*='show-more']",
)


def _visible(loc, timeout: int = 300) -> bool:
    try:
        return loc.is_visible(timeout=timeout)
    except Exception:
        return False


def _safe_text(loc, timeout: int = 500) -> str:
    try:
        if not _visible(loc, timeout=timeout):
            return ""
        return (loc.inner_text(timeout=timeout) or "").strip()
    except Exception:
        return ""


def _safe_attr(loc, attr: str) -> str:
    try:
        return loc.get_attribute(attr) or ""
    except Exception:
        return ""


def expand_see_more(post) -> None:
    """Click any 'see more' inside the given post Locator to reveal full content.
    Tries class-based selectors first, then role-name/locale fallbacks, then aria-label."""
    for sel in SEE_MORE_SELECTORS:
        try:
            btn = post.locator(sel).first
            if _visible(btn):
                try:
                    btn.scroll_into_view_if_needed(timeout=500)
                except Exception:
                    pass
                try:
                    btn.click(timeout=1500)
                    return
                except Exception:
                    try:
                        btn.click(timeout=1500, force=True)
                        return
                    except Exception:
                        continue
        except Exception:
            continue
    for label in SEE_MORE_LABELS:
        try:
            btn = post.get_by_role("button", name=re.compile(label, re.I)).first
            if _visible(btn):
                try:
                    btn.click(timeout=1500)
                    return
                except Exception:
                    try:
                        btn.click(timeout=1500, force=True)
                        return
                    except Exception:
                        continue
        except Exception:
            continue


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in EMAIL_RE.findall(text):
        low = m.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(m)
    return out


def _normalize_li_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("/"):
        href = "https://www.linkedin.com" + href
    return href.split("?")[0]


def extract_author_url(post) -> str:
    """Return the canonical profile/company URL of the post author, or empty string."""
    for sel in AUTHOR_LINK_SELECTORS:
        try:
            link = post.locator(sel).first
            if _visible(link):
                href = _safe_attr(link, "href")
                if href:
                    return _normalize_li_url(href)
        except Exception:
            continue
    return ""


def _first_text(post, selectors: tuple[str, ...]) -> str:
    for sel in selectors:
        try:
            el = post.locator(sel).first
            text = _safe_text(el)
            if text:
                return text
        except Exception:
            continue
    return ""


def _extract_attached_job_url(post) -> str:
    """LinkedIn often attaches a /jobs/view/ card under hiring posts."""
    try:
        link = post.locator("a[href*='/jobs/view/']").first
        if _visible(link):
            href = _safe_attr(link, "href")
            if href:
                return _normalize_li_url(href)
    except Exception:
        pass
    return ""


def _extract_post_permalink(post) -> str:
    try:
        link = post.locator("a[href*='/feed/update/']").first
        if _visible(link):
            href = _safe_attr(link, "href")
            if href:
                return _normalize_li_url(href)
    except Exception:
        pass
    return ""


# Phrases that strongly signal a hiring post. Used as a lightweight filter so the
# LLM only sees posts that look relevant, instead of every news/share in the feed.
HIRING_HINTS = (
    "hiring", "we're hiring", "we are hiring", "join our team", "join us",
    "open role", "open position", "looking for", "we're looking",
    "apply at", "apply here", "send your cv", "send your resume", "dm me",
    "recrute", "nous recrutons", "embauche", "poste à pourvoir", "rejoignez",
    "contratando", "buscamos", "se busca",
    "stellenangebot", "wir stellen ein", "bewerbung",
    "assumiamo", "cerchiamo",
)


def looks_like_hiring(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    if any(h in low for h in HIRING_HINTS):
        return True
    if EMAIL_RE.search(low):
        return True
    return False


# JS-side scraper that survives LinkedIn's obfuscated CSS-in-JS class names AND
# the disappearance of data-urn / role="article" attributes. Anchor: the
# accessibility delimiter "Feed post" (and locale equivalents) that LinkedIn
# emits between every post in the feed. We walk the DOM in document order, and
# every time we see that exact text we close the previous post chunk and start
# a new one — accumulating text, hrefs, and image-alts in between.
FEED_JS_SCRAPER = r"""
() => {
  const main = document.querySelector('main') || document.body;
  if (!main) return [];
  // Accessibility delimiters seen between posts. Compared after trim+lowercase.
  const DELIMS = new Set([
    'feed post',
    'publication',
    'publicación', 'publicacion',
    'beitrag',
    'messaggio',
    'publicação', 'publicacao',
    '피드 게시물',
    'フィードの投稿', 'フィード投稿',
  ]);
  const posts = [];
  let current = null;
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_ALL, null);
  let node;
  while ((node = walker.nextNode())) {
    if (node.nodeType === Node.TEXT_NODE) {
      const raw = node.nodeValue || '';
      const t = raw.trim();
      if (!t) continue;
      if (DELIMS.has(t.toLowerCase())) {
        if (current && current.lines.length >= 2) posts.push(current);
        current = { lines: [], links: [], img_alts: [] };
        continue;
      }
      if (current) current.lines.push(t);
    } else if (node.nodeType === Node.ELEMENT_NODE && current) {
      if (node.tagName === 'A' && node.href) {
        current.links.push(node.href);
      } else if (node.tagName === 'IMG') {
        const alt = node.getAttribute('alt') || '';
        if (alt) current.img_alts.push(alt);
      }
    }
  }
  if (current && current.lines.length >= 2) posts.push(current);
  return posts.map(p => ({
    text: p.lines.join('\n').slice(0, 8000),
    links: Array.from(new Set(p.links)).slice(0, 40),
    img_alts: p.img_alts.slice(0, 10),
  })).slice(0, 80);
}
"""


# i18n marker strings inside a post's footer chrome — we strip these from the
# extracted body so the LLM doesn't see "Like Comment Repost Send" as content.
FOOTER_CHROME = {
    "like", "comment", "repost", "send", "follow", "+ follow", "share",
    "j'aime", "commenter", "republier", "envoyer", "suivre", "partager",
    "me gusta", "comentar", "compartir", "enviar", "seguir",
    "gefällt mir", "kommentieren", "teilen", "senden", "folgen",
    "mi piace", "commenta", "condividi", "invia", "segui",
    "curtir", "comentar", "compartilhar", "enviar", "seguir",
}


def _classify_links(links: list[str]) -> dict:
    """Sort a flat list of hrefs into the structured slots the rest of the
    pipeline expects."""
    author_url = ""
    attached_job_url = ""
    post_url = ""
    seen = set()
    for href in links:
        clean = (href or "").split("#", 1)[0]
        if not clean or clean in seen:
            continue
        seen.add(clean)
        low = clean.lower()
        if "/feed/update/" in low and not post_url:
            post_url = clean.split("?")[0]
        elif "/jobs/view/" in low and not attached_job_url:
            attached_job_url = clean.split("?")[0]
        elif ("/in/" in low or "/company/" in low) and not author_url:
            author_url = clean.split("?")[0]
    return {
        "author_url": author_url,
        "attached_job_url": attached_job_url,
        "post_url": post_url,
    }


def _split_author_and_body(text: str) -> tuple[str, str]:
    """Heuristically split the raw inner_text of a post into (author, body).
    The author block is the leading lines up to the timestamp marker
    ('2d', '20h', '3 mo', '•', '...'). Everything after that is body."""
    if not text:
        return "", ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Strip footer chrome lines wherever they appear.
    lines = [ln for ln in lines if ln.lower() not in FOOTER_CHROME]
    if not lines:
        return "", ""
    # Timestamp markers used as the cut point between header and body.
    import re as _re
    ts = _re.compile(r"^(?:\d+\s*(?:s|m|h|d|w|mo|y|min|hr|sec|day|week|month|year)s?\b|•|edited\b|\.\.\.|…)", _re.I)
    cut = None
    for i, ln in enumerate(lines):
        if ts.match(ln):
            cut = i
            break
    if cut is None:
        # No timestamp found — treat first line as author, rest as body.
        return lines[0], "\n".join(lines[1:])
    author = lines[0]
    # Body starts after the timestamp line (and any "Edited" / "Follow" right after it).
    body_start = cut + 1
    while body_start < len(lines) and lines[body_start].lower() in {
        "edited", "edited •", "follow", "+ follow", "•",
    }:
        body_start += 1
    body = "\n".join(lines[body_start:])
    return author, body


# "Authors" that are actually sidebar widgets — LinkedIn delimits them with the
# same "Feed post" SR text so our JS scraper picks them up. Skip them.
NON_POST_AUTHORS = {
    "suggested", "recommended for you", "promoted",
    "people you may know", "you might be interested",
    "premium", "people followed by",
    "jobs recommended for you", "jobs for you", "top picks for you",
    "events for you", "newsletters for you", "groups for you",
    "suggéré", "suggere", "suggestion", "suggestions",
    "recommandé pour vous", "personnes que vous pourriez connaître",
    "offres d'emploi recommandées pour vous", "offres pour vous",
    "sugerido", "personas que quizás conozcas",
    "vorgeschlagen", "personen, die sie kennen könnten",
    "suggerito", "persone che potresti conoscere",
}


def _is_non_post(author: str, content: str) -> bool:
    """LinkedIn renders Suggested / Recommended for you / Premium ad widgets with
    the same delimiter as real posts. Filter them at the Python boundary so the
    LLM doesn't waste cycles scoring them and the agent doesn't try to DM them."""
    a = (author or "").strip().lower()
    if not a:
        return True
    if a in NON_POST_AUTHORS:
        return True
    # Heuristic: very short author lines that don't contain a real name pattern.
    if a.startswith("recommended ") or a.startswith("suggested ") or a.startswith("promoted "):
        return True
    if a.startswith("jobs ") or a.startswith("offres "):
        # "Jobs recommended for you", "Jobs for you", "Offres d'emploi pour vous" widgets.
        return True
    # Body sniff: pure promo / ad cards never contain a real timestamp.
    low = (content or "").lower()
    if "promoted" in low[:120] and "follow" in low[:200] and len(low) < 400:
        return True
    return False


def scrape_feed_via_js(page) -> list[dict]:
    """Use the JS-side scraper to extract every post visible on the page. Returns
    a list of dicts with author/content/links pre-classified for the agent."""
    try:
        raw = page.evaluate(FEED_JS_SCRAPER) or []
    except Exception as exc:
        print(f"[POST] JS scrape failed: {exc}", flush=True)
        return []
    out = []
    dropped = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or ""
        author, body = _split_author_and_body(text)
        if _is_non_post(author, body or text):
            dropped += 1
            continue
        emails = extract_emails(body) or extract_emails(text)
        links_cls = _classify_links(item.get("links") or [])
        out.append({
            "author": author,
            "content": body or text,
            "emails": emails,
            "primary_email": emails[0] if emails else "",
            **links_cls,
            "urn": "",  # obfuscated DOM no longer exposes urn
        })
    if dropped:
        print(f"[POST] filtered {dropped} non-post cards (suggested/recommended/promoted)", flush=True)
    return out


def scrape_post(post) -> dict:
    """Extract a full post dict from a Playwright post Locator. Best-effort: any
    field may be empty if the selectors don't match this DOM variant.

    Returns:
        {
            "author": str,
            "author_url": str,
            "content": str,
            "emails": list[str],
            "primary_email": str,
            "attached_job_url": str,
            "post_url": str,
            "urn": str,
        }
    """
    try:
        post.scroll_into_view_if_needed(timeout=1000)
    except Exception:
        pass

    expand_see_more(post)

    author = _first_text(post, AUTHOR_NAME_SELECTORS)
    content = _first_text(post, CONTENT_SELECTORS)

    # Last-ditch fallback: if no specific content container matched, fall back to
    # the post's full inner_text/text_content. Strips header/footer chrome crudely.
    if not content:
        full = ""
        for getter in ("inner_text", "text_content"):
            try:
                fn = getattr(post, getter, None)
                if fn is None:
                    continue
                raw = (fn(timeout=1000) or "").strip()
                if raw:
                    full = raw
                    break
            except Exception:
                continue
        if full:
            chrome = {
                "like", "comment", "repost", "send", "follow", "+ follow",
                "j'aime", "commenter", "republier", "envoyer", "suivre",
                "me gusta", "comentar", "compartir", "enviar", "seguir",
                "gefällt mir", "kommentieren", "teilen", "senden", "folgen",
            }
            lines = [
                ln.strip() for ln in full.splitlines()
                if ln.strip() and ln.strip().lower() not in chrome
            ]
            content = "\n".join(lines)

    emails = extract_emails(content)
    author_url = extract_author_url(post)
    attached_job_url = _extract_attached_job_url(post)
    post_url = _extract_post_permalink(post)
    urn = _safe_attr(post, "data-urn") or _safe_attr(post, "data-id")

    return {
        "author": author,
        "author_url": author_url,
        "content": content,
        "emails": emails,
        "primary_email": emails[0] if emails else "",
        "attached_job_url": attached_job_url,
        "post_url": post_url,
        "urn": urn,
    }
