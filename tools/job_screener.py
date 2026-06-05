"""Job-fit Pre-screener agent.

Before the bot opens a job card in the search results, this agent reads the card's
visible text (title + company + location + brief snippet) and gives a 0-100 fit
score vs the CV. Cards below the threshold are marked processed and skipped without
ever being opened — saving a click, a get_job_details, an evaluate LLM call, and an
Easy Apply attempt that would have failed on poor match anyway.

Toggle via env: JOB_SCREENER_ENABLED=false to disable.
Threshold via env: JOB_FIT_SCREEN_THRESHOLD (default 40)."""

import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

from tools.llm_models import get_ollama_base_url, resolve_model
from tools.resume_parser import get_resume_text


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


ENABLED = _env_bool("JOB_SCREENER_ENABLED", True)
THRESHOLD = int(os.getenv("JOB_FIT_SCREEN_THRESHOLD", "40"))

_LLM_CACHE: dict[str, ChatOllama] = {}


class FitScore(BaseModel):
    model_config = ConfigDict(extra="ignore")
    score: int = Field(default=0, ge=0, le=100)
    reason: str = Field(default="", description="One short sentence justification.")


_SYSTEM = (
    "You quickly score how well a job listing matches a candidate's resume. "
    "Output a 0-100 score and a one-sentence reason. Be strict but realistic:\n"
    "  0-20  - clear mismatch (different field, requires X yrs the candidate doesn't have, etc.)\n"
    "  20-40 - tangentially related, low match\n"
    "  40-60 - partial match\n"
    "  60-85 - good match\n"
    "  85-100 - excellent match (role and stack align well)\n"
    "Focus on: role title vs candidate's specialization, required tech stack vs resume "
    "skills, seniority level. A general-purpose junior role doesn't penalize heavily; a "
    "senior role requiring 10 years for a junior candidate scores low."
)


_HUMAN = """Candidate resume (skills + recent role):
{resume_summary}

Job listing card (title, company, location, snippet):
{card_text}

Score the fit 0-100 with a one-sentence reason."""


def _llm(model_name: str) -> ChatOllama:
    cached = _LLM_CACHE.get(model_name)
    if cached is None:
        cached = ChatOllama(model=model_name, temperature=0, base_url=get_ollama_base_url())
        _LLM_CACHE[model_name] = cached
    return cached


def screen(card_text: str, llm_model: str | None) -> dict:
    """Score this card. Returns {score, reason}. score=-1 means screening unavailable/failed
    (caller should NOT skip on score=-1; it falls through to normal processing)."""
    if not ENABLED or not card_text or not card_text.strip():
        return {"score": -1, "reason": "screener disabled or empty card"}
    resume = (get_resume_text() or "").strip()
    if not resume:
        return {"score": -1, "reason": "no resume"}
    model_name = resolve_model(llm_model)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    structured = _llm(model_name).with_structured_output(FitScore, method="json_schema")
    chain = prompt | structured
    try:
        result = chain.invoke({
            "resume_summary": resume[:1800],
            "card_text": card_text[:600],
        })
        d = result.model_dump()
        return {"score": int(d.get("score", 0) or 0), "reason": (d.get("reason") or "")[:200]}
    except Exception as exc:
        print(f"[Screener] LLM screening failed: {type(exc).__name__}: {exc}", flush=True)
        return {"score": -1, "reason": "llm_error"}


def passes(score: int, threshold: int | None = None) -> bool:
    t = threshold if threshold is not None else THRESHOLD
    return score < 0 or score >= t  # score == -1 (unknown) defaults to PASS so screening never blocks
