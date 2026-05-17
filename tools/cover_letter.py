"""Cover-letter generation.

When an Easy Apply form has a separate file-upload slot for a motivation/cover letter
(as opposed to the resume slot), the bot generates a tailored letter via the LLM using
the candidate's resume + the job description, renders it as a PDF, and uploads that.

The PDF stays in /cover-letters/<company>-<title>-<timestamp>.pdf for the user's
records (per request: store after using)."""

import os
import re
import threading
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

from tools.llm_models import get_ollama_base_url, resolve_model
from tools.resume_parser import get_resume_text
from tools.profile_overrides import load as load_overrides
from tools.cv_profile import cv_profile


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


CRITIC_ENABLED = _env_bool("COVER_LETTER_CRITIC_ENABLED", True)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COVER_LETTERS_DIR = os.path.join(PROJECT_ROOT, "cover-letters")
_LOCK = threading.Lock()


_SYSTEM = (
    "You write tailored cover letters in the candidate's voice. Use ONLY facts from the "
    "resume — never invent experience, certifications, languages, or skills. Match the "
    "language of the job description (e.g. write in French if the description is in "
    "French). Keep it tight: 250-380 words, professional, first-person, no fluff. "
    "Open with why this role + company specifically. Middle: 2-3 concrete resume bullets "
    "that map to the job description. Close with availability + sign-off. "
    "Output plain text only — no markdown, no headers, no bullet points, no '[' "
    "placeholders. Use real paragraph breaks (blank lines)."
)


_HUMAN = """Resume:
{resume}

Job:
- Company: {company}
- Title: {title}
- Description: {description}

Candidate:
- Name: {full_name}
- Email: {email}
- Phone: {phone}
- City: {city}

Write the cover letter. Open with a greeting (e.g. "Dear Hiring Team," or the equivalent
in the description's language). End with the candidate's full name on its own line.
Plain text, no markdown."""


_LLM_CACHE: dict[str, ChatOllama] = {}


def _llm(model_name: str) -> ChatOllama:
    cached = _LLM_CACHE.get(model_name)
    if cached is None:
        cached = ChatOllama(model=model_name, temperature=0.4, base_url=get_ollama_base_url())
        _LLM_CACHE[model_name] = cached
    return cached


def _candidate_profile() -> dict:
    cv = cv_profile()
    ov = load_overrides()
    first = ov.get("first_name") or cv.get("first_name") or ""
    last = ov.get("last_name") or cv.get("last_name") or ""
    return {
        "full_name": (f"{first} {last}").strip() or "Candidate",
        "email": ov.get("email") or cv.get("email") or "",
        "phone": ov.get("phone") or cv.get("phone") or "",
        "city": ov.get("city") or cv.get("city") or "",
    }


def generate_text(job: dict, llm_model: str | None) -> str:
    """Ask the LLM for a tailored cover letter. Returns plain-text body."""
    resume = (get_resume_text() or "").strip()
    if not resume:
        print("[CoverLetter] No CV text available; cannot generate.", flush=True)
        return ""
    model_name = resolve_model(llm_model)
    prof = _candidate_profile()
    description = ((job.get("description") or job.get("summary") or "") + "")[:2500]
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | _llm(model_name)
    try:
        raw = chain.invoke({
            "resume": resume[:4000],
            "company": (job.get("company") or "the company")[:120],
            "title": (job.get("title") or "the role")[:120],
            "description": description or "(no description provided)",
            **prof,
        })
        text = getattr(raw, "content", None)
        if not isinstance(text, str):
            text = ""
        return text.strip()
    except Exception as exc:
        print(f"[CoverLetter] LLM call failed: {type(exc).__name__}: {exc}", flush=True)
        return ""


def _safe_filename(s: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "").strip())
    return cleaned.strip("_") or "untitled"


def _sanitize_for_latin1(text: str) -> str:
    """fpdf2's built-in Helvetica is Latin-1 only. Replace common typographic chars."""
    replacements = {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "--",
        "…": "...",
        "•": "*",
        " ": " ",
        " ": " ", " ": " ",
        "→": "->", "←": "<-",
    }
    out = text
    for k, v in replacements.items():
        out = out.replace(k, v)
    # Drop anything still outside Latin-1.
    return out.encode("latin-1", errors="ignore").decode("latin-1")


def render_pdf(text: str, output_path: str, header_lines: list[str]) -> bool:
    """Render the cover letter as a single-page PDF (Letter size, 1in margins)."""
    try:
        from fpdf import FPDF
    except ImportError:
        print("[CoverLetter] fpdf2 not installed — cannot render PDF.", flush=True)
        return False
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        pdf = FPDF(format="Letter", unit="in")
        pdf.set_auto_page_break(auto=True, margin=1.0)
        pdf.add_page()
        pdf.set_margins(1.0, 1.0, 1.0)

        # Header (name, contact, date) — right-aligned would be classier but left works.
        pdf.set_font("Helvetica", "B", 11)
        if header_lines:
            for i, line in enumerate(header_lines):
                line = _sanitize_for_latin1(line)
                if not line:
                    continue
                if i == 0:
                    pdf.set_font("Helvetica", "B", 12)
                else:
                    pdf.set_font("Helvetica", "", 10)
                pdf.cell(0, 0.22, line, ln=1)
            pdf.ln(0.15)

        pdf.set_font("Helvetica", "", 11)
        body = _sanitize_for_latin1(text or "").strip()
        # Render paragraph-by-paragraph so blank lines become real spacing.
        for para in body.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            # multi_cell with width 0 → full page width minus margins.
            pdf.multi_cell(0, 0.22, para)
            pdf.ln(0.12)
        pdf.output(output_path)
        return True
    except Exception as exc:
        print(f"[CoverLetter] PDF render failed: {exc}", flush=True)
        return False


def make_for_job(job: dict, llm_model: str | None) -> Optional[str]:
    """Generate → critique → (revise once if flagged) → persist as PDF. Returns the path."""
    text = generate_text(job, llm_model)
    if not text:
        return None
    # Critic pass: catch hallucinated skills, language mismatch, length issues. If the
    # critic flags issues, regenerate with the feedback once and replace `text`.
    if CRITIC_ENABLED:
        feedback = critique(text, job, llm_model)
        if not feedback.get("ok") and feedback.get("issues"):
            print(
                f"[CoverLetter-critic] flagged: {'; '.join(feedback['issues'])[:200]} — "
                f"regenerating once with feedback",
                flush=True,
            )
            revised = regenerate_with_feedback(job, llm_model, feedback["issues"])
            if revised:
                text = revised
        else:
            print(f"[CoverLetter-critic] OK", flush=True)
    prof = _candidate_profile()
    company = _safe_filename((job.get("company") or "company")[:50])
    title = _safe_filename((job.get("title") or "role")[:50])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{company}-{title}-{stamp}.pdf"
    with _LOCK:
        os.makedirs(COVER_LETTERS_DIR, exist_ok=True)
    pdf_path = os.path.join(COVER_LETTERS_DIR, filename)
    header_lines = [
        prof["full_name"],
        prof["email"],
        prof["phone"],
        prof["city"],
        datetime.now().strftime("%B %d, %Y"),
    ]
    header_lines = [h for h in header_lines if h]
    if not render_pdf(text, pdf_path, header_lines):
        return None
    print(f"[CoverLetter] Wrote {pdf_path}", flush=True)
    return pdf_path


# ─── Critic ─────────────────────────────────────────────────────────────────

class _CritiqueResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ok: bool = Field(default=True)
    issues: list[str] = Field(default_factory=list, description="Short bullet-list of problems; empty if ok.")


_CRITIC_SYSTEM = (
    "You review a cover letter that was just generated for a candidate. Flag SPECIFIC "
    "problems only — be sparing, don't invent issues. Flag when ANY of:\n"
    "  - It mentions a tech / tool / certification / language not in the resume\n"
    "  - The language of the letter doesn't match the job description\n"
    "  - It's outside 200-450 words\n"
    "  - It contains placeholder text like '[Company]' or 'Lorem ipsum'\n"
    "  - It includes false work-history claims (e.g. 'I worked at <company>' when not in resume)\n"
    "  - It opens with markdown / a heading / bullet points (must be plain prose)\n"
    "If the letter is fine, return ok=true with an empty issues list. Be tolerant of style "
    "differences; focus on correctness, honesty, and language."
)


_CRITIC_HUMAN = """Resume (truncated):
{resume}

Job:
- Company: {company}
- Title: {title}
- Description (first 500 chars): {description}

Generated cover letter:
\"\"\"
{letter}
\"\"\"

Return JSON: {{ok: bool, issues: [short strings]}}."""


def critique(letter_text: str, job: dict, llm_model: str | None) -> dict:
    """Returns {ok: bool, issues: list[str]}."""
    if not letter_text or not letter_text.strip():
        return {"ok": False, "issues": ["empty letter"]}
    resume = (get_resume_text() or "").strip()
    if not resume:
        return {"ok": True, "issues": []}
    model_name = resolve_model(llm_model)
    prompt = ChatPromptTemplate.from_messages([("system", _CRITIC_SYSTEM), ("human", _CRITIC_HUMAN)])
    structured = _llm(model_name).with_structured_output(_CritiqueResult, method="json_schema")
    chain = prompt | structured
    try:
        result = chain.invoke({
            "resume": resume[:3000],
            "company": (job.get("company") or "")[:120],
            "title": (job.get("title") or "")[:120],
            "description": ((job.get("description") or "") + "")[:500],
            "letter": letter_text[:3500],
        })
        d = result.model_dump()
        return {"ok": bool(d.get("ok", True)), "issues": [str(i)[:200] for i in d.get("issues", [])][:6]}
    except Exception as exc:
        print(f"[CoverLetter-critic] LLM critique failed: {type(exc).__name__}: {exc}", flush=True)
        return {"ok": True, "issues": []}  # fail-open: don't block on critic error


_REGEN_HUMAN = """Resume:
{resume}

Job:
- Company: {company}
- Title: {title}
- Description: {description}

Candidate:
- Name: {full_name}
- Email: {email}
- Phone: {phone}
- City: {city}

A first draft was rejected by a reviewer for these reasons:
{issues}

Write a NEW cover letter that fixes every issue listed above while still drawing only on
facts from the resume. Plain text, no markdown. End with the candidate's full name.
"""


def regenerate_with_feedback(job: dict, llm_model: str | None, issues: list[str]) -> str:
    """Second-pass generation that addresses the critic's feedback."""
    resume = (get_resume_text() or "").strip()
    if not resume or not issues:
        return ""
    model_name = resolve_model(llm_model)
    prof = _candidate_profile()
    description = ((job.get("description") or job.get("summary") or "") + "")[:2500]
    issues_str = "\n".join(f"- {i}" for i in issues[:6])
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _REGEN_HUMAN)])
    chain = prompt | _llm(model_name)
    try:
        raw = chain.invoke({
            "resume": resume[:4000],
            "company": (job.get("company") or "the company")[:120],
            "title": (job.get("title") or "the role")[:120],
            "description": description or "(no description provided)",
            "issues": issues_str,
            **prof,
        })
        text = getattr(raw, "content", None)
        return text.strip() if isinstance(text, str) else ""
    except Exception as exc:
        print(f"[CoverLetter-critic] regenerate failed: {type(exc).__name__}: {exc}", flush=True)
        return ""
