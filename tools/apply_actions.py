import math
import os
import re
import glob
from playwright.sync_api import Page
from tools.playwright_actions import random_sleep
from tools.cv_profile import cv_profile
from tools.profile_overrides import load as load_overrides
from tools import qa_overrides
from tools.form_llm import llm_answer_for_field, safe_default_for_binary, llm_revise_answer
from tools.run_control import checkpoint as _run_checkpoint
from tools import human_loop

MAX_APPLY_STEPS = 20
_MODAL_SELECTORS = (
    "div.jobs-easy-apply-modal",
    "div[data-test-modal-id='easy-apply-modal']",
    "div[role='dialog'][aria-labelledby*='easy-apply']",
    "div[role='dialog'][aria-labelledby*='jobs-apply']",
)
_SAVE_ARIA_TERMS = ("save", "enregistrer", "sauvegarder", "guardar", "speichern", "salva", "salvar")
_CONFIRMATION_TERMS = (
    "application sent", "your application was sent", "applied",
    "candidature envoyée", "votre candidature a été envoyée", "candidature soumise",
    "solicitud enviada", "candidatura enviada",
    "bewerbung gesendet", "candidatura inviata",
)


def _resolve(field: str, env_key: str, default: str = "") -> str:
    """Resolution chain: UI override -> .env -> CV.txt -> default."""
    ov = load_overrides()
    val = ov.get(field)
    if val:
        return str(val)
    env_val = os.getenv(env_key)
    if env_val:
        return env_val
    cv_val = cv_profile().get(field)
    if cv_val:
        return str(cv_val)
    return default


def _years_exp() -> str:
    ov = load_overrides()
    if ov.get("years_exp"):
        return str(ov["years_exp"])
    env_val = os.getenv("APPLICANT_YEARS_EXP")
    if env_val:
        return env_val
    y = cv_profile().get("years_exp")
    if y is None:
        return "1"
    try:
        years = float(y)
    except (TypeError, ValueError):
        return "1"
    if years < 1:
        return "1"
    return str(int(math.ceil(years)))


def _phone() -> str:
    return _resolve("phone", "APPLICANT_PHONE")


def _linkedin() -> str:
    return _resolve("linkedin", "APPLICANT_LINKEDIN")


def _portfolio() -> str:
    ov = load_overrides()
    if ov.get("portfolio"):
        return str(ov["portfolio"])
    env_val = os.getenv("APPLICANT_PORTFOLIO")
    if env_val:
        return env_val
    cv = cv_profile()
    return cv.get("portfolio") or cv.get("github") or ""


def _github() -> str:
    return _resolve("github", "APPLICANT_GITHUB")


def _city() -> str:
    return _resolve("city", "APPLICANT_CITY")


def _country() -> str:
    """Country resolution: override → env → CV profile.country → infer from CV location 'City, Country'."""
    ov = load_overrides()
    if ov.get("country"):
        return str(ov["country"])
    env_val = os.getenv("APPLICANT_COUNTRY")
    if env_val:
        return env_val
    cv = cv_profile()
    if cv.get("country"):
        return str(cv["country"])
    # Many CVs follow "Location: City, Country" — split on commas.
    for key in ("location", "address"):
        val = cv.get(key) or ""
        if "," in val:
            tail = val.split(",")[-1].strip()
            # Keep it short; skip if it looks like a state or zip code.
            if tail and len(tail) <= 30 and not tail.isdigit():
                return tail
    return ""


def _email() -> str:
    return _resolve("email", "APPLICANT_EMAIL")


def _first_name() -> str:
    return _resolve("first_name", "APPLICANT_FIRST_NAME")


def _last_name() -> str:
    return _resolve("last_name", "APPLICANT_LAST_NAME")


def _static(field: str, env_key: str, default: str) -> str:
    ov = load_overrides()
    if ov.get(field):
        return str(ov[field])
    return os.getenv(env_key, default)


_HOME_TERMS_DEFAULT = (
    "morocco", "maroc", "marruecos", "moroccan",
    "rabat", "casablanca", "casa", "marrakech", "marrakesh",
    "fez", "fes", "tangier", "tanger", "tangiers", "agadir",
    "kenitra", "meknes", "meknès", "oujda", "tetouan", "tetouán",
    "sale", "salé", "mohammedia", "beni mellal", "el jadida",
    "nador", "settat", "berkane", "larache", "khouribga",
    "ouarzazate", "errachidia", "taza", "khemisset", "ifrane",
)


def _home_terms() -> tuple[str, ...]:
    custom = os.getenv("APPLICANT_HOME_TERMS", "").strip()
    if custom:
        return tuple(t.strip().lower() for t in custom.split(",") if t.strip())
    return _HOME_TERMS_DEFAULT


def _is_home_job(job_details: dict | None) -> bool | None:
    """True if job location matches a home-country term, False if clearly abroad, None if unknown."""
    if not job_details:
        return None
    location = (job_details.get("location") or "").lower()
    if not location:
        return None
    terms = _home_terms()
    if any(t in location for t in terms):
        return True
    return False


def _authorized_answer(job_details: dict | None) -> str:
    ov = load_overrides()
    if ov.get("authorized"):
        return str(ov["authorized"])
    env_val = os.getenv("APPLICANT_AUTHORIZED")
    if env_val:
        return env_val
    home = _is_home_job(job_details)
    if home is True:
        return "Yes"
    if home is False:
        return "No"
    return "Yes"


def _sponsorship_answer(job_details: dict | None) -> str:
    ov = load_overrides()
    if ov.get("sponsorship"):
        return str(ov["sponsorship"])
    env_val = os.getenv("APPLICANT_SPONSORSHIP")
    if env_val:
        return env_val
    home = _is_home_job(job_details)
    if home is True:
        return "No"
    if home is False:
        return "Yes"
    return "No"


def _resume_path() -> str | None:
    root = os.path.join(os.path.dirname(__file__), "..")
    explicit = os.getenv("RESUME_PDF_PATH")
    if explicit:
        path = explicit if os.path.isabs(explicit) else os.path.join(root, explicit)
        if os.path.exists(path):
            return path
    for pattern in ("*.pdf", "*.PDF"):
        for path in glob.glob(os.path.join(root, pattern)):
            return path
    return None


def _visible(locator) -> bool:
    try:
        return locator.is_visible(timeout=500)
    except Exception:
        return False


def _label_text(field) -> str:
    """Best-effort text for the label associated with a form control."""
    try:
        return (field.evaluate(
            """el => {
                const id = el.id;
                if (id) {
                    const l = document.querySelector('label[for=\"' + CSS.escape(id) + '\"]');
                    if (l) return l.innerText;
                }
                const wrap = el.closest('div.fb-dash-form-element, .jobs-easy-apply-form-element, fieldset, .artdeco-form-item');
                if (wrap) {
                    const l = wrap.querySelector('label, legend, .artdeco-text-input--label, .fb-dash-form-element__label');
                    if (l) return l.innerText;
                }
                return '';
            }"""
        ) or "").lower()
    except Exception:
        return ""


def _answer_for(label: str, context: dict | None = None) -> str | None:
    """Map a question label to an answer. Context may include `job_details` for per-job decisions."""
    if not label:
        return None
    ctx = context or {}
    job_details = ctx.get("job_details")
    text = label.lower()
    if any(k in text for k in ("years of experience", "years of work experience", "how many years", "years' experience")):
        return _years_exp()
    # Phone — require a phone-context word, not bare "mobile" (collides with form labels
    # like "are you mobile to [city]" which is about willingness to relocate, not phones).
    if "phone" in text or "telephone" in text or "téléphone" in text or "telefono" in text:
        return _phone() or None
    if ("mobile" in text or "cell" in text or "portable" in text) and any(
        ctx_word in text for ctx_word in ("number", "phone", "tel", "numéro", "numero")
    ):
        return _phone() or None
    # LinkedIn — match standalone "linkedin" labels too; only skip when the label is
    # clearly about something else (photo, connections, post).
    if "linkedin" in text and not any(neg in text for neg in ("photo", "connection", "post", "feed", "headline")):
        return _linkedin() or None
    if "github" in text:
        return _github() or None
    if any(k in text for k in ("portfolio", "website", "personal site", "site web", "sitio web", "página")):
        return _portfolio() or None
    # City — multi-locale.
    if any(k in text for k in (
        "city", "current location",
        "ville",                          # FR
        "ciudad",                         # ES
        "stadt",                          # DE
        "città", "citta",                 # IT
        "cidade",                         # PT
        "מקום",                           # HE (best-effort)
    )) or text.strip() in ("location", "ville", "city", "stadt", "ciudad", "cidade", "città"):
        return _city() or None
    # Country — multi-locale.
    if any(k in text for k in (
        "country",
        "pays",                           # FR
        "país", "pais",                   # ES / PT
        "paese",                          # IT
        "land",                           # DE / NL
    )) and "nationality" not in text:
        return _country() or None
    if "nationality" in text or "nationalité" in text or "nationalidad" in text:
        # Nationality often equals country, fall back to country if no explicit override.
        return _country() or None
    if "first name" in text:
        return _first_name() or None
    if "last name" in text or "surname" in text:
        return _last_name() or None
    if "email" in text:
        return _email() or None
    if any(k in text for k in ("salary", "compensation", "expected pay")):
        return _static("salary", "APPLICANT_SALARY", "") or None
    if "notice" in text:
        return _static("notice", "APPLICANT_NOTICE", "2 weeks")
    if any(k in text for k in ("authorized to work", "authorised to work", "work authorization", "legally authorized", "right to work", "authorized for employment")):
        return _authorized_answer(job_details)
    if any(k in text for k in ("require sponsorship", "need sponsorship", "visa sponsorship", "sponsorship now", "sponsorship in the future")):
        return _sponsorship_answer(job_details)
    if "relocate" in text or "willing to move" in text:
        return _static("relocate", "APPLICANT_RELOCATE", "Yes")
    return None


_OBJECT_REPR_MARKERS = (
    "additional_kwargs=", "response_metadata=", "tool_calls=", "usage_metadata=",
    "AIMessage(", "HumanMessage(", "ToolMessage(", "ChatGeneration(",
    "model_provider=", "prompt_eval_count=",
)


def _looks_like_object_repr(text: str) -> bool:
    """Detect LangChain / dict-like reprs that leaked into an answer string. These
    contain multiple `key=value` pairs and shouldn't end up in a form field."""
    if not text or len(text) < 40:
        return False
    hits = sum(1 for m in _OBJECT_REPR_MARKERS if m in text)
    return hits >= 2


def _resolve_answer(
    label: str,
    options: list[str] | None,
    kind: str,
    context: dict | None,
    allow_human_loop: bool = False,
    max_chars: int | None = None,
) -> str | None:
    """Layered answer resolution: heuristics → user overrides → LLM → safe default → ask human."""
    ctx = context or {}
    label = (label or "").strip()
    if not label:
        print("[Resolve] Skipped: empty label", flush=True)
        return None
    short = label[:80].replace("\n", " ")
    print(f"[Resolve] Q={short!r} kind={kind} options={options}", flush=True)
    # Layer 1: hardcoded heuristics.
    answer = _answer_for(label, ctx)
    if answer:
        print(f"[Resolve]   → L1 heuristic: {answer!r}", flush=True)
        return answer
    # Layer 2: user-editable Q&A overrides.
    answer = qa_overrides.match(label, options)
    if answer:
        print(f"[Resolve]   → L2 override: {answer!r}", flush=True)
        return answer
    # Layer 3: LLM-assisted filler — with job context and per-field char budget.
    llm_model = (ctx.get("llm_model") if isinstance(ctx, dict) else None) or None
    job_details = (ctx.get("job_details") or {}) if isinstance(ctx, dict) else {}
    job_ctx = {
        "title": (job_details.get("title") or "")[:120],
        "company": (job_details.get("company") or "")[:120],
        "description": (job_details.get("description") or "")[:600],
    }
    answer = llm_answer_for_field(
        label, options or [], kind, llm_model,
        job_context=job_ctx, max_chars=max_chars,
    )
    if answer:
        # Defensive: reject obvious junk leaking from a misbehaving model wrapper
        # (LangChain AIMessage repr, RunInfo, etc.) — these always contain `content=`
        # plus other key=value pairs and would otherwise be typed into the form.
        if _looks_like_object_repr(answer):
            print(f"[Resolve]   → L3 LLM returned object-repr garbage, dropping: {answer[:120]!r}", flush=True)
            answer = None
        else:
            print(f"[Resolve]   → L3 LLM: {(answer[:80] + '...') if len(answer) > 80 else answer!r}", flush=True)
            return answer
    # Layer 4: safe default for binary Yes/No questions.
    if kind in ("radio", "select"):
        answer = safe_default_for_binary(label, options or [])
        if answer:
            print(f"[Resolve]   → L4 safe-default: {answer!r}", flush=True)
            return answer
    # Layer 5: ask the human (only for required fields — caller opts in).
    if allow_human_loop:
        job_details = ctx.get("job_details") or {}
        ctx_msg = ""
        if job_details:
            title = (job_details.get("title") or "").strip()
            company = (job_details.get("company") or "").strip()
            if title or company:
                ctx_msg = f"{title} @ {company}".strip(" @")
        try:
            answer = human_loop.ask_user(label, options or [], kind, ctx_msg)
        except Exception as exc:
            print(f"[Resolve]   → L5 human-loop error: {exc}", flush=True)
            answer = None
        if answer:
            print(f"[Resolve]   → L5 human: {answer!r}", flush=True)
            return answer
    print("[Resolve]   → UNRESOLVED (will leave empty)", flush=True)
    return None


def _fill_text_inputs(page: Page, context: dict | None = None) -> None:
    # Broader selector: any input that's not radio/checkbox/hidden/file/button/typeahead, plus textareas.
    # Typeaheads (role='combobox' or aria-autocomplete) are skipped here so _fill_comboboxes
    # can drive them with real keystrokes and pick a dropdown suggestion.
    inputs = _modal_scope(page).locator(
        "input:not([type='radio']):not([type='checkbox']):not([type='hidden']):not([type='file'])"
        ":not([type='submit']):not([type='button']):not([readonly]):not([disabled])"
        ":not([role='combobox']):not([aria-autocomplete]):not([aria-haspopup='listbox']), "
        "textarea:not([readonly]):not([disabled])"
    ).all()
    print(f"[TextInputs] found {len(inputs)} candidate text fields", flush=True)
    for field in inputs:
        try:
            if not _visible(field):
                continue
            try:
                current = (field.input_value() or "").strip()
            except Exception:
                current = ""
            if current:
                continue
            label = _label_text(field)
            try:
                tag = (field.evaluate("el => el.tagName") or "").lower()
            except Exception:
                tag = "input"
            kind = "textarea" if tag == "textarea" else "text"
            # Detect maxlength so the LLM knows the character budget. LinkedIn often sets
            # the limit on the DOM property (and enforces with JS) rather than the HTML
            # attribute — read both. `el.maxLength` returns -1 when not set.
            max_chars = None
            try:
                ml_attr = field.get_attribute("maxlength")
                if ml_attr and ml_attr.isdigit():
                    max_chars = int(ml_attr)
            except Exception:
                pass
            if max_chars is None:
                try:
                    ml_prop = field.evaluate("el => el.maxLength")
                    if isinstance(ml_prop, int) and ml_prop > 0:
                        max_chars = ml_prop
                except Exception:
                    pass
            if max_chars is None:
                # Last resort: scrape a "0/<N>" counter next to the textarea (LinkedIn pattern).
                try:
                    n = field.evaluate(
                        """el => {
                            const wrap = el.closest('div.fb-dash-form-element, .artdeco-form-item, div');
                            if (!wrap) return null;
                            const txt = (wrap.innerText || '');
                            const m = txt.match(/\\d+\\s*\\/\\s*([\\d,]+)/);
                            if (m) return parseInt(m[1].replace(/,/g, ''), 10);
                            return null;
                        }"""
                    )
                    if isinstance(n, int) and n > 0:
                        max_chars = n
                except Exception:
                    pass
            print(f"[TextInputs] empty field label={label!r} max_chars={max_chars}", flush=True)
            answer = _resolve_answer(label, None, kind, context, max_chars=max_chars)
            if answer:
                try:
                    field.fill(answer)
                    print(f"[TextInputs] filled {label!r} with {answer[:60]!r}", flush=True)
                except Exception as e:
                    print(f"[TextInputs] fill failed for {label!r}: {e}", flush=True)
        except Exception as e:
            print(f"[TextInputs] iteration error: {e}", flush=True)
            continue


def _radio_group_label(group) -> str:
    """Extract the question text for a radio group: try <legend>, then aria-labelledby, then a sibling <label>."""
    try:
        legend = group.locator("legend").first
        if _visible(legend):
            txt = (legend.inner_text() or "").strip()
            if txt:
                # Legend often contains duplicated visible+visually-hidden text — keep first line only.
                return txt.splitlines()[0].strip()
    except Exception:
        pass
    try:
        # aria-labelledby points to one or more element IDs whose combined text is the label.
        label_text = group.evaluate(
            """el => {
                const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                if (ids.length) {
                    return ids.map(id => {
                        const n = document.getElementById(id);
                        return n ? n.innerText : '';
                    }).join(' ').trim();
                }
                // Try a label inside the parent .fb-dash-form-element wrapper
                const wrap = el.closest('div.fb-dash-form-element, .jobs-easy-apply-form-element, .artdeco-form-item');
                if (wrap) {
                    const l = wrap.querySelector('label, .artdeco-text-input--label, .fb-dash-form-element__label, span[id]');
                    if (l) return l.innerText;
                }
                return '';
            }"""
        )
        if label_text:
            return str(label_text).strip().splitlines()[0].strip()
    except Exception:
        pass
    return ""


def _fill_radios(page: Page, context: dict | None = None) -> None:
    scope = _modal_scope(page)
    # LinkedIn uses a mix of <fieldset> and <div role="radiogroup">. Cover both.
    groups = scope.locator(
        "fieldset[data-test-form-builder-radio-button-form-component], "
        "fieldset, "
        "div[role='radiogroup']"
    ).all()
    seen: set[int] = set()
    for fs in groups:
        try:
            if not _visible(fs):
                continue
            # Skip if no radio inputs inside — avoids matching irrelevant fieldsets (e.g., "language" wrapper).
            radio_count = fs.locator("input[type='radio']").count()
            if radio_count == 0:
                continue
            # Dedupe nested groups using JS handle id (best-effort).
            try:
                key = id(fs)
                if key in seen:
                    continue
                seen.add(key)
            except Exception:
                pass

            legend = _radio_group_label(fs)

            # Collect labels associated with the radios.
            label_locators = fs.locator("label").all()
            option_texts: list[str] = []
            label_map: dict[str, object] = {}
            for label in label_locators:
                try:
                    if not _visible(label):
                        continue
                    txt = (label.inner_text() or "").strip()
                    if not txt:
                        continue
                    first_line = txt.splitlines()[0].strip()
                    if first_line and first_line not in label_map:
                        option_texts.append(first_line)
                        label_map[first_line] = label
                except Exception:
                    continue
            if not option_texts:
                continue
            print(f"[Radios] group legend={legend!r} options={option_texts}", flush=True)
            answer = _resolve_answer(legend, option_texts, "radio", context)
            if not answer:
                continue
            answer_lc = answer.strip().lower()
            target = None
            for opt_text in option_texts:
                ot = opt_text.lower()
                if ot == answer_lc or answer_lc in ot or ot.startswith(answer_lc):
                    target = label_map.get(opt_text)
                    break
            if target is None:
                print(f"[Radios] answer {answer!r} did not map to any option {option_texts}", flush=True)
                continue
            try:
                target.click()
                print(f"[Radios] clicked {opt_text!r} for legend {legend!r}", flush=True)
            except Exception as e:
                print(f"[Radios] click failed: {e}", flush=True)
                continue
        except Exception as e:
            print(f"[Radios] group iteration error: {e}", flush=True)
            continue


def _fill_selects(page: Page, context: dict | None = None) -> None:
    selects = _modal_scope(page).locator("select").all()
    for sel in selects:
        try:
            if not _visible(sel):
                continue
            label = _label_text(sel)
            options = sel.locator("option").all()
            option_texts: list[str] = []
            value_map: dict[str, str] = {}
            for opt in options:
                try:
                    txt = (opt.inner_text() or "").strip()
                    if not txt or txt.lower().startswith("select"):
                        continue
                    if txt not in value_map:
                        option_texts.append(txt)
                        value_map[txt] = opt.get_attribute("value") or txt
                except Exception:
                    continue
            if not option_texts:
                continue
            answer = _resolve_answer(label, option_texts, "select", context)
            if not answer:
                continue
            answer_lc = answer.strip().lower()
            target_text = None
            for opt_text in option_texts:
                if opt_text.lower() == answer_lc or answer_lc in opt_text.lower() or opt_text.lower().startswith(answer_lc):
                    target_text = opt_text
                    break
            if not target_text:
                continue
            try:
                sel.select_option(value_map[target_text])
            except Exception:
                try:
                    sel.select_option(label=target_text)
                except Exception:
                    continue
        except Exception:
            continue


def _autofill_step(page: Page, context: dict | None = None) -> None:
    ctx = context or {}
    handle_resume_upload(page, job=ctx.get("job_details"), llm_model=ctx.get("llm_model"))
    # Typeaheads MUST run before plain text inputs — otherwise fill() sets the value without
    # firing the keydown events the typeahead listens for, and the suggestion is never picked.
    _fill_comboboxes(page, context)
    _fill_text_inputs(page, context)
    _fill_radios(page, context)
    _fill_selects(page, context)
    _fill_contenteditables(page, context)
    _fill_checkbox_groups(page, context)
    _fill_single_checkboxes(page, context)
    _second_pass_required(page, context)
    # Pre-submit Reviewer: audit filled values + clear anything obviously wrong + retry once.
    _pre_submit_review(page, context)
    _audit_required_fields(page)


def _collect_filled_text_fields(scope) -> list[dict]:
    """Return [{tag, kind, name, id, label, value}] for every visible FILLED text/textarea/
    select in the current modal step. Skips radio/checkbox/file/hidden — these are usually
    constrained-format and not the source of hallucinated answers."""
    try:
        result = scope.evaluate(
            """root => {
                const out = [];
                root.querySelectorAll('input, textarea, select').forEach(el => {
                    if (el.disabled) return;
                    const t = (el.type || '').toLowerCase();
                    if (el.tagName !== 'SELECT' && el.tagName !== 'TEXTAREA') {
                        if (['radio','checkbox','file','hidden','submit','button'].includes(t)) return;
                    }
                    let value = '';
                    if (el.tagName === 'SELECT') {
                        const opt = el.options[el.selectedIndex];
                        if (opt) value = opt.text || opt.value || '';
                    } else {
                        value = el.value || '';
                    }
                    value = (value || '').trim();
                    if (!value) return;
                    // Skip placeholder-only values on selects.
                    const vlow = value.toLowerCase();
                    if (el.tagName === 'SELECT' && (vlow.startsWith('select') || vlow.startsWith('--'))) return;
                    let label = '';
                    if (el.id) {
                        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                        if (l) label = l.innerText;
                    }
                    if (!label) {
                        const wrap = el.closest('div.fb-dash-form-element, fieldset, .artdeco-form-item');
                        if (wrap) {
                            const l = wrap.querySelector('label, legend, .artdeco-text-input--label, .fb-dash-form-element__label');
                            if (l) label = l.innerText;
                        }
                    }
                    out.push({
                        tag: el.tagName,
                        kind: el.tagName === 'SELECT' ? 'select' : (el.tagName === 'TEXTAREA' ? 'textarea' : 'text'),
                        name: el.name || '',
                        id: el.id || '',
                        label: (label || '').trim().split('\\n')[0],
                        value: value,
                    });
                });
                return out;
            }"""
        ) or []
        return result
    except Exception as exc:
        print(f"[Reviewer] field collection failed: {exc}", flush=True)
        return []


def _clear_field_for_revise(scope, ef: dict) -> bool:
    """Clear a filled field so the next autofill pass re-resolves it from scratch."""
    try:
        sel = None
        if ef.get("id"):
            sel = f"#{ef['id']}"
        elif ef.get("name"):
            tag = (ef.get("tag") or "").lower()
            if tag == "select":
                sel = f"select[name=\"{ef['name']}\"]"
            else:
                sel = f"[name=\"{ef['name']}\"]"
        if not sel:
            return False
        target = scope.locator(sel).first
        if ef.get("kind") in ("text", "textarea"):
            try:
                target.fill("")
            except Exception:
                target.evaluate(
                    "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }"
                )
            return True
        if ef.get("kind") == "select":
            target.evaluate(
                "el => { el.selectedIndex = 0; el.dispatchEvent(new Event('change', {bubbles:true})); }"
            )
            return True
    except Exception as exc:
        print(f"[Reviewer]   clear failed for {ef.get('label','?')[:60]!r}: {exc}", flush=True)
        return False
    return False


def _pre_submit_review(page: Page, context: dict | None) -> None:
    """Audit filled text/textarea/select values for hallucinations/junk; clear flagged
    fields and re-fill them once. Bounded to a single retry — the reviewer's purpose is
    catching obvious mistakes, not running an infinite loop."""
    try:
        from tools import pre_submit_reviewer
    except Exception:
        return
    if not pre_submit_reviewer.ENABLED:
        return
    scope = _modal_scope(page)
    filled = _collect_filled_text_fields(scope)
    if not filled:
        return
    ctx = context or {}
    verdicts = pre_submit_reviewer.audit(filled, ctx.get("job_details") or {}, ctx.get("llm_model"))
    flagged = [(ef, v) for ef, v in zip(filled, verdicts) if not v.get("ok", True)]
    if not flagged:
        return
    print(f"[Reviewer] {len(flagged)} field(s) flagged — clearing & re-resolving:", flush=True)
    cleared_any = False
    for ef, v in flagged:
        print(
            f"[Reviewer]   {ef['label'][:60]!r} value={(ef['value'] or '')[:60]!r}  "
            f"→ issue={v.get('issue','')[:120]!r}",
            flush=True,
        )
        if _clear_field_for_revise(scope, ef):
            cleared_any = True
    if not cleared_any:
        return
    # Re-resolve just the now-empty fields via the existing pipelines.
    _fill_text_inputs(page, context)
    _fill_selects(page, context)
    _second_pass_required(page, context)


# ─── single-checkbox semantics ──────────────────────────────────────────────

_CONSENT_PHRASES = (
    # English
    "i agree", "i accept", "i confirm", "i acknowledge", "i have read", "i consent",
    "agree to the terms", "accept the terms", "agree to", "consent to", "certify that",
    "i declare", "by submitting", "by checking this box",
    # French
    "j'accepte", "je reconnais", "je confirme", "je certifie", "je déclare",
    "vous reconnaissez", "vous acceptez", "confirmé",
    # Spanish
    "acepto", "reconozco", "confirmo", "estoy de acuerdo", "he leído", "declaro",
    # German
    "ich akzeptiere", "ich bestätige", "ich erkläre", "ich stimme", "ich willige",
    # Italian
    "accetto", "confermo", "riconosco", "dichiaro",
    # Portuguese
    "aceito", "confirmo", "reconheço", "declaro",
)
# When ANY of these appear, default to UNCHECKED — these are opt-in marketing / contact
# preferences that shouldn't be auto-enabled even though they read like consent.
_OPT_OUT_PHRASES = (
    "marketing", "promotional", "newsletter", "third party", "third-party",
    "unsubscribe", "opt out", "opt-out", "do not contact",
    "publicidad", "boletín", "boletin", "marketing email",
    "désinscription", "ne pas contacter", "à des fins commerciales", "à des fins de marketing",
    "marketing zwecken", "werbung",
    "fini di marketing", "comunicazioni promozionali",
)


def _looks_like_consent(label: str, ctx: str) -> bool:
    """True iff the (label + surrounding paragraph) reads as a positive consent
    statement we should agree to, and contains no marketing-opt-out language."""
    text = f"{label} {ctx}".lower()
    if not text.strip():
        return False
    if any(opt in text for opt in _OPT_OUT_PHRASES):
        return False
    return any(p in text for p in _CONSENT_PHRASES)


def _checkbox_question_context(cb) -> tuple[str, str]:
    """Return (short_label, surrounding_paragraph) for a standalone checkbox.

    LinkedIn often labels the box with just one word ('Confirmé') while the actual
    question — multiple lines of legal/consent text — lives in a sibling <p> above.
    The model can't reason from 'Confirmé' alone; we hand it the paragraph."""
    label_text = ""
    try:
        cb_id = cb.get_attribute("id") or ""
        if cb_id:
            scope_root = cb
            try:
                lbl = cb.page.locator(f"label[for=\"{cb_id}\"]").first
                if _visible(lbl):
                    label_text = ((lbl.inner_text() or "").strip().splitlines() or [""])[0]
            except Exception:
                pass
        if not label_text:
            try:
                parent_label = cb.locator("xpath=ancestor::label[1]").first
                if _visible(parent_label):
                    label_text = ((parent_label.inner_text() or "").strip().splitlines() or [""])[0]
            except Exception:
                pass
    except Exception:
        pass
    paragraph = ""
    try:
        paragraph = cb.evaluate(
            """el => {
                // Walk up to find a container that holds a substantial sibling paragraph/heading.
                let node = el;
                const seenTexts = new Set();
                for (let depth = 0; depth < 6 && node; depth++) {
                    const parent = node.parentElement;
                    if (!parent) break;
                    const candidates = parent.querySelectorAll('p, h3, h4, .fb-dash-form-element__label, legend');
                    for (const c of candidates) {
                        if (c.contains(el)) continue;
                        const text = (c.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (text.length < 25) continue;
                        if (seenTexts.has(text)) continue;
                        seenTexts.add(text);
                        return text;
                    }
                    node = parent;
                }
                return '';
            }"""
        ) or ""
    except Exception:
        pass
    return label_text, paragraph


def _checkbox_is_present(cb, page: Page) -> bool:
    """LinkedIn often visually hides the <input> itself and exposes a styled <label>.
    A `display:none` input would make `is_visible()` return False even though the
    user clearly sees the box. Treat the checkbox as 'present' if the input OR its
    label OR an ancestor label is visible."""
    try:
        if cb.is_visible(timeout=300):
            return True
    except Exception:
        pass
    try:
        cb_id = cb.get_attribute("id") or ""
        if cb_id:
            lbl = page.locator(f"label[for=\"{cb_id}\"]").first
            if lbl.is_visible(timeout=300):
                return True
    except Exception:
        pass
    try:
        parent = cb.locator("xpath=ancestor::label[1]").first
        if parent.is_visible(timeout=300):
            return True
    except Exception:
        pass
    return False


def _check_checkbox(cb, page: Page) -> bool:
    """Click the visible label (a human-equivalent action) rather than the hidden input.
    Falls back to force=True if no clickable label is available, and finally to a JS
    `el.checked = true` + change-event dispatch as last resort."""
    cb_id = ""
    try:
        cb_id = cb.get_attribute("id") or ""
    except Exception:
        pass
    if cb_id:
        try:
            lbl = page.locator(f"label[for=\"{cb_id}\"]").first
            if lbl.is_visible(timeout=300):
                lbl.click()
                # Verify the state actually flipped — some labels are decorative.
                try:
                    if cb.is_checked():
                        return True
                except Exception:
                    return True  # we did click; can't introspect
        except Exception:
            pass
    try:
        parent = cb.locator("xpath=ancestor::label[1]").first
        if parent.is_visible(timeout=300):
            parent.click()
            try:
                if cb.is_checked():
                    return True
            except Exception:
                return True
    except Exception:
        pass
    try:
        cb.check(force=True)
        return True
    except Exception:
        pass
    try:
        cb.evaluate(
            """el => { el.checked = true;
                       el.dispatchEvent(new Event('input', { bubbles: true }));
                       el.dispatchEvent(new Event('change', { bubbles: true })); }"""
        )
        return True
    except Exception:
        return False


def _fill_single_checkboxes(page: Page, context: dict | None = None) -> None:
    """Standalone checkboxes (consent / acknowledgment / single-question yes/no)."""
    scope = _modal_scope(page)
    try:
        checkboxes = scope.locator("input[type='checkbox']").all()
    except Exception:
        return
    if not checkboxes:
        return

    standalone: list[object] = []
    for cb in checkboxes:
        try:
            # Visual presence check — uses the LABEL when the input itself is hidden.
            if not _checkbox_is_present(cb, page):
                continue
            try:
                if cb.is_checked():
                    continue
            except Exception:
                pass
            name = ""
            try:
                name = cb.get_attribute("name") or ""
            except Exception:
                pass
            if name:
                try:
                    sibling_count = scope.locator(f"input[type='checkbox'][name=\"{name}\"]").count()
                except Exception:
                    sibling_count = 1
                if sibling_count > 1:
                    continue  # belongs to a multi-checkbox group
            standalone.append(cb)
        except Exception:
            continue
    if not standalone:
        return

    print(f"[Checkbox] found {len(standalone)} standalone checkbox(es)", flush=True)
    for cb in standalone:
        try:
            label, paragraph = _checkbox_question_context(cb)
            print(
                f"[Checkbox] label={label[:60]!r} paragraph={paragraph[:100]!r}",
                flush=True,
            )

            # Layer 0: consent heuristic — fast, language-agnostic, covers legal/GDPR boxes.
            if _looks_like_consent(label, paragraph):
                if _check_checkbox(cb, page):
                    print(f"[Checkbox]   → checked (consent heuristic: {label!r})", flush=True)
                else:
                    print(f"[Checkbox]   check failed via every strategy for {label!r}", flush=True)
                continue

            # Layers 1–4: route through the standard resolver with rich context.
            full_question = label
            if paragraph and len(paragraph) > len(label):
                full_question = (paragraph + " — checkbox label: " + (label or "(unlabelled)")).strip()
            answer = _resolve_answer(full_question, ["Yes", "No"], "checkbox", context)
            if not answer:
                print("[Checkbox]   → no answer in first pass; second_pass will escalate to human-loop if required", flush=True)
                continue
            ans_low = answer.strip().lower()
            yes_tokens = ("yes", "true", "1", "oui", "sí", "si", "ja", "check", "checked", "agree", "confirm")
            if ans_low in yes_tokens or any(ans_low.startswith(t) for t in yes_tokens):
                if _check_checkbox(cb, page):
                    print(f"[Checkbox]   → checked (resolver: {answer!r})", flush=True)
                else:
                    print(f"[Checkbox]   check failed via every strategy", flush=True)
            else:
                print(f"[Checkbox]   answer {answer!r} → leaving unchecked", flush=True)
        except Exception as exc:
            print(f"[Checkbox] iteration error: {exc}", flush=True)
            continue


def _fill_contenteditables(page: Page, context: dict | None = None) -> None:
    """LinkedIn occasionally renders rich-text inputs as <div contenteditable='true'>."""
    scope = _modal_scope(page)
    try:
        nodes = scope.locator("[contenteditable='true'], [contenteditable='']").all()
    except Exception:
        return
    if not nodes:
        return
    print(f"[ContentEditable] found {len(nodes)} candidate(s)", flush=True)
    for node in nodes:
        try:
            if not _visible(node):
                continue
            try:
                current = (node.inner_text() or "").strip()
            except Exception:
                current = ""
            if current:
                continue
            label = _label_text(node)
            print(f"[ContentEditable] empty label={label!r}", flush=True)
            answer = _resolve_answer(label, None, "textarea", context)
            if not answer:
                continue
            try:
                node.evaluate(
                    """(el, value) => {
                        el.focus();
                        el.innerText = value;
                        el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.blur();
                    }""",
                    answer,
                )
                print(f"[ContentEditable] filled {label!r} with {answer[:60]!r}", flush=True)
            except Exception as exc:
                print(f"[ContentEditable] fill failed for {label!r}: {exc}", flush=True)
        except Exception as exc:
            print(f"[ContentEditable] iteration error: {exc}", flush=True)
            continue


def _fill_comboboxes(page: Page, context: dict | None = None) -> None:
    """Typeahead inputs (city, school, company): type keystrokes to trigger LinkedIn's listbox,
    then click the first suggestion so the value is officially 'selected'."""
    scope = _modal_scope(page)
    try:
        boxes = scope.locator(
            "[role='combobox'], "
            "input[aria-autocomplete='list'], "
            "input[aria-autocomplete='both'], "
            "input[aria-haspopup='listbox']"
        ).all()
    except Exception:
        return
    if not boxes:
        return
    print(f"[Combobox] found {len(boxes)} candidate(s)", flush=True)
    seen: set[str] = set()
    for box in boxes:
        try:
            if not _visible(box):
                continue
            try:
                tag = (box.evaluate("el => el.tagName") or "").lower()
            except Exception:
                tag = ""
            if tag == "select":
                continue  # native <select role='combobox'> handled by _fill_selects
            # Dedupe — an element can match multiple selectors above.
            try:
                fingerprint = box.evaluate("el => (el.id || '') + '|' + (el.name || '') + '|' + (el.getAttribute('aria-labelledby') || '')")
            except Exception:
                fingerprint = ""
            if fingerprint and fingerprint in seen:
                continue
            if fingerprint:
                seen.add(fingerprint)
            try:
                if tag == "input":
                    current = (box.input_value() or "").strip()
                else:
                    current = (box.inner_text() or "").strip()
            except Exception:
                current = ""
            # Treat placeholder text ("Select an option", "Choisir", "Wählen", …) as empty.
            if current and not _is_placeholder_text(current):
                continue
            label = _label_text(box)
            print(f"[Combobox] empty/placeholder label={label!r} current={current[:40]!r}", flush=True)

            # ── Path A: dropdown-style (non-input) combobox ────────────────────
            # LinkedIn renders fixed-option fields as <div role="combobox">. Clicking
            # opens a listbox of the finite choices. Probe them and let the LLM pick.
            if tag != "input":
                try:
                    box.click()
                    random_sleep(0, 1)
                except Exception as exc:
                    print(f"[Combobox] click-to-open failed for {label!r}: {exc}", flush=True)
                    continue
                opts = _collect_listbox_option_texts(scope, page)
                if opts:
                    print(f"[Combobox] dropdown opened, options={opts}", flush=True)
                    answer = _resolve_answer(label, opts, "select", context)
                    if answer:
                        option_el = _first_listbox_option(scope, page, answer)
                        if option_el is not None:
                            try:
                                option_el.click()
                                random_sleep(0, 1)
                                print(f"[Combobox] picked {answer!r} for {label!r}", flush=True)
                                continue
                            except Exception as exc:
                                print(f"[Combobox] option click failed for {label!r}: {exc}", flush=True)
                        else:
                            print(f"[Combobox] no option visible matching {answer!r} for {label!r}", flush=True)
                    else:
                        print(f"[Combobox] resolver returned nothing for {label!r}; second_pass will escalate", flush=True)
                    # Close the open dropdown so it doesn't block other field interactions.
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                    continue
                # No options visible after click — fall through to typeahead flow.
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

            # ── Path B: typeahead (input that filters on keystrokes — city/school) ──
            answer = _resolve_answer(label, None, "text", context)
            if not answer:
                continue
            try:
                box.click()
                random_sleep(0, 1)
                if tag == "input":
                    try:
                        box.fill("")
                    except Exception:
                        pass
                    box.press_sequentially(answer, delay=40)
                else:
                    page.keyboard.type(answer, delay=40)
                if not _wait_for_listbox_option(scope, page, timeout_ms=2500):
                    box.press("Enter")
                    print(f"[Combobox] no listbox after typing {answer[:40]!r} for {label!r}; pressed Enter", flush=True)
                    continue
                option = _first_listbox_option(scope, page, answer)
                if option is not None:
                    try:
                        option.click()
                        print(f"[Combobox] picked suggestion for {label!r} typed={answer[:40]!r}", flush=True)
                        random_sleep(0, 1)
                    except Exception as exc:
                        print(f"[Combobox] option click failed for {label!r}: {exc} — falling back to Enter", flush=True)
                        box.press("Enter")
                else:
                    box.press("Enter")
                    print(f"[Combobox] couldn't match option for {label!r}; pressed Enter", flush=True)
            except Exception as exc:
                print(f"[Combobox] fill failed for {label!r}: {exc}", flush=True)
        except Exception as exc:
            print(f"[Combobox] iteration error: {exc}", flush=True)
            continue


_LISTBOX_OPTION_SELECTORS = (
    "[role='listbox'] [role='option']",
    ".basic-typeahead__triggered-content [role='option']",
    "div.search-basic-typeahead [role='option']",
    "ul.basic-typeahead__selectable [role='option']",
    ".artdeco-typeahead__results-list [role='option']",
    ".artdeco-dropdown__content [role='option']",
)

# Placeholder words shown inside an unselected combobox/dropdown. If the visible
# text starts with any of these, treat the field as EMPTY (not filled).
_DROPDOWN_PLACEHOLDER_PREFIXES = (
    "select",                 # EN
    "choisir", "choisir ",    # FR
    "sélection", "selection",
    "seleccion", "seleccionar",  # ES
    "selezion",               # IT (selezionare / seleziona)
    "wählen", "wahlen",       # DE
    "selecion",               # PT (selecionar)
    "--", "—",
)


def _is_placeholder_text(text: str) -> bool:
    if not text:
        return True
    low = text.strip().lower()
    return any(low.startswith(p) for p in _DROPDOWN_PLACEHOLDER_PREFIXES)


def _collect_listbox_option_texts(scope, page: Page, limit: int = 30) -> list[str]:
    """Read the visible options of an open listbox. Drops placeholder rows
    ('Select an option', '--', etc.) so the LLM only sees real choices."""
    out: list[str] = []
    seen: set[str] = set()
    for sel in _LISTBOX_OPTION_SELECTORS:
        for root in (scope, page):
            try:
                items = root.locator(sel).all()
            except Exception:
                items = []
            for item in items:
                try:
                    if not _visible(item):
                        continue
                    text = ((item.inner_text() or "").strip().splitlines() or [""])[0].strip()
                    if not text or text in seen:
                        continue
                    if _is_placeholder_text(text):
                        continue
                    seen.add(text)
                    out.append(text)
                    if len(out) >= limit:
                        return out
                except Exception:
                    continue
        if out:
            return out
    return out


def _wait_for_listbox_option(scope, page: Page, timeout_ms: int = 2500) -> bool:
    """Poll for any visible listbox option to appear. LinkedIn's typeahead is debounced."""
    import time as _t
    deadline = _t.time() + timeout_ms / 1000
    while _t.time() < deadline:
        for sel in _LISTBOX_OPTION_SELECTORS:
            try:
                loc = scope.locator(sel).first
                if _visible(loc):
                    return True
                loc = page.locator(sel).first
                if _visible(loc):
                    return True
            except Exception:
                continue
        _t.sleep(0.2)
    return False


def _first_listbox_option(scope, page: Page, query: str):
    """Return the best-matching listbox option for `query`, falling back to the first visible one."""
    qlow = (query or "").strip().lower()
    candidates = []
    for sel in _LISTBOX_OPTION_SELECTORS:
        for loc_root in (scope, page):
            try:
                items = loc_root.locator(sel).all()
            except Exception:
                items = []
            for item in items:
                try:
                    if not _visible(item):
                        continue
                    text = (item.inner_text() or "").strip()
                    if not text:
                        continue
                    candidates.append((text, item))
                except Exception:
                    continue
        if candidates:
            break
    if not candidates:
        return None
    # Prefer an option whose text starts with the typed query.
    for text, item in candidates:
        if text.lower().startswith(qlow):
            return item
    for text, item in candidates:
        if qlow in text.lower():
            return item
    return candidates[0][1]


def _fill_checkbox_groups(page: Page, context: dict | None = None) -> None:
    """Multi-select checkbox fieldsets — let LLM list relevant options free-form, click each match."""
    scope = _modal_scope(page)
    try:
        groups = scope.locator(
            "fieldset:has(input[type='checkbox']), "
            "div[role='group']:has(input[type='checkbox'])"
        ).all()
    except Exception:
        return
    if not groups:
        return
    seen_keys: set[int] = set()
    print(f"[Checkboxes] found {len(groups)} candidate group(s)", flush=True)
    for fs in groups:
        try:
            if not _visible(fs):
                continue
            try:
                key = id(fs)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            except Exception:
                pass
            checkboxes = fs.locator("input[type='checkbox']").all()
            if len(checkboxes) < 2:
                continue  # single-checkbox handled in second_pass / safe_default
            already_any = False
            for cb in checkboxes:
                try:
                    if cb.is_checked():
                        already_any = True
                        break
                except Exception:
                    continue
            if already_any:
                continue
            legend = _radio_group_label(fs)
            option_texts: list[str] = []
            label_map: dict[str, object] = {}
            for cb in checkboxes:
                try:
                    cb_id = cb.get_attribute("id") or ""
                    text = ""
                    if cb_id:
                        lbl = scope.locator(f"label[for=\"{cb_id}\"]").first
                        if _visible(lbl):
                            text = (lbl.inner_text() or "").strip().splitlines()[0].strip()
                    if not text:
                        try:
                            parent_lbl = cb.locator("xpath=ancestor::label[1]").first
                            if _visible(parent_lbl):
                                text = (parent_lbl.inner_text() or "").strip().splitlines()[0].strip()
                        except Exception:
                            pass
                    if text and text not in label_map:
                        option_texts.append(text)
                        label_map[text] = cb
                except Exception:
                    continue
            if not option_texts:
                continue
            print(f"[Checkboxes] group legend={legend!r} options={option_texts}", flush=True)
            # Route through _resolve_answer so the LLM gets the full job context (company, role,
            # description) and the real option list. The prompt instructs the model to return
            # multiple selections separated by '|', e.g. "Rabat|Casablanca".
            answer = _resolve_answer(legend, option_texts, "checkbox-group", context)
            picked: list[str] = []
            if answer:
                # Split on '|', ',', and ';' — be lenient about the model's separator choice.
                tokens = [t.strip() for t in re.split(r"[|,;]+", answer) if t.strip()]
                for tok in tokens:
                    tok_low = tok.lower()
                    # Exact / startswith / substring match against option labels.
                    matched_opt = None
                    for opt in option_texts:
                        ol = opt.lower()
                        if ol == tok_low or ol.startswith(tok_low) or tok_low in ol:
                            matched_opt = opt
                            break
                    if matched_opt and matched_opt not in picked:
                        target = label_map.get(matched_opt)
                        if target is None:
                            continue
                        try:
                            if _checkbox_is_present(target, page):
                                if _check_checkbox(target, page):
                                    picked.append(matched_opt)
                        except Exception:
                            continue
            # Don't auto-pick the first option as a fallback any more — it can be wrong.
            # If the LLM truly gave nothing useful, leave the group untouched; the second
            # pass will escalate to the human-loop modal if it's required.
            print(f"[Checkboxes] picked={picked} (from LLM answer {answer!r})", flush=True)
        except Exception as exc:
            print(f"[Checkboxes] iteration error: {exc}", flush=True)
            continue


def _second_pass_required(page: Page, context: dict | None = None) -> None:
    """For each required field still empty, look it up by id/name and fill it directly via LLM."""
    scope = _modal_scope(page)
    try:
        empty = scope.evaluate(
            """root => {
                const out = [];
                root.querySelectorAll('input, textarea, select').forEach(el => {
                    const required = el.required || el.getAttribute('aria-required') === 'true';
                    if (!required || el.disabled) return;
                    const t = (el.type || '').toLowerCase();
                    if (t === 'hidden' || t === 'file' || t === 'submit' || t === 'button') return;
                    if (t === 'checkbox') {
                        // Skip checkboxes that are part of a multi-checkbox group (handled elsewhere).
                        if (el.name) {
                            const siblings = root.querySelectorAll(`input[type="checkbox"][name="${el.name}"]`);
                            if (siblings.length > 1) return;
                        }
                        if (el.checked) return;
                        // Standalone unchecked required checkbox — let Python escalate.
                        let cbLabel = '';
                        if (el.id) {
                            const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                            if (l) cbLabel = (l.innerText || '').trim().split('\\n')[0];
                        }
                        if (!cbLabel) {
                            const wrap = el.closest('label');
                            if (wrap) cbLabel = (wrap.innerText || '').trim().split('\\n')[0];
                        }
                        // Pull a nearby paragraph for context (consent text usually lives there).
                        let para = '';
                        let node = el;
                        for (let d = 0; d < 6 && node; d++) {
                            const p = node.parentElement;
                            if (!p) break;
                            const cands = p.querySelectorAll('p, h3, h4, .fb-dash-form-element__label, legend');
                            for (const c of cands) {
                                if (c.contains(el)) continue;
                                const t2 = (c.innerText || '').replace(/\\s+/g, ' ').trim();
                                if (t2.length >= 25) { para = t2; break; }
                            }
                            if (para) break;
                            node = p;
                        }
                        out.push({
                            tag: 'CHECKBOX',
                            type: 'checkbox',
                            name: el.name || '',
                            id: el.id || '',
                            label: cbLabel,
                            paragraph: para,
                        });
                        return;
                    }
                    let val = '';
                    if (el.tagName === 'SELECT') val = el.value;
                    else if (t === 'radio') {
                        const group = el.name ? root.querySelectorAll(`input[name="${el.name}"]`) : [el];
                        if (Array.from(group).some(g => g.checked)) return;
                    } else val = el.value || '';
                    if (val && val.trim()) return;
                    let label = '';
                    if (el.id) {
                        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                        if (l) label = l.innerText;
                    }
                    if (!label) {
                        const wrap = el.closest('div.fb-dash-form-element, fieldset, .artdeco-form-item');
                        if (wrap) {
                            const l = wrap.querySelector('label, legend, .artdeco-text-input--label, .fb-dash-form-element__label');
                            if (l) label = l.innerText;
                        }
                    }
                    const isCombobox = (
                        el.getAttribute('role') === 'combobox' ||
                        el.hasAttribute('aria-autocomplete') ||
                        el.getAttribute('aria-haspopup') === 'listbox'
                    );
                    // For SELECT, harvest the option labels so second_pass can let the LLM
                    // pick from them (and trigger the human-loop with a real list to choose).
                    let selectOptions = [];
                    if (el.tagName === 'SELECT') {
                        const opts = el.querySelectorAll('option');
                        opts.forEach(o => {
                            const text = (o.innerText || o.value || '').trim();
                            if (!text) return;
                            // Drop placeholder rows ("Select an option", "-- choose --", etc.)
                            const low = text.toLowerCase();
                            if (low.startsWith('select') || low.startsWith('--')
                                || low === 'choisir' || low === 'choisir...'
                                || low === 'seleccione' || low.startsWith('seleccionar')
                                || low === 'wählen' || low === 'wahlen'
                                || low === 'scegli' || low === 'selecionar') return;
                            if (!selectOptions.includes(text)) selectOptions.push(text);
                        });
                    }
                    out.push({
                        tag: el.tagName,
                        type: t,
                        name: el.name || '',
                        id: el.id || '',
                        label: (label || '').trim().split('\\n')[0],
                        is_combobox: isCombobox,
                        options: selectOptions,
                    });
                });
                root.querySelectorAll('fieldset, div[role="radiogroup"]').forEach(g => {
                    const radios = g.querySelectorAll('input[type="radio"]');
                    if (!radios.length) return;
                    if (Array.from(radios).some(r => r.checked)) return;
                    let label = '';
                    const legend = g.querySelector('legend');
                    if (legend) label = legend.innerText;
                    if (!label) {
                        const ids = (g.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                        label = ids.map(id => { const n = document.getElementById(id); return n ? n.innerText : ''; }).join(' ');
                    }
                    const opts = [];
                    radios.forEach(r => {
                        let l = '';
                        if (r.id) { const x = document.querySelector('label[for="' + CSS.escape(r.id) + '"]'); if (x) l = x.innerText; }
                        if (!l) { const x = r.closest('label'); if (x) l = x.innerText; }
                        l = (l || '').trim().split('\\n')[0];
                        if (l && !opts.includes(l)) opts.push(l);
                    });
                    out.push({
                        tag: 'RADIOGROUP',
                        type: 'radio',
                        name: radios[0].name || '',
                        id: '',
                        label: (label || '').trim().split('\\n')[0],
                        options: opts,
                    });
                });
                return out;
            }"""
        ) or []
    except Exception as e:
        print(f"[2ndPass] scan error: {e}", flush=True)
        return

    if not empty:
        return
    print(f"[2ndPass] {len(empty)} field(s) still empty — retrying each individually", flush=True)
    for f in empty:
        try:
            label = f.get("label") or ""
            tag = f.get("tag") or ""
            ftype = (f.get("type") or "").lower()
            name = f.get("name") or ""
            elem_id = f.get("id") or ""
            options = f.get("options") or []

            if tag == "RADIOGROUP":
                kind = "radio"
            elif tag == "SELECT":
                kind = "select"
            elif tag == "TEXTAREA":
                kind = "textarea"
            elif tag == "CHECKBOX":
                kind = "checkbox"
            elif f.get("is_combobox"):
                kind = "combobox"
            else:
                kind = "text"

            print(f"[2ndPass] field tag={tag} type={ftype} name={name!r} label={label!r} options={options}", flush=True)
            # Required field that escaped the first pass — escalate to the human loop if needed.
            # Checkboxes need richer context: the visible label is often a single word ("Confirmé")
            # while the actual question lives in a sibling paragraph captured by the JS scan.
            resolve_label = label
            resolve_options = options or None
            if kind == "checkbox":
                paragraph = f.get("paragraph") or ""
                if _looks_like_consent(label, paragraph):
                    target_cb = None
                    if elem_id:
                        target_cb = scope.locator(f"#{elem_id}").first
                    elif name:
                        target_cb = scope.locator(f"input[type='checkbox'][name=\"{name}\"]").first
                    if target_cb is not None and _checkbox_is_present(target_cb, page):
                        if _check_checkbox(target_cb, page):
                            print("[2ndPass]   → checked (consent heuristic)", flush=True)
                        else:
                            print("[2ndPass]   check failed via every strategy", flush=True)
                    continue
                resolve_options = ["Yes", "No"]
                if paragraph and len(paragraph) > len(label):
                    resolve_label = paragraph + " — checkbox label: " + (label or "(unlabelled)")

            answer = _resolve_answer(resolve_label, resolve_options, kind, context, allow_human_loop=True)
            if not answer:
                print("[2ndPass]   no answer; leaving empty", flush=True)
                continue

            if kind == "radio":
                # Click the radio matching the answer.
                a_low = answer.strip().lower()
                clicked = False
                if name:
                    radios = scope.locator(f"input[type='radio'][name=\"{name}\"]").all()
                    for r in radios:
                        try:
                            r_id = r.get_attribute("id") or ""
                            r_label = ""
                            if r_id:
                                lbl = scope.locator(f"label[for=\"{r_id}\"]").first
                                if _visible(lbl):
                                    r_label = (lbl.inner_text() or "").strip().splitlines()[0].strip()
                            if not r_label:
                                continue
                            if r_label.lower() == a_low or a_low in r_label.lower() or r_label.lower().startswith(a_low):
                                lbl.click()
                                clicked = True
                                print(f"[2ndPass]   clicked radio label={r_label!r}", flush=True)
                                break
                        except Exception:
                            continue
                if not clicked:
                    print(f"[2ndPass]   could not match radio answer {answer!r} to any option for name={name!r}", flush=True)
                continue

            if kind == "select":
                if not (name or elem_id):
                    continue
                sel_loc = scope.locator(f"select#{elem_id}" if elem_id else f"select[name=\"{name}\"]").first
                if not _visible(sel_loc):
                    continue
                try:
                    sel_loc.select_option(label=answer)
                    print(f"[2ndPass]   selected {answer!r}", flush=True)
                except Exception as e:
                    print(f"[2ndPass]   select failed: {e}", flush=True)
                continue

            if kind == "checkbox":
                target_cb = scope.locator(f"#{elem_id}").first if elem_id else (
                    scope.locator(f"input[type='checkbox'][name=\"{name}\"]").first if name else None
                )
                if target_cb is None or not _checkbox_is_present(target_cb, page):
                    print(f"[2ndPass]   could not locate checkbox", flush=True)
                    continue
                ans_low = (answer or "").strip().lower()
                yes_tokens = ("yes", "true", "1", "oui", "sí", "si", "ja", "check", "checked", "agree", "confirm")
                if ans_low in yes_tokens or any(ans_low.startswith(t) for t in yes_tokens):
                    if _check_checkbox(target_cb, page):
                        print(f"[2ndPass]   → checked (resolver: {answer!r})", flush=True)
                    else:
                        print("[2ndPass]   check failed via every strategy", flush=True)
                else:
                    print(f"[2ndPass]   answer {answer!r} → leaving unchecked", flush=True)
                continue

            if kind == "combobox":
                # Typeahead-aware fill: real keystrokes + click first listbox option.
                box = None
                if elem_id:
                    try:
                        box = scope.locator(f"#{elem_id}").first
                        if not _visible(box):
                            box = None
                    except Exception:
                        box = None
                if box is None and name:
                    try:
                        box = scope.locator(f"[name=\"{name}\"]").first
                        if not _visible(box):
                            box = None
                    except Exception:
                        box = None
                if box is None:
                    print("[2ndPass]   could not locate combobox again", flush=True)
                    continue
                try:
                    box.click()
                    random_sleep(0, 1)
                    try:
                        box.fill("")
                    except Exception:
                        pass
                    box.press_sequentially(answer, delay=40)
                    if _wait_for_listbox_option(scope, page, timeout_ms=2500):
                        option = _first_listbox_option(scope, page, answer)
                        if option is not None:
                            try:
                                option.click()
                                print(f"[2ndPass]   picked typeahead option for {label!r}", flush=True)
                                random_sleep(0, 1)
                            except Exception:
                                box.press("Enter")
                        else:
                            box.press("Enter")
                    else:
                        box.press("Enter")
                        print(f"[2ndPass]   no listbox for {label!r}; pressed Enter", flush=True)
                except Exception as exc:
                    print(f"[2ndPass]   combobox fill failed for {label!r}: {exc}", flush=True)
                continue

            # text / textarea
            target = None
            if elem_id:
                try:
                    target = scope.locator(f"#{elem_id}").first
                    if not _visible(target):
                        target = None
                except Exception:
                    target = None
            if target is None and name:
                try:
                    target = scope.locator(f"[name=\"{name}\"]").first
                    if not _visible(target):
                        target = None
                except Exception:
                    target = None
            if target is None:
                print("[2ndPass]   could not locate the field again", flush=True)
                continue
            try:
                target.fill(answer)
                print(f"[2ndPass]   filled with {answer[:60]!r}", flush=True)
            except Exception as e:
                print(f"[2ndPass]   fill failed: {e}", flush=True)
        except Exception as e:
            print(f"[2ndPass] field error: {e}", flush=True)
            continue


def _audit_required_fields(page: Page) -> None:
    """Log every required field still empty after autofill — pinpoints what we're missing."""
    scope = _modal_scope(page)
    try:
        empty_required = scope.evaluate(
            """root => {
                const out = [];
                const fields = root.querySelectorAll('input, textarea, select');
                fields.forEach(el => {
                    const required = el.required || el.getAttribute('aria-required') === 'true';
                    if (!required) return;
                    if (el.type === 'hidden' || el.type === 'file' || el.disabled) return;
                    let value = '';
                    if (el.tagName === 'SELECT') value = el.value;
                    else if (el.type === 'radio' || el.type === 'checkbox') {
                        const group = el.name ? root.querySelectorAll(`input[name="${el.name}"]`) : [el];
                        const anyChecked = Array.from(group).some(g => g.checked);
                        if (anyChecked) return;
                        value = '';
                    } else value = el.value || '';
                    if (value && value.trim()) return;
                    let label = '';
                    if (el.id) {
                        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                        if (l) label = l.innerText;
                    }
                    if (!label) {
                        const wrap = el.closest('div.fb-dash-form-element, fieldset, .artdeco-form-item');
                        if (wrap) {
                            const l = wrap.querySelector('label, legend, .artdeco-text-input--label, .fb-dash-form-element__label');
                            if (l) label = l.innerText;
                        }
                    }
                    out.push({tag: el.tagName, type: el.type || '', name: el.name || '', label: (label || '').trim().split('\\n')[0]});
                });
                // Also catch radio groups that have nothing checked.
                const groups = root.querySelectorAll('fieldset, div[role="radiogroup"]');
                groups.forEach(g => {
                    const radios = g.querySelectorAll('input[type="radio"]');
                    if (!radios.length) return;
                    const checked = Array.from(radios).some(r => r.checked);
                    if (checked) return;
                    let label = '';
                    const legend = g.querySelector('legend');
                    if (legend) label = legend.innerText;
                    if (!label) {
                        const ids = (g.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                        label = ids.map(id => { const n = document.getElementById(id); return n ? n.innerText : ''; }).join(' ');
                    }
                    out.push({tag: 'RADIOGROUP', type: 'radio', name: radios[0].name || '', label: (label || '').trim().split('\\n')[0]});
                });
                return out;
            }"""
        )
    except Exception as e:
        print(f"[Audit] error: {e}", flush=True)
        return
    if not empty_required:
        print("[Audit] All required fields are filled.", flush=True)
        return
    print(f"[Audit] {len(empty_required)} required field(s) STILL EMPTY after autofill:", flush=True)
    for f in empty_required:
        print(f"  • <{f['tag']} type={f['type']!r} name={f['name']!r}> label={f['label']!r}", flush=True)


def _dump_modal_html(page: Page, tag: str = "modal") -> str | None:
    """Save the modal HTML to state/errors/ for diagnostic purposes. Returns the path or None."""
    try:
        from datetime import datetime
        scope = _modal_scope(page)
        html = scope.evaluate("el => el.outerHTML")
        if not html:
            return None
        errors_dir = os.path.join(os.path.dirname(__file__), "..", "state", "errors")
        os.makedirs(errors_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(errors_dir, f"{tag}-{stamp}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(html))
        print(f"[Dump] modal HTML saved → {path}", flush=True)
        return path
    except Exception as e:
        print(f"[Dump] failed: {e}", flush=True)
        return None


_COVER_LETTER_PHRASES = (
    "cover letter", "covering letter", "motivation letter",
    "lettre de motivation", "lettre d'accompagnement", "lettre d accompagnement",
    "carta de presentación", "carta de presentacion", "carta de motivación", "carta de motivacion",
    "anschreiben", "motivationsschreiben",
    "lettera di motivazione", "lettera di presentazione",
    "carta de apresentação", "carta de apresentacao", "carta de motivação", "carta de motivacao",
)


def _file_input_label(field) -> str:
    """Best-effort label/context for a (usually hidden) file input. Tries aria-label,
    `<label for>`, then walks up the DOM picking the nearest text node."""
    try:
        aria = (field.get_attribute("aria-label") or "").strip()
        if aria:
            return aria
    except Exception:
        pass
    try:
        fid = field.get_attribute("id") or ""
        if fid:
            lbl = field.page.locator(f"label[for=\"{fid}\"]").first
            try:
                if lbl.count():
                    txt = ((lbl.inner_text() or "").strip().splitlines() or [""])[0]
                    if txt:
                        return txt
            except Exception:
                pass
    except Exception:
        pass
    try:
        ctx = field.evaluate(
            """el => {
                let node = el;
                for (let d = 0; d < 6 && node; d++) {
                    const parent = node.parentElement;
                    if (!parent) break;
                    const t = (parent.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (t && t.length >= 4 && t.length <= 200) return t;
                    node = parent;
                }
                return '';
            }"""
        ) or ""
        return ctx.strip()
    except Exception:
        return ""


def _is_cover_letter_field(label_text: str) -> bool:
    if not label_text:
        return False
    low = label_text.lower()
    return any(p in low for p in _COVER_LETTER_PHRASES)


def _is_resume_field(label_text: str) -> bool:
    """Heuristic for explicit resume slots — defaults to True for unlabeled file inputs
    so legacy single-upload forms still receive the resume."""
    if not label_text:
        return True
    low = label_text.lower()
    return any(k in low for k in (
        "resume", "résumé", "resumé", "cv", "curriculum",
        "lebenslauf",   # DE
        "currículum", "curriculum vitae",  # ES
        "currículo",    # PT
    ))


def handle_resume_upload(page: Page, job: dict | None = None, llm_model: str | None = None) -> None:
    """Process every file-upload slot in the modal.

    For each visible `<input type=file>`:
      * if its label mentions cover/motivation letter → generate a tailored PDF via
        tools.cover_letter and upload that (kept in /cover-letters/),
      * otherwise → upload the resume PDF as before.

    Backward-compatible: with no `job`/`llm_model` args, only the resume is uploaded."""
    try:
        inputs = _modal_scope(page).locator("input[type='file']").all()
    except Exception as exc:
        print(f"[Apply] file inputs lookup failed: {exc}", flush=True)
        return
    if not inputs:
        return

    resume_path = _resume_path()
    cover_path_cache: str | None = None  # generate at most once per modal step

    for upload in inputs:
        try:
            label = _file_input_label(upload)
            print(f"[Upload] field label/context={label[:140]!r}", flush=True)
            chose_cover = _is_cover_letter_field(label) and job is not None

            if chose_cover:
                if cover_path_cache is None:
                    try:
                        from tools import cover_letter as _cl
                        cover_path_cache = _cl.make_for_job(job or {}, llm_model)
                    except Exception as exc:
                        print(f"[Upload] cover-letter generation failed: {exc}", flush=True)
                if cover_path_cache:
                    try:
                        upload.set_input_files(cover_path_cache)
                        random_sleep(2, 3)
                        print(f"[Upload] cover letter PDF uploaded for label={label[:60]!r}", flush=True)
                        continue
                    except Exception as exc:
                        print(f"[Upload] cover-letter file set failed: {exc} — falling back to resume", flush=True)

            # Resume slot (explicit or unlabeled fallback).
            if not resume_path:
                continue
            try:
                upload.set_input_files(resume_path)
                random_sleep(2, 3)
            except Exception as exc:
                print(f"[Upload] resume set_input_files failed: {exc}", flush=True)
        except Exception as exc:
            print(f"[Upload] iteration error: {exc}", flush=True)
            continue


_EASY_APPLY_LABELS = (
    "Easy Apply",
    "Candidature simplifiée", "Candidature simplifiee",
    "Postulación sencilla", "Postulacion sencilla",
    "Sofortbewerbung",
    "Candidatura semplice",
    "Solicitação simplificada", "Solicitacao simplificada",
)
_SUBMIT_LABELS = (
    "Submit application", "Submit",
    "Envoyer la candidature", "Soumettre la candidature", "Envoyer", "Soumettre",
    "Enviar solicitud", "Enviar candidatura", "Enviar",
    "Bewerbung absenden", "Absenden", "Senden",
    "Invia candidatura", "Invia",
    "Enviar inscrição", "Enviar inscricao",
)
_NEXT_LABELS = ("Next", "Continue", "Suivant", "Continuer", "Siguiente", "Continuar", "Weiter", "Avanti", "Próximo", "Proximo", "Próximo passo")
_REVIEW_LABELS = ("Review", "Review your application", "Vérifier", "Verifier", "Vérifier votre candidature", "Revisar", "Revisar candidatura", "Überprüfen", "Uberprufen", "Rivedi", "Rivedi candidatura")
_DISMISS_LABELS = ("Dismiss", "Ignorer", "Fermer", "Descartar", "Cerrar", "Schließen", "Schliessen", "Chiudi")
_DISCARD_LABELS = ("Discard", "Abandonner", "Supprimer", "Descartar", "Verwerfen", "Scarta")
# LinkedIn shows this kind of message when you've hit their daily submission cap. Detecting
# it lets us stop the agent — continuing burns time and risks an account flag.
_DAILY_LIMIT_PHRASES = (
    # EN
    "we limit daily submissions",
    "limit daily submissions",
    "save this job and apply tomorrow",
    "daily application limit",
    "you've reached the daily limit",
    "you have reached the daily limit",
    "you've reached your daily limit",
    "reached the daily application limit",
    # FR
    "nous limitons les candidatures quotidiennes",
    "limite quotidienne",
    "revenez demain",
    "candidatures quotidiennes",
    # ES
    "límite diario de solicitudes",
    "limite diario",
    "vuelve mañana",
    # DE
    "tägliches bewerbungslimit",
    "tagesbewerbungslimit",
    # IT
    "limite giornaliero di candidature",
    # PT
    "limite diário de candidaturas",
)


def _detect_daily_limit(scope_or_page) -> bool:
    """True if the page/modal shows LinkedIn's daily-submission-limit message."""
    try:
        text = (scope_or_page.locator("body").inner_text(timeout=600) or "").lower()
    except Exception:
        try:
            text = (scope_or_page.inner_text(timeout=600) or "").lower()
        except Exception:
            return False
    return any(p in text for p in _DAILY_LIMIT_PHRASES)


_EXTERNAL_APPLY_HINTS = (
    "continue applying", "continue on company", "company website", "external site",
    "continuer la candidature", "site de l'entreprise", "site externe",
    "continuar en el sitio", "sitio web de la empresa", "sitio externo",
    "auf der unternehmenswebsite", "externe website", "weiter zur bewerbung",
    "continua sul sito", "sito esterno", "sito dell'azienda",
)


def _detect_external_apply(page: Page, original_url: str) -> tuple[bool, str, dict]:
    """Returns (is_external, signal, meta) — meta has 'destination_url' and 'destination_title' when found."""
    meta: dict = {}
    try:
        current_url = page.url or ""
    except Exception:
        current_url = ""
    if current_url and "linkedin.com" not in current_url:
        meta["destination_url"] = current_url
        try:
            meta["destination_title"] = page.title() or ""
        except Exception:
            pass
        return True, f"url_left_linkedin (now {current_url[:120]})", meta
    # Look for an "open in new tab" link styled as the next step.
    try:
        ext_link = page.locator(
            "a[target='_blank']:not([href*='linkedin.com']):not([href^='/'])"
        ).first
        if _visible(ext_link):
            href = ext_link.get_attribute("href") or ""
            text = (ext_link.inner_text() or "").strip()[:60]
            if href:
                meta["destination_url"] = href
                meta["destination_title"] = text
            return True, f"external_link ({text or href[:80]!r})", meta
    except Exception:
        pass
    # Look for the "Continue applying on company website" interstitial.
    try:
        body_text = (page.locator("body").inner_text(timeout=1000) or "").lower()
    except Exception:
        body_text = ""
    for hint in _EXTERNAL_APPLY_HINTS:
        if hint in body_text:
            return True, f"prompt_text ({hint!r})", meta
    return False, "", meta


def _find_modal(page: Page):
    """Return the Easy Apply modal Locator if currently open, else None."""
    for sel in _MODAL_SELECTORS:
        loc = page.locator(sel).first
        if _visible(loc):
            return loc
    # Generic fallback: any visible dialog containing Easy-Apply specific content
    for dialog in page.locator("div[role='dialog']").all():
        try:
            if not _visible(dialog):
                continue
            marker = dialog.locator(
                "button[data-easy-apply-next-button], "
                "button[data-easy-apply-submit-button], "
                ".jobs-easy-apply-content, "
                ".jobs-easy-apply-form-section__group"
            ).first
            if _visible(marker):
                return dialog
        except Exception:
            continue
    return None


def _modal_scope(page: Page):
    """Backward-compat helper for autofill: returns modal or page (last resort)."""
    return _find_modal(page) or page


def _button_in(scope, labels):
    """Find a button by accessible name inside the given scope (modal or page)."""
    for name in labels:
        try:
            loc = scope.get_by_role("button", name=name, exact=True).first
            if _visible(loc): return loc
            loc = scope.get_by_role("button", name=name).first
            if _visible(loc): return loc
            loc = scope.locator(f'button:has-text("{name}")').first
            if _visible(loc): return loc
            loc = scope.locator(f'button[aria-label*="{name}" i]').first
            if _visible(loc): return loc
        except Exception:
            continue
    return None


def _has_validation_error(scope) -> bool:
    try:
        err = scope.locator(
            ".artdeco-inline-feedback--error, "
            "[aria-invalid='true'], "
            ".fb-dash-form-element__error-field"
        ).first
        return _visible(err)
    except Exception:
        return False


def _collect_field_errors(scope) -> list[dict]:
    """Pair each visible validation error with its associated field so the LLM can revise.

    Returns a list of dicts: {label, error_text, field, kind, current_value, options, max_chars}.
    Only includes fields the bot can interact with again (text / textarea / select / radio)."""
    out: list[dict] = []
    try:
        error_nodes = scope.locator(
            ".artdeco-inline-feedback--error, .fb-dash-form-element__error-field"
        ).all()
    except Exception:
        return out
    seen_error_ids: set[int] = set()
    for node in error_nodes:
        try:
            if not _visible(node):
                continue
            try:
                key = id(node)
                if key in seen_error_ids:
                    continue
                seen_error_ids.add(key)
            except Exception:
                pass
            error_text = ((node.inner_text() or "").strip().splitlines() or [""])[0].strip()
            if not error_text:
                continue
            # Walk to the enclosing form-element wrapper.
            try:
                wrap = node.locator(
                    "xpath=ancestor::*[contains(@class,'fb-dash-form-element') or "
                    "contains(@class,'artdeco-form-item') or self::fieldset][1]"
                ).first
                if not _visible(wrap):
                    continue
            except Exception:
                continue
            # Find the field's label inside the wrapper.
            label_text = ""
            for lbl_sel in ("legend", "label", ".artdeco-text-input--label", ".fb-dash-form-element__label"):
                try:
                    lbl = wrap.locator(lbl_sel).first
                    if _visible(lbl):
                        label_text = ((lbl.inner_text() or "").strip().splitlines() or [""])[0].strip()
                        if label_text:
                            break
                except Exception:
                    continue
            # Find the field. Order matters — prefer specific types over a bare <input>.
            field = None
            kind = "text"
            for sel, k in (
                ("select", "select"),
                ("textarea", "textarea"),
                ("input[type='radio']", "radio"),
                ("input[type='checkbox']", "checkbox"),
                ("input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='button'])", "text"),
            ):
                try:
                    candidate = wrap.locator(sel).first
                    if candidate.count() and _visible(candidate):
                        field = candidate
                        kind = k
                        break
                except Exception:
                    continue
            if field is None:
                continue
            # Current value.
            current = ""
            try:
                if kind in ("text", "textarea"):
                    current = (field.input_value() or "").strip()
                elif kind == "select":
                    current = (field.evaluate("el => (el.options[el.selectedIndex] || {}).text || ''") or "").strip()
            except Exception:
                pass
            # Options (for select / radio group).
            opts: list[str] = []
            if kind == "select":
                try:
                    for o in field.locator("option").all():
                        try:
                            t = (o.inner_text() or "").strip()
                        except Exception:
                            t = ""
                        if t and not _is_placeholder_text(t):
                            opts.append(t)
                except Exception:
                    pass
            elif kind == "radio":
                try:
                    for lbl in wrap.locator("label").all():
                        try:
                            if not _visible(lbl):
                                continue
                            t = ((lbl.inner_text() or "").strip().splitlines() or [""])[0].strip()
                            if t and t not in opts:
                                opts.append(t)
                        except Exception:
                            continue
                except Exception:
                    pass
            # Char budget (textarea).
            max_chars = None
            if kind == "textarea":
                try:
                    ml = field.evaluate("el => el.maxLength")
                    if isinstance(ml, int) and ml > 0:
                        max_chars = ml
                except Exception:
                    pass
            out.append({
                "label": label_text or "(unlabeled field)",
                "error_text": error_text,
                "field": field,
                "wrap": wrap,
                "kind": kind,
                "current_value": current,
                "options": opts,
                "max_chars": max_chars,
            })
        except Exception:
            continue
    return out


def _apply_revised_value(ef: dict, new_answer: str, page: Page) -> bool:
    """Write the revised value back into the original field. Returns success."""
    field = ef["field"]
    kind = ef["kind"]
    try:
        if kind in ("text", "textarea"):
            try:
                field.fill(new_answer)
                return True
            except Exception:
                try:
                    field.click()
                    field.press("Control+A")
                    field.press("Delete")
                    field.type(new_answer, delay=20)
                    return True
                except Exception as exc:
                    print(f"[Revise]   text fill fallback failed: {exc}", flush=True)
                    return False
        if kind == "select":
            try:
                field.select_option(label=new_answer)
                return True
            except Exception:
                try:
                    field.select_option(new_answer)
                    return True
                except Exception as exc:
                    print(f"[Revise]   select fallback failed: {exc}", flush=True)
                    return False
        if kind == "radio":
            wrap = ef["wrap"]
            a_low = new_answer.strip().lower()
            try:
                for lbl in wrap.locator("label").all():
                    try:
                        if not _visible(lbl):
                            continue
                        t = ((lbl.inner_text() or "").strip().splitlines() or [""])[0].lower()
                        if not t:
                            continue
                        if t == a_low or a_low in t or t.startswith(a_low):
                            lbl.click()
                            return True
                    except Exception:
                        continue
            except Exception:
                pass
            return False
    except Exception as exc:
        print(f"[Revise]   apply failed: {exc}", flush=True)
    return False


def _retry_on_validation_errors(scope, page: Page, context: dict | None) -> int:
    """Read every field-level validation error, ask the LLM to revise each based on the
    validator's complaint, and write the new values back. Returns the count revised."""
    errors = _collect_field_errors(scope)
    if not errors:
        return 0
    ctx = context or {}
    llm_model = ctx.get("llm_model")
    job_details = (ctx.get("job_details") or {}) if isinstance(ctx, dict) else {}
    job_ctx = {
        "title": (job_details.get("title") or "")[:120],
        "company": (job_details.get("company") or "")[:120],
        "description": (job_details.get("description") or "")[:600],
    }
    revised = 0
    for ef in errors:
        try:
            print(
                f"[Revise] field={ef['label']!r} kind={ef['kind']} error={ef['error_text']!r} "
                f"previous={ef['current_value']!r}",
                flush=True,
            )
            new_answer = llm_revise_answer(
                label=ef["label"],
                validation_error=ef["error_text"],
                previous_answer=ef["current_value"],
                kind=ef["kind"],
                llm_model=llm_model,
                job_context=job_ctx,
                max_chars=ef.get("max_chars"),
                options=ef.get("options") or None,
            )
            if not new_answer:
                print(f"[Revise]   LLM gave no revision for {ef['label']!r}", flush=True)
                continue
            if _apply_revised_value(ef, new_answer, page):
                revised += 1
                print(f"[Revise]   ✓ wrote {new_answer!r} into {ef['label']!r}", flush=True)
            else:
                print(f"[Revise]   ✗ could not write revised value into {ef['label']!r}", flush=True)
        except Exception as exc:
            print(f"[Revise] iteration error: {exc}", flush=True)
            continue
    return revised


def _collect_validation_messages(scope) -> list[str]:
    """Return up to 3 visible validation error messages with their associated field label."""
    msgs: list[str] = []
    try:
        nodes = scope.locator(
            ".artdeco-inline-feedback--error .artdeco-inline-feedback__message, "
            ".fb-dash-form-element__error-field, "
            "[aria-invalid='true']"
        ).all()
    except Exception:
        nodes = []
    seen: set[str] = set()
    for node in nodes:
        try:
            if not _visible(node):
                continue
            text = (node.inner_text() or "").strip()
            if not text and node.get_attribute("aria-invalid") == "true":
                # Field marked invalid but no message — fall back to its label.
                label = _label_text(node)
                text = f"required: {label}" if label else "required field"
            if not text or text in seen:
                continue
            # Try to find the related field's label for context.
            label = ""
            try:
                wrap_label = node.evaluate(
                    """el => {
                        const wrap = el.closest('div.fb-dash-form-element, .jobs-easy-apply-form-element, fieldset, .artdeco-form-item');
                        if (!wrap) return '';
                        const l = wrap.querySelector('label, legend, .artdeco-text-input--label, .fb-dash-form-element__label');
                        return l ? l.innerText : '';
                    }"""
                )
                label = (wrap_label or "").strip().splitlines()[0] if wrap_label else ""
            except Exception:
                pass
            entry = f"{label} → {text}" if label else text
            seen.add(text)
            msgs.append(entry)
            if len(msgs) >= 3:
                break
        except Exception:
            continue
    return msgs


def _modal_dom_size(scope) -> int:
    """Total element count in the modal — used to detect 'Next click did nothing'."""
    try:
        return int(scope.evaluate("el => el.querySelectorAll('*').length") or 0)
    except Exception:
        return 0


def _modal_button_texts(scope, limit: int = 8) -> list[str]:
    """Visible button labels in the modal — debug stuck_unknown_form / validation_loop."""
    out: list[str] = []
    seen: set[str] = set()
    try:
        btns = scope.locator("button").all()
    except Exception:
        return out
    for b in btns:
        try:
            if not _visible(b):
                continue
            txt = ((b.inner_text() or "").strip().splitlines() or [""])[0]
            if not txt:
                txt = (b.get_attribute("aria-label") or "").strip()
            if not txt or txt in seen:
                continue
            seen.add(txt)
            out.append(txt)
            if len(out) >= limit:
                break
        except Exception:
            continue
    return out


def _visible_field_labels(scope, limit: int = 5) -> list[str]:
    """List visible field labels in the current modal step — useful for debugging stuck_unknown_form."""
    labels: list[str] = []
    seen: set[str] = set()
    try:
        nodes = scope.locator(
            "label, legend, .artdeco-text-input--label, .fb-dash-form-element__label"
        ).all()
    except Exception:
        return labels
    for node in nodes:
        try:
            if not _visible(node):
                continue
            text = (node.inner_text() or "").strip().splitlines()[0]
            if not text or text in seen:
                continue
            seen.add(text)
            labels.append(text)
            if len(labels) >= limit:
                break
        except Exception:
            continue
    return labels


def _step_signature(scope, page: Page) -> tuple[str, str]:
    """Per-step identity. Combines the progress-bar value with the section heading.

    The first <h2> in the modal is the JOB title ("Apply to Coface") — constant across
    every step of an Easy Apply, so it cannot be used as the only discriminator. The
    `<progress max="100" value="N">` element advances every step on the standard
    LinkedIn form; we prefer it. The <h3> section heading ("Education", "Work
    experience", ...) is the next best signal. <h2> is only used as a last resort."""
    progress = ""
    try:
        p = scope.locator("progress[max='100']").first
        if _visible(p):
            progress = p.get_attribute("value") or ""
    except Exception:
        pass
    heading = ""
    try:
        h3 = scope.locator("h3").first
        if _visible(h3):
            heading = ((h3.inner_text(timeout=300) or "").strip().splitlines() or [""])[0]
    except Exception:
        pass
    if not heading:
        try:
            h2 = scope.locator("h2").first
            if _visible(h2):
                heading = ((h2.inner_text(timeout=300) or "").strip().splitlines() or [""])[0]
        except Exception:
            pass
    return (page.url, f"progress={progress}|h={heading}")


def _saw_confirmation(page: Page) -> bool:
    """After Submit, LinkedIn shows either a 'application sent' dialog or closes the modal."""
    try:
        body_text = (page.locator("body").inner_text(timeout=1000) or "").lower()
    except Exception:
        body_text = ""
    return any(term in body_text for term in _CONFIRMATION_TERMS)


def _looks_like_save(button) -> bool:
    """Multi-locale check that a button is the Save button, not Easy Apply."""
    try:
        aria = (button.get_attribute("aria-label") or "").lower()
        text = (button.inner_text() or "").lower()
        haystack = f"{aria} {text}"
        return any(term in haystack for term in _SAVE_ARIA_TERMS)
    except Exception:
        return False


def _find_easy_apply_button(page: Page):
    """Try several locator strategies across locales/markup variants."""
    selectors = [
        "button[data-control-name='jobdetails_topcard_inapply']",
        "button.jobs-apply-button",
    ]
    for sel in selectors:
        for btn in page.locator(sel).all():
            try:
                if not _visible(btn):
                    continue
                if _looks_like_save(btn):
                    continue
                return btn
            except Exception:
                continue
    # Text-based fallbacks across locales (exact label match in our list)
    for label in _EASY_APPLY_LABELS:
        for finder in (
            lambda lbl=label: page.get_by_role("button", name=lbl).first,
            lambda lbl=label: page.locator(f"button:has-text(\"{lbl}\")").first,
            lambda lbl=label: page.locator(f"button[aria-label*=\"{lbl}\" i]").first,
        ):
            try:
                loc = finder()
                if _visible(loc) and not _looks_like_save(loc):
                    return loc
            except Exception:
                continue
    return None


def _wait_for_modal(page: Page, timeout_ms: int = 6000):
    """Poll for the Easy Apply modal to appear after clicking the apply button."""
    import time as _time
    deadline = _time.time() + (timeout_ms / 1000)
    while _time.time() < deadline:
        modal = _find_modal(page)
        if modal is not None:
            return modal
        _time.sleep(0.25)
    return None


def apply_easy_apply(page: Page, job_details: dict | None = None, llm_model: str | None = None) -> tuple[bool, str]:
    """Returns (success, reason). reason is empty on success, else a short tag."""
    context = {"job_details": job_details or {}, "llm_model": llm_model}
    try:
        # Pre-click: LinkedIn sometimes shows the daily-limit message on the job page itself
        # (replacing the Easy Apply button or as a banner). Catch it before we even click.
        if _detect_daily_limit(page):
            return False, "daily_limit_reached"

        easy_apply_btn = _find_easy_apply_button(page)
        if easy_apply_btn is None:
            return False, "no_easy_apply_button"

        try:
            easy_apply_btn.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            original_url = page.url or ""
        except Exception:
            original_url = ""
        easy_apply_btn.click()
        random_sleep(2, 4)

        modal = _wait_for_modal(page, timeout_ms=6000)
        # Post-click: limit message may appear inside the modal that opened, or on the page
        # in lieu of the modal opening at all.
        if _detect_daily_limit(page) or (modal is not None and _detect_daily_limit(modal)):
            return False, "daily_limit_reached"
        if modal is None:
            # Distinguish external ATS / company-site redirect from a genuinely stuck modal.
            is_external, signal, meta = _detect_external_apply(page, original_url)
            if is_external:
                dest = meta.get("destination_url") or ""
                title = meta.get("destination_title") or ""
                tail = f" | dest={dest[:120]}" if dest else ""
                tail += f" | title={title[:80]!r}" if title else ""
                print(f"[Apply] External ATS detected after Easy Apply click: {signal}{tail}", flush=True)
                reason = f"external_apply ({signal})"
                if dest:
                    reason += f" → {dest}"
                return False, reason
            print("[Apply] Easy Apply clicked but modal did not open within 6s", flush=True)
            return False, "modal_did_not_open"

        last_sig: tuple[str, str] = ("", "")
        same_sig_count = 0
        for step in range(MAX_APPLY_STEPS):
            _run_checkpoint(f"apply_step_{step}")
            # Re-resolve the modal each iteration (DOM may have replaced it).
            modal = _find_modal(page)
            if modal is None:
                # Modal closed unexpectedly. Could mean Submit succeeded or user-side dismissal.
                if _saw_confirmation(page):
                    print(f"[Apply] Modal closed at step {step}; confirmation detected. Treating as success.", flush=True)
                    return True, ""
                print(f"[Apply] Modal disappeared at step {step} with no confirmation.", flush=True)
                return False, "modal_closed_no_confirmation"

            _autofill_step(page, context)

            submit_btn = _button_in(modal, _SUBMIT_LABELS)
            if submit_btn is not None:
                submit_label = ""
                try:
                    submit_label = (submit_btn.inner_text() or submit_btn.get_attribute("aria-label") or "").strip()
                except Exception:
                    pass
                submit_btn.click()
                random_sleep(3, 5)
                # Verify submission: modal closed OR confirmation visible.
                post_modal = _find_modal(page)
                if post_modal is None or _saw_confirmation(page):
                    dismiss_btn = _button_in(page, _DISMISS_LABELS)
                    if dismiss_btn is not None:
                        try:
                            dismiss_btn.click()
                        except Exception:
                            pass
                    print(f"[Apply] Submit clicked at step {step}; confirmation OK.", flush=True)
                    return True, ""
                heading = _step_signature(modal, page)[1]
                detail = f"step={step} heading={heading!r} clicked={submit_label!r}"
                print(f"[Apply] Submit clicked but no confirmation. {detail}", flush=True)
                return False, f"submit_no_confirmation ({detail})"

            sig = _step_signature(modal, page)

            advance_btn = _button_in(modal, _NEXT_LABELS) or _button_in(modal, _REVIEW_LABELS)
            if advance_btn is None:
                visible_labels = _visible_field_labels(modal)
                _dump_modal_html(page, tag="stuck")
                close_btn = _button_in(modal, _DISMISS_LABELS)
                if close_btn is not None:
                    try:
                        close_btn.click()
                        random_sleep(1, 2)
                        confirm = _button_in(page, _DISCARD_LABELS)
                        if confirm is not None:
                            confirm.click()
                    except Exception:
                        pass
                fields_str = "; ".join(visible_labels) if visible_labels else "no labelled fields"
                detail = f"step={step} heading={sig[1]!r} fields=[{fields_str}]"
                print(f"[Apply] Stuck: no Submit/Next/Review. {detail}", flush=True)
                return False, f"stuck_unknown_form ({detail})"

            dom_size_before = _modal_dom_size(modal)
            advance_btn.click()
            random_sleep(2, 4)

            # Refresh modal handle and check for validation error inside it.
            modal_after = _find_modal(page)
            if modal_after is not None and _has_validation_error(modal_after):
                # ── Self-correction loop ─────────────────────────────────────
                # For each invalid field, feed (label, error_text, previous_answer) back to
                # the LLM and ask for a revised value. Re-click the same advance button.
                # Bounded retries to avoid infinite loops.
                MAX_VALIDATION_RETRIES = 2
                cleared = False
                for retry_n in range(MAX_VALIDATION_RETRIES):
                    revised = _retry_on_validation_errors(modal_after, page, context)
                    if revised == 0:
                        print(f"[Apply] No fields revised on retry {retry_n+1}; giving up.", flush=True)
                        break
                    print(
                        f"[Apply] Validation retry {retry_n+1}/{MAX_VALIDATION_RETRIES}: "
                        f"revised {revised} field(s); re-clicking advance.",
                        flush=True,
                    )
                    random_sleep(1, 2)
                    retry_btn = (
                        _button_in(modal_after, _NEXT_LABELS)
                        or _button_in(modal_after, _REVIEW_LABELS)
                        or _button_in(modal_after, _SUBMIT_LABELS)
                    )
                    if retry_btn is None:
                        print("[Apply] No advance button found after revision; giving up.", flush=True)
                        break
                    try:
                        retry_btn.click()
                    except Exception as exc:
                        print(f"[Apply] retry click failed: {exc}", flush=True)
                        break
                    random_sleep(2, 4)
                    modal_after = _find_modal(page)
                    if modal_after is None:
                        # Either modal closed (success) or page navigated.
                        if _saw_confirmation(page):
                            print(f"[Apply] Modal closed after self-correction at step {step}; confirmation detected.", flush=True)
                            return True, ""
                        cleared = True  # let the outer loop's next iteration decide
                        break
                    if not _has_validation_error(modal_after):
                        print(f"[Apply] Self-correction cleared the validation error at step {step}.", flush=True)
                        cleared = True
                        break
                if cleared:
                    # Advance happened (or modal closed) — let the outer step loop iterate.
                    continue
                # Retries exhausted — fail with the latest details.
                msgs = _collect_validation_messages(modal_after) if modal_after is not None else []
                joined = "; ".join(msgs) if msgs else "unspecified field error"
                _dump_modal_html(page, tag="validation")
                detail = f"step={step} heading={sig[1]!r} errors=[{joined}] (after {MAX_VALIDATION_RETRIES} self-correction retries)"
                print(f"[Apply] Validation error after retries. {detail}", flush=True)
                return False, f"validation_error ({detail})"

            # Compute the post-click DOM size once — used both for the safety net and diagnostics.
            dom_size_after = _modal_dom_size(modal_after) if modal_after is not None else 0
            dom_delta = abs(dom_size_after - dom_size_before)

            if sig == last_sig and dom_delta < 8:
                same_sig_count += 1
                if same_sig_count >= 2:
                    # Unconditional diagnostics — covers silent rejections and clicks that didn't register.
                    _dump_modal_html(page, tag="validation_loop")
                    msgs = _collect_validation_messages(modal_after) if modal_after is not None else []
                    buttons = _modal_button_texts(modal_after) if modal_after is not None else []
                    try:
                        cur_url = page.url or ""
                    except Exception:
                        cur_url = ""
                    detail = (
                        f"step={step} heading={sig[1]!r} url={cur_url[:120]!r} "
                        f"dom={dom_size_before}→{dom_size_after} "
                        f"msgs=[{'; '.join(msgs) or 'none'}] "
                        f"buttons={buttons}"
                    )
                    print(f"[Apply] Stuck on same step. {detail}", flush=True)
                    return False, f"validation_loop ({detail})"
            else:
                # Either signature changed OR DOM moved enough to prove we advanced.
                if sig == last_sig and dom_delta >= 8:
                    print(f"[Apply] Step advanced despite identical sig (dom {dom_size_before}→{dom_size_after}).", flush=True)
                same_sig_count = 0
            last_sig = sig

        detail = f"steps={MAX_APPLY_STEPS} last_heading={last_sig[1]!r}"
        print(f"[Apply] max_steps_reached. {detail}", flush=True)
        return False, f"max_steps_reached ({detail})"

    except Exception as exc:
        print(f"[Apply] Error during Easy Apply: {exc}", flush=True)
        return False, f"exception:{type(exc).__name__}"
