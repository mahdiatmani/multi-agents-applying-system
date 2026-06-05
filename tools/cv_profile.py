import os
import re
from datetime import datetime
from typing import Optional

CV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "CV.txt"))

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_cache: dict = {}
_cache_mtime: float | None = None


def _read_cv() -> str:
    if not os.path.exists(CV_PATH):
        return ""
    try:
        with open(CV_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _grab(pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def _parse_month_year(s: str) -> Optional[tuple[int, int]]:
    if not s:
        return None
    s = s.strip().lower()
    if s in ("present", "current", "now", "today"):
        now = datetime.now()
        return now.month, now.year
    m = re.match(r"([a-z]+)[\s/.\-]+(\d{4})", s)
    if not m:
        m = re.match(r"(\d{4})[\s/.\-]+([a-z]+)", s)
        if not m:
            return None
        month_name, year = m.group(2), int(m.group(1))
    else:
        month_name, year = m.group(1), int(m.group(2))
    month = _MONTHS.get(month_name[:3]) or _MONTHS.get(month_name)
    if not month:
        return None
    return month, year


def _experience_section(text: str) -> str:
    """Slice out the PROFESSIONAL EXPERIENCE block so date math doesn't count education."""
    m = re.search(
        r"(?:PROFESSIONAL\s+EXPERIENCE|WORK\s+EXPERIENCE|EXPERIENCE)\s*\n(.*?)(?=\n\s*(?:EDUCATION|PROJECTS|SKILLS|LANGUAGES|CERTIFICATIONS|AWARDS|VOLUNTEER|REFERENCES)\b|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


def _estimate_years_exp(text: str) -> float:
    section = _experience_section(text) or text
    pattern = re.compile(
        r"([A-Za-z]+[\s/.\-]+\d{4})\s*[-–—~]\s*([A-Za-z]+[\s/.\-]+\d{4}|Present|Current|Now|Today)",
        re.IGNORECASE,
    )
    intervals: list[tuple[int, int]] = []
    for m in pattern.finditer(section):
        start = _parse_month_year(m.group(1))
        end = _parse_month_year(m.group(2))
        if not start or not end:
            continue
        s_m = start[1] * 12 + start[0]
        e_m = end[1] * 12 + end[0]
        if e_m >= s_m:
            intervals.append((s_m, e_m))
    if not intervals:
        return 0.0
    intervals.sort()
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    total_months = sum(e - s for s, e in merged)
    return round(total_months / 12, 1)


def _parse(text: str) -> dict:
    if not text:
        return {}

    profile: dict = {}

    email = _grab(r"Email[:\s]+([^\s\n]+)", text)
    if not email:
        email = _grab(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text)
    if email:
        profile["email"] = email

    phone = _grab(r"Phone[:\s]+([+\d][\d\s().\-]{6,})", text)
    if not phone:
        phone = _grab(r"(\+?\d[\d\s().\-]{7,}\d)", text)
    if phone:
        profile["phone"] = re.sub(r"[\s().\-]", "", phone)

    location = _grab(r"Location[:\s]+([^\n]+)", text)
    if location:
        profile["location"] = location
        profile["city"] = location.split(",")[0].strip()

    full_name = _grab(r"^([A-Z][A-Z\s'\-]+[A-Z])\s*$", text, flags=re.MULTILINE)
    if full_name:
        parts = [p for p in full_name.title().split() if p]
        if parts:
            profile["full_name"] = " ".join(parts)
            profile["first_name"] = parts[0]
            profile["last_name"] = parts[-1] if len(parts) > 1 else ""

    linkedin = _grab(r"(https?://(?:www\.)?linkedin\.com/[^\s\n]+)", text)
    if linkedin:
        profile["linkedin"] = linkedin.rstrip("/")

    github = _grab(r"(https?://(?:www\.)?github\.com/[^\s\n]+)", text)
    if github:
        profile["github"] = github.rstrip("/")

    portfolio = _grab(r"Portfolio[:\s]+([^\s\n]+)", text)
    if portfolio:
        profile["portfolio"] = portfolio.rstrip("/")

    profile["years_exp"] = _estimate_years_exp(text)

    return profile


def cv_profile() -> dict:
    """Return a parsed snapshot of CV.txt. Re-reads on mtime change."""
    global _cache, _cache_mtime
    if not os.path.exists(CV_PATH):
        return {}
    try:
        mtime = os.path.getmtime(CV_PATH)
    except OSError:
        return dict(_cache)
    if mtime != _cache_mtime:
        _cache = _parse(_read_cv())
        _cache_mtime = mtime
    return dict(_cache)
