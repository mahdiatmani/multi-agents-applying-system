import os
import re
from typing import Any

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from tools.llm_models import get_ollama_base_url, resolve_model
from tools.resume_parser import get_resume_text

_LLM_CACHE: dict[tuple[str, str], Any] = {}
_ANSWER_CACHE: dict[tuple[str, str, str], str] = {}


class FormFieldAnswer(BaseModel):
    answer: str = Field(default="", description="Best answer for this field. For radios/selects, exact text of the chosen option. For text/number inputs, the value to type.")
    confidence: int = Field(default=0, ge=0, le=100)


_SYSTEM = (
    "You fill out a single field on a LinkedIn Easy Apply form on behalf of a candidate. "
    "Use the candidate's resume and the question to pick the most plausible favorable answer. "
    "Never invent credentials. Be conservative on sensitive questions (sponsorship, criminal history)."
)

_HUMAN = """Resume (truncated):
{resume}

Question / label:
{question}

Field kind: {kind}
Options (if any — pick ONE exactly as written; empty list means free-form text):
{options}

GUIDELINES:
- For Yes/No questions favourable to the candidate (start date, willing to relocate, authorized to work): answer "Yes".
- For sponsorship / visa / criminal questions: answer "No" unless the resume clearly states otherwise.
- For "years of experience" with a tech: estimate based on resume; if absent, answer "1".
- For salary / compensation: answer "Negotiable".
- For free-text questions ≤ 200 chars: write a short, professional, first-person sentence.
- If the question is irrelevant or you cannot answer confidently: leave answer empty.
- If options are provided, your answer MUST be one of them, character-for-character.
"""


def _get_llm(model_name: str):
    base_url = get_ollama_base_url()
    key = (model_name, base_url)
    cached = _LLM_CACHE.get(key)
    if cached is None:
        cached = ChatOllama(model=model_name, temperature=0, base_url=base_url)
        _LLM_CACHE[key] = cached
    return cached


def _truncate(text: str, max_chars: int = 4000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def llm_answer_for_field(
    label: str,
    options: list[str] | None,
    kind: str,
    llm_model: str | None,
) -> str | None:
    """Ask the LLM to fill one form field. Returns the answer string or None."""
    if not label:
        return None
    model_name = resolve_model(llm_model)
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    cache_key = (label.strip().lower(), model_name, "|".join(opts))
    if cache_key in _ANSWER_CACHE:
        cached = _ANSWER_CACHE[cache_key]
        return cached or None

    resume = _truncate(get_resume_text() or "")
    if not resume:
        return None

    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    llm = _get_llm(model_name)
    structured = llm.with_structured_output(FormFieldAnswer, method="json_schema")
    chain = prompt | structured

    options_str = "\n".join(f"- {o}" for o in opts) if opts else "(none — free-form text)"
    print(f"[form_llm] Asking LLM (model={model_name}) for {label!r} kind={kind} options={opts}", flush=True)
    last_err = None
    result = None
    for attempt in range(2):
        try:
            result = chain.invoke({
                "resume": resume,
                "question": label.strip(),
                "kind": kind,
                "options": options_str,
            })
            break
        except Exception as exc:
            last_err = exc
            print(f"[form_llm] LLM attempt {attempt + 1} failed for {label!r}: {type(exc).__name__}: {exc}", flush=True)
    if result is None:
        print(f"[form_llm] LLM gave up after retries for {label!r} (last_err={last_err})", flush=True)
        _ANSWER_CACHE[cache_key] = ""
        return None

    answer = (result.answer or "").strip()
    if not answer:
        print(f"[form_llm] LLM returned empty for {label!r}", flush=True)
        _ANSWER_CACHE[cache_key] = ""
        return None

    # If options were given, force a strict match (also handles cross-locale Yes/No mapping).
    if opts:
        match = _match_answer_to_option(answer, opts)
        if match is not None:
            print(f"[form_llm] {label!r} → matched option {match!r} (LLM said {answer!r})", flush=True)
            _ANSWER_CACHE[cache_key] = match
            return match
        print(f"[form_llm] {label!r}: LLM answer {answer!r} not in options {opts}", flush=True)
        _ANSWER_CACHE[cache_key] = ""
        return None

    print(f"[form_llm] {label!r} → {answer!r}", flush=True)
    _ANSWER_CACHE[cache_key] = answer
    return answer


def _match_answer_to_option(answer: str, opts: list[str]) -> str | None:
    """Map an LLM answer to one of the available options, cross-locale aware for Yes/No."""
    if not opts:
        return None
    a = answer.strip().lower()
    # Exact / substring match.
    for o in opts:
        ol = o.lower()
        if ol == a or a in ol or ol.startswith(a):
            return o
    # Cross-locale Yes/No mapping.
    if _YES_RE.match(answer):
        for o in opts:
            if _YES_RE.match(o):
                return o
    if _NO_RE.match(answer):
        for o in opts:
            if _NO_RE.match(o):
                return o
    return None


_YES_RE = re.compile(r"^\s*(yes|oui|sí|si|ja)\s*$", re.IGNORECASE)
_NO_RE = re.compile(r"^\s*(no|non|nein|nao|não)\s*$", re.IGNORECASE)
_NEGATIVE_DEFAULT_TERMS = (
    "sponsorship", "visa sponsor", "sponsor your visa",
    "convicted", "criminal", "felony",
    "currently employed", "currently working",
    "compete", "non-compete", "non compete",
)


def safe_default_for_binary(label: str, options: list[str] | None) -> str | None:
    """For a Yes/No fieldset with no other signal, pick Yes by default unless the question is negative-impact."""
    if not options:
        return None
    opts = [str(o).strip() for o in options if str(o).strip()]
    if len(opts) != 2:
        return None
    yes_opt = next((o for o in opts if _YES_RE.match(o)), None)
    no_opt = next((o for o in opts if _NO_RE.match(o)), None)
    if not (yes_opt and no_opt):
        return None
    lower_label = (label or "").lower()
    if any(term in lower_label for term in _NEGATIVE_DEFAULT_TERMS):
        return no_opt
    return yes_opt
