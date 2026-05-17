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
    "You have the candidate's resume, the question label, the answer format, and the job "
    "context (company + role). Reason like a careful, honest applicant: the resume is the "
    "ONLY source of truth. NEVER invent credentials, employers, technologies, certifications, "
    "languages, or skills. If something is not in the resume, it does not exist for you. "
    "Be conservative on questions about sponsorship, criminal history, or prior history "
    "with THIS company."
)

_HUMAN = """Resume (truncated):
{resume}

Job context:
- Company: {job_company}
- Role: {job_title}
- Description (truncated): {job_description}

Question / label:
{question}

Field kind: {kind}
Character budget for free-text answers: {max_chars}
Options (when present, your answer MUST be one of them char-for-char; for `checkbox-group`
you MAY pick MULTIPLE separated by `|`):
{options}

HONESTY RULE — APPLIES TO EVERY ANSWER:
- A technology, tool, language, library, framework, certification, or skill EXISTS for the
  candidate only if it (or a clear synonym/abbreviation) appears verbatim in the resume.
- If the resume does not mention it, you MUST answer as if the candidate has zero experience
  with it. NEVER invent. NEVER round 0 up to 1 to look better. NEVER assume Python implies R,
  TensorFlow implies PyTorch, AWS implies Azure, etc. — only what's literally in the resume.

REASONING RULES:
- "Years of experience with <thing>" (numeric field): scan the resume for <thing>. If
  present, estimate years from the relevant experience/projects. If <thing> is NOT in the
  resume at all, answer "0". Do not pick "1" as a polite default.
- "Have you used / do you know / are you certified in / are you familiar with <thing>"
  (Yes/No): answer "Yes" only if <thing> is in the resume; otherwise "No".
- "Are you fluent in <language>" (human language): answer "Yes" only for languages listed in
  the resume's LANGUAGES section. Otherwise "No".
- Company-history questions ("have you ever worked / interviewed / applied / had a recruitment
  process at <THIS company>"): scan the resume's work experience for the company name shown
  above. If the company is NOT present, answer "No". Do not assume prior history.
- Sponsorship / visa / criminal record / non-compete: answer "No" unless the resume explicitly
  says otherwise.
- "Authorized to work in <country>", "right to work", "willing to relocate", "available to
  start": answer "Yes" when consistent with the resume; otherwise "No".
- Salary / expected compensation: "Negotiable" unless the resume gives a number.
- Free-text fields: write 2–5 substantive sentences drawn from the resume. Stay within
  {max_chars} characters. Match the language of the question (FR/ES/DE/IT/PT/EN).
- Multi-select (`kind` == "checkbox-group"): list ALL options that genuinely apply per the
  resume, separated by `|` — e.g. "Rabat|Casablanca". For cities-mobility questions, include
  any city the resume says the candidate lives or has worked in. Pick at least one when the
  field is mandatory.
- Dropdown / radio: pick the option that best matches the resume. For "How did you hear about
  us?" with no resume signal, prefer the most plausible generic answer ("LinkedIn").
- If you cannot answer confidently AND no honest default applies, leave answer empty.
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


def _salvage_plain_answer(text: str) -> str:
    """Recover the answer from a model that didn't honor the JSON schema.

    Models like gpt-oss:120b-cloud just emit the answer as plain text. We accept that —
    strip code fences, decode JSON if present, drop common prefixes, and return the body."""
    import json as _json
    if not text:
        return ""
    s = str(text).strip()
    # Strip triple-backtick fences.
    if s.startswith("```"):
        s = s.strip("`")
        # Drop optional language tag on the first line.
        if "\n" in s:
            first, rest = s.split("\n", 1)
            if len(first.strip()) <= 12 and not first.strip().startswith("{"):
                s = rest
        s = s.strip("`").strip()
    # Try JSON — model may have produced valid JSON despite the framework's complaint,
    # or partial JSON; pull the `answer` field if so.
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = _json.loads(s)
            if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
                return obj["answer"].strip()
        except Exception:
            pass
    # Drop common labelling prefixes.
    for prefix in ("answer:", "Answer:", "ANSWER:", "réponse:", "Réponse:", "Respuesta:"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):].strip()
            break
    # Strip outer quotes.
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s


def llm_answer_for_field(
    label: str,
    options: list[str] | None,
    kind: str,
    llm_model: str | None,
    job_context: dict | None = None,
    max_chars: int | None = None,
) -> str | None:
    """Ask the LLM to fill one form field. Returns the answer string or None.

    - `job_context` carries {title, company, description} so the LLM can answer
      company-specific questions ("have you ever worked at X") truthfully.
    - `max_chars` is the form-imposed cap on free-text answers (e.g. textarea maxlength).
    - For `kind == "checkbox-group"`, the LLM is told it may return options pipe-separated;
      callers parse the result themselves (don't pass that to _match_answer_to_option)."""
    if not label:
        return None
    model_name = resolve_model(llm_model)
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    ctx = job_context or {}
    company = (ctx.get("company") or "").strip()
    title = (ctx.get("title") or "").strip()
    description = (ctx.get("description") or "").strip()[:600]
    budget = max_chars if (isinstance(max_chars, int) and max_chars > 0) else 800

    cache_key = (label.strip().lower(), model_name, "|".join(opts), company.lower(), budget)
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
    invoke_args = {
        "resume": resume,
        "question": label.strip(),
        "kind": kind,
        "options": options_str,
        "job_company": company or "(unknown)",
        "job_title": title or "(unknown)",
        "job_description": description or "(none)",
        "max_chars": budget,
    }
    print(
        f"[form_llm] Asking LLM (model={model_name}) for {label!r} kind={kind} "
        f"opts={opts} company={company!r} budget={budget}", flush=True,
    )
    last_err = None
    result = None
    for attempt in range(2):
        try:
            result = chain.invoke(invoke_args)
            break
        except Exception as exc:
            last_err = exc
            print(f"[form_llm] LLM attempt {attempt + 1} (structured) failed: {type(exc).__name__}: {str(exc)[:200]}", flush=True)

    # Fallback: many Ollama models (gpt-oss, llama variants) don't honor JSON schema and emit
    # the raw answer as text. If structured parsing failed but the model is clearly producing
    # useful content, salvage it via a plain-text completion and wrap it ourselves.
    if result is None:
        try:
            print(f"[form_llm] Falling back to plain-text completion for {label!r}", flush=True)
            plain_chain = prompt | llm
            raw = plain_chain.invoke(invoke_args)
            # IMPORTANT: distinguish "content is None / missing" from "content is empty
            # string". Empty string is a real (useless) model output — don't fall back
            # to `str(raw)` which leaks the full AIMessage repr into the form.
            content_attr = getattr(raw, "content", None)
            if isinstance(content_attr, str):
                text = content_attr
            elif content_attr is None and not hasattr(raw, "content"):
                text = str(raw)
            else:
                text = ""
            cleaned = _salvage_plain_answer(text)
            if cleaned:
                result = FormFieldAnswer(answer=cleaned, confidence=60)
                print(f"[form_llm] Plain-text salvage produced: {cleaned[:120]!r}{'…' if len(cleaned)>120 else ''}", flush=True)
            else:
                print(f"[form_llm] Plain-text fallback got empty content (model={model_name})", flush=True)
        except Exception as exc:
            print(f"[form_llm] Plain-text fallback also failed: {type(exc).__name__}: {exc}", flush=True)

    if result is None:
        print(f"[form_llm] LLM gave up after retries for {label!r} (last_err={last_err})", flush=True)
        _ANSWER_CACHE[cache_key] = ""
        return None

    answer = (result.answer or "").strip()
    if not answer:
        print(f"[form_llm] LLM returned empty for {label!r}", flush=True)
        _ANSWER_CACHE[cache_key] = ""
        return None

    # Multi-select: caller parses the pipe-separated list itself; cache as-is.
    if kind == "checkbox-group" and opts:
        print(f"[form_llm] {label!r} → multi-select raw {answer!r}", flush=True)
        _ANSWER_CACHE[cache_key] = answer
        return answer

    # Single-option: force a strict match (also handles cross-locale Yes/No mapping).
    if opts:
        match = _match_answer_to_option(answer, opts)
        if match is not None:
            print(f"[form_llm] {label!r} → matched option {match!r} (LLM said {answer!r})", flush=True)
            _ANSWER_CACHE[cache_key] = match
            return match
        print(f"[form_llm] {label!r}: LLM answer {answer!r} not in options {opts}", flush=True)
        _ANSWER_CACHE[cache_key] = ""
        return None

    # Free-text: trim to budget if the model overshot.
    if budget and len(answer) > budget:
        answer = answer[: budget].rstrip()
    print(f"[form_llm] {label!r} → {answer[:80]!r}{'…' if len(answer) > 80 else ''}", flush=True)
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
# ─── Validation-driven revision ─────────────────────────────────────────────

_REVISE_SYSTEM = (
    "You revise a SINGLE form-field answer that a validator rejected. Read the validator's "
    "complaint — it tells you the format or constraint to satisfy (e.g. \"decimal greater "
    "than 0.0\", \"valid phone number\", \"max 100 characters\", \"select one of the listed "
    "options\"). Produce a new value that satisfies the validator AND remains truthful to "
    "the resume. The resume is the only source of truth. "
    "\n\nHONESTY RULE — APPLIES TO EVERY REVISION:"
    "\n- A technology, tool, language, library, framework, certification, or skill EXISTS for "
    "the candidate only if it (or a clear synonym) appears verbatim in the resume."
    "\n- NEVER invent experience to satisfy a validator. If the field asks 'years of X' and "
    "X is not in the resume, the honest answer is 0 — even if the validator demands > 0. "
    "In that case, return an empty string. Do not lie to make the form pass."
    "\n- Format fixes (decimal, phone, max-length) are fine — those don't require inventing "
    "facts. But a SEMANTIC fix (\"need more years\") that contradicts the resume must be "
    "refused with an empty response."
    "\n\nOutput ONLY the new value — no explanation, no quotes, no JSON, no labels. "
    "Match the language of the question."
)


_REVISE_HUMAN = """Resume (truncated):
{resume}

Job context:
- Company: {job_company}
- Role: {job_title}

Field label:
{question}

Field kind: {kind}
Allowed options (if non-empty, your answer MUST be exactly one of these):
{options}

Validator's complaint (in the form's language — read it carefully):
{error}

Previous answer that was REJECTED:
{previous}

Output ONLY the new value. Examples of correct outputs:
- For "must be a decimal greater than 0.0", AND the tech is in the resume with N years of
  use → "N.0" (e.g. "5.0"). If the tech is NOT in the resume → "" (refuse; do not invent).
- For "must be a valid phone number" → "+212648073768" (from the resume).
- For "select one of the options" → the exact text of one option that fits the resume.
- For "max 100 characters" → a sentence ≤ 100 chars summarising the resume.
- If satisfying the validator requires claiming experience or facts NOT in the resume →
  output an empty string (a single newline is fine). Do not lie.
"""


def llm_revise_answer(
    label: str,
    validation_error: str,
    previous_answer: str,
    kind: str,
    llm_model: str | None,
    job_context: dict | None = None,
    max_chars: int | None = None,
    options: list[str] | None = None,
) -> str | None:
    """Ask the LLM to fix a single answer given the validator's complaint.

    Uses a plain-text completion (no JSON schema) because the response is a single value
    and most local models drop JSON structure when answering one-word."""
    if not label or not validation_error:
        return None
    model_name = resolve_model(llm_model)
    ctx = job_context or {}
    company = (ctx.get("company") or "").strip()
    title = (ctx.get("title") or "").strip()
    resume = _truncate(get_resume_text() or "")
    if not resume:
        return None
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    options_str = "\n".join(f"- {o}" for o in opts) if opts else "(none — free form)"

    prompt = ChatPromptTemplate.from_messages([("system", _REVISE_SYSTEM), ("human", _REVISE_HUMAN)])
    llm = _get_llm(model_name)
    chain = prompt | llm

    try:
        raw = chain.invoke({
            "resume": resume,
            "question": label.strip(),
            "error": validation_error.strip(),
            "previous": (previous_answer or "(empty)")[:200],
            "kind": kind,
            "options": options_str,
            "job_company": company or "(unknown)",
            "job_title": title or "(unknown)",
        })
        content = getattr(raw, "content", None)
        text = content if isinstance(content, str) else ""
        cleaned = _salvage_plain_answer(text)
        if not cleaned:
            print(f"[form_llm-revise] empty revision for {label!r}", flush=True)
            return None
        if max_chars and len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rstrip()
        # If options are constrained, force a strict match.
        if opts:
            match = _match_answer_to_option(cleaned, opts)
            if match is None:
                print(f"[form_llm-revise] revision {cleaned!r} doesn't match options {opts}", flush=True)
                return None
            cleaned = match
        print(
            f"[form_llm-revise] {label!r} validator={validation_error[:60]!r} previous={previous_answer[:40]!r} → {cleaned[:80]!r}",
            flush=True,
        )
        return cleaned
    except Exception as exc:
        print(f"[form_llm-revise] failed for {label!r}: {type(exc).__name__}: {exc}", flush=True)
        return None


_NEGATIVE_DEFAULT_TERMS = (
    # Sensitive / sponsorship / legal.
    "sponsorship", "visa sponsor", "sponsor your visa",
    "convicted", "criminal", "felony",
    "currently employed", "currently working",
    "compete", "non-compete", "non compete",
    # Prior history with THIS employer — default to No when the resume doesn't say yes.
    # These are CATEGORIES of question, not company names; safe to keep here.
    "ever worked", "previously worked", "worked here", "worked with us", "worked at our",
    "former employee", "former colleague", "alumni",
    "previously applied", "applied before", "applied to us",
    "interviewed before", "previous interview", "interview process",
    "recruitment process", "had a recruitment", "had recruitment",
    # FR/ES/DE/IT/PT phrases for the same category.
    "travaillé chez", "candidaté", "déjà postulé", "déjà candidaté", "déjà entretien",
    "ya ha trabajado", "ha trabajado", "ha postulado", "anteriormente",
    "schon einmal", "bereits beworben", "ehemalig",
    "già lavorato", "già candidato",
    "já trabalhou", "já candidatou",
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
