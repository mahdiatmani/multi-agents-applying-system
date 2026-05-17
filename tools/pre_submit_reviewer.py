"""Pre-submit Reviewer agent.

Runs right before clicking Next/Review/Submit on an Easy Apply step. Audits every
filled text/textarea/select field against the resume + job. Flagged fields
(hallucinated skills, object-repr leaks, language mismatch, empty required) are
cleared so the next autofill pass re-resolves them with the failure context.

Toggle via env: PRE_SUBMIT_REVIEWER_ENABLED=false to disable entirely."""

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


ENABLED = _env_bool("PRE_SUBMIT_REVIEWER_ENABLED", True)

_LLM_CACHE: dict[str, ChatOllama] = {}


class FieldVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int = Field(default=-1, description="0-based index from the input list.")
    ok: bool = Field(default=True, description="True if the value is plausibly correct.")
    issue: str = Field(default="", description="Short reason when ok=false. Empty otherwise.")


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdicts: list[FieldVerdict] = Field(default_factory=list)


# NOTE: any literal `{` or `}` in this string must be doubled (`{{` / `}}`).
# ChatPromptTemplate.from_messages parses this as an f-string template; single
# braces are treated as variable placeholders. `'{...: ...}'` previously broke
# Easy Apply with "Invalid variable name '...' in f-string template".
_SYSTEM = (
    "You audit a candidate's filled-out Easy Apply form before submission. For each "
    "(label, value) pair, judge whether the value is plausibly correct given the resume "
    "and the job context. Flag (ok=false) when ANY of the following hold:\n"
    "  - The value contains code or object representation garbage (e.g. 'content=...', "
    "    'AIMessage(', 'additional_kwargs=', '{{...: ...}}')\n"
    "  - It claims a skill / tool / certification / language NOT in the resume\n"
    "  - It's an empty required field (label looks required but value is empty)\n"
    "  - The language of the value mismatches the question (e.g. an English paragraph "
    "    in answer to a French question)\n"
    "  - It's logically wrong given the resume (e.g. 'Yes, I worked at COMPANY' when "
    "    COMPANY isn't in the resume's work experience)\n"
    "Otherwise ok=true. Be tolerant of valid short answers (numbers, phone numbers, single "
    "words) — don't over-flag."
)


_HUMAN = """Resume (truncated):
{resume}

Job:
- Company: {company}
- Title: {title}

Filled fields (audit each in order, output verdicts in the SAME order):
{fields}

Return JSON: a list of verdicts, one per field, with `index`, `ok`, `issue`."""


def _llm(model_name: str) -> ChatOllama:
    cached = _LLM_CACHE.get(model_name)
    if cached is None:
        cached = ChatOllama(model=model_name, temperature=0, base_url=get_ollama_base_url())
        _LLM_CACHE[model_name] = cached
    return cached


def audit(filled: list[dict], job: dict | None, llm_model: str | None) -> list[dict]:
    """Audit a batch of filled fields. Input: list of {label, value, kind}.
    Returns a list of {ok: bool, issue: str} the same length as input."""
    n = len(filled)
    if n == 0:
        return []
    safe_default = [{"ok": True, "issue": ""} for _ in range(n)]
    if not ENABLED:
        return safe_default
    resume = (get_resume_text() or "").strip()
    if not resume:
        return safe_default

    model_name = resolve_model(llm_model)
    job = job or {}
    fields_str = "\n".join(
        f"{i}. [{(f.get('kind') or '?')}] {(f.get('label') or '?')[:80]} = "
        f"{((f.get('value') or '(empty)'))[:240]}"
        for i, f in enumerate(filled)
    )
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    structured = _llm(model_name).with_structured_output(AuditResult, method="json_schema")
    chain = prompt | structured
    print(f"[Reviewer] auditing {n} field(s) against resume + job={job.get('company','?')!r}", flush=True)
    try:
        result = chain.invoke({
            "resume": resume[:3500],
            "company": (job.get("company") or "")[:120],
            "title": (job.get("title") or "")[:120],
            "fields": fields_str,
        })
        data = result.model_dump().get("verdicts") or []
        by_index = {int(v.get("index", -1)): v for v in data if isinstance(v, dict)}
        out: list[dict] = []
        for i in range(n):
            v = by_index.get(i) or {"ok": True, "issue": ""}
            out.append({
                "ok": bool(v.get("ok", True)),
                "issue": str(v.get("issue", ""))[:240],
            })
        flagged = sum(1 for v in out if not v["ok"])
        print(f"[Reviewer] flagged {flagged}/{n}", flush=True)
        return out
    except Exception as exc:
        print(f"[Reviewer] audit failed ({type(exc).__name__}): {exc}", flush=True)
        return safe_default
