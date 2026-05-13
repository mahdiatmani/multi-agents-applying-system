import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

SEE_MORE_LABELS = (
    "see more", "...more", "…more",
    "voir plus", "...plus",
    "ver más", "ver mas",
    "mehr ansehen",
    "vedi altro",
    "ver mais",
)


def _visible(loc, timeout: int = 300) -> bool:
    try:
        return loc.is_visible(timeout=timeout)
    except Exception:
        return False


def expand_see_more(post) -> None:
    """Click any 'see more' inside the given post Locator to reveal full content."""
    selectors = [
        "button.feed-shared-inline-show-more-text__see-more-less-toggle",
        "button.inline-show-more-text__button",
        "button.feed-shared-inline-show-more-text__button",
    ]
    for sel in selectors:
        try:
            btn = post.locator(sel).first
            if _visible(btn):
                btn.click()
                return
        except Exception:
            continue
    for label in SEE_MORE_LABELS:
        try:
            btn = post.get_by_role("button", name=label).first
            if _visible(btn):
                btn.click()
                return
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


def extract_author_url(post) -> str:
    """Return the canonical profile URL of the post author, or empty string."""
    candidates = [
        "a.update-components-actor__meta-link",
        "a.update-components-actor__container-link",
        "a.app-aware-link.update-components-actor__meta-link",
        ".update-components-actor a[href*='/in/']",
    ]
    for sel in candidates:
        try:
            link = post.locator(sel).first
            if _visible(link):
                href = link.get_attribute("href") or ""
                if href:
                    if href.startswith("/"):
                        href = "https://www.linkedin.com" + href
                    return href.split("?")[0]
        except Exception:
            continue
    return ""
