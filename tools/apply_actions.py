import math
import os
import glob
from playwright.sync_api import Page
from tools.playwright_actions import random_sleep
from tools.cv_profile import cv_profile
from tools.profile_overrides import load as load_overrides
from tools import qa_overrides
from tools.form_llm import llm_answer_for_field, safe_default_for_binary
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
    if "phone" in text or "mobile" in text or "telephone" in text:
        return _phone() or None
    if "linkedin" in text and ("url" in text or "profile" in text):
        return _linkedin() or None
    if "github" in text:
        return _github() or None
    if any(k in text for k in ("portfolio", "website", "personal site")):
        return _portfolio() or None
    if "city" in text or "current location" in text or text.strip() == "location":
        return _city() or None
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


def _resolve_answer(
    label: str,
    options: list[str] | None,
    kind: str,
    context: dict | None,
    allow_human_loop: bool = False,
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
    # Layer 3: LLM-assisted filler.
    llm_model = (ctx.get("llm_model") if isinstance(ctx, dict) else None) or None
    answer = llm_answer_for_field(label, options or [], kind, llm_model)
    if answer:
        print(f"[Resolve]   → L3 LLM: {answer!r}", flush=True)
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
    print(f"[Resolve]   → UNRESOLVED (will leave empty)", flush=True)
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
            print(f"[TextInputs] empty field label={label!r}", flush=True)
            answer = _resolve_answer(label, None, kind, context)
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
    handle_resume_upload(page)
    # Typeaheads MUST run before plain text inputs — otherwise fill() sets the value without
    # firing the keydown events the typeahead listens for, and the suggestion is never picked.
    _fill_comboboxes(page, context)
    _fill_text_inputs(page, context)
    _fill_radios(page, context)
    _fill_selects(page, context)
    _fill_contenteditables(page, context)
    _fill_checkbox_groups(page, context)
    _second_pass_required(page, context)
    _audit_required_fields(page)


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
            if current:
                continue
            label = _label_text(box)
            print(f"[Combobox] empty label={label!r}", flush=True)
            answer = _resolve_answer(label, None, "text", context)
            if not answer:
                continue
            try:
                box.click()
                random_sleep(0, 1)
                # Real keystrokes so LinkedIn's typeahead keydown listeners fire and the listbox opens.
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
)


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
            llm_model = (context or {}).get("llm_model")
            answer = llm_answer_for_field(legend, [], "checkbox-group", llm_model) or ""
            if not answer:
                answer = option_texts[0]
                print(f"[Checkboxes]   LLM empty; defaulting to {answer!r}", flush=True)
            answer_low = answer.lower()
            picked: list[str] = []
            for opt in option_texts:
                opt_low = opt.lower()
                tokens = [t for t in opt_low.split() if len(t) > 2]
                if opt_low in answer_low or any(tok in answer_low for tok in tokens):
                    try:
                        label_map[opt].check()
                        picked.append(opt)
                    except Exception:
                        continue
            if not picked:
                try:
                    label_map[option_texts[0]].check()
                    picked.append(option_texts[0])
                except Exception:
                    pass
            print(f"[Checkboxes] picked={picked}", flush=True)
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
                    if (t === 'checkbox') return;
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
                    out.push({
                        tag: el.tagName,
                        type: t,
                        name: el.name || '',
                        id: el.id || '',
                        label: (label || '').trim().split('\\n')[0],
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
            else:
                kind = "text"

            print(f"[2ndPass] field tag={tag} type={ftype} name={name!r} label={label!r} options={options}", flush=True)
            # Required field that escaped the first pass — escalate to the human loop if needed.
            answer = _resolve_answer(label, options or None, kind, context, allow_human_loop=True)
            if not answer:
                print(f"[2ndPass]   no answer; leaving empty", flush=True)
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
                print(f"[2ndPass]   could not locate the field again", flush=True)
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


def handle_resume_upload(page: Page) -> None:
    try:
        upload_input = _modal_scope(page).locator("input[type='file']").first
        if upload_input.count() == 0:
            return
        resume_path = _resume_path()
        if not resume_path:
            return
        upload_input.set_input_files(resume_path)
        random_sleep(2, 3)
    except Exception as exc:
        print(f"[Apply] Resume upload skipped: {exc}", flush=True)


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
            loc = scope.get_by_role("button", name=name).first
            if _visible(loc):
                return loc
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
    try:
        heading = (scope.locator("h2, h3").first.inner_text(timeout=500) or "").strip()
    except Exception:
        heading = ""
    return (page.url, heading)


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
                        try: dismiss_btn.click()
                        except Exception: pass
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
                msgs = _collect_validation_messages(modal_after)
                joined = "; ".join(msgs) if msgs else "unspecified field error"
                _dump_modal_html(page, tag="validation")
                detail = f"step={step} heading={sig[1]!r} errors=[{joined}]"
                print(f"[Apply] Validation error. {detail}", flush=True)
                return False, f"validation_error ({detail})"

            if sig == last_sig:
                same_sig_count += 1
                if same_sig_count >= 2:
                    # Unconditional diagnostics — covers silent rejections and clicks that didn't register.
                    dom_size_after = _modal_dom_size(modal_after) if modal_after is not None else 0
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
                same_sig_count = 0
            last_sig = sig

        detail = f"steps={MAX_APPLY_STEPS} last_heading={last_sig[1]!r}"
        print(f"[Apply] max_steps_reached. {detail}", flush=True)
        return False, f"max_steps_reached ({detail})"

    except Exception as exc:
        print(f"[Apply] Error during Easy Apply: {exc}", flush=True)
        return False, f"exception:{type(exc).__name__}"
