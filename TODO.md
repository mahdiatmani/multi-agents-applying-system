# LinkedIn Apply Agent — Status & Roadmap

A LangGraph-orchestrated bot that searches LinkedIn for jobs, profiles, and posts,
scores each one against the user's CV with an Ollama LLM, then auto-applies via
Easy Apply, sends connection requests, or drafts personalized outreach emails/DMs.

---

## What the app has today

### Architecture
- **Orchestration**: LangGraph state machine (`agent/graph.py`) with nodes for
  `init`, `search_job`, `search_person`, `search_post`, `evaluate`, `apply`,
  `network`, `draft_email`, `draft_dm`.
- **Browser**: Playwright with persistent session in `state/browser_state.json`
  (`agent/browser.py`). Headless mode toggleable from UI.
- **Backend**: FastAPI in `server.py` with SSE log streaming (`/api/logs`),
  start/stop endpoints, JSON DB at `state/database.json`, pending-connections
  store at `state/pending_connections.json`, and a daily background sweeper.
- **Frontend**: React + Vite app in `frontend/` with live activity feed,
  stat cards, profile/CV editor, login-status indicator, side-panel settings
  persisted to `localStorage`.
- **Persistence**: `state/history.json` tracks already-processed
  job/person/post IDs (`tools/history.py`); `state/database.json` holds stats
  + activity feed; `state/pending_connections.json` tracks queued DMs.
- **Containerized**: builds & runs via `docker compose up --build -d`
  (frontend bundled in same image; Ollama reached via `host.docker.internal`).

### LLM evaluation
- Default model: `gpt-oss:120b-cloud` via Ollama (`tools/llm_models.py`).
  Overridable through `DEFAULT_LLM_MODEL` env var or UI selector.
- Structured output (`with_structured_output`, JSON schema) → `match_score`,
  `reasoning`, `action`, `extracted_email`, `draft_message`.
- Score thresholds force the decision: `APPLY_THRESHOLD` for jobs,
  `OUTREACH_THRESHOLD` for posts — LLM cannot override the score band.
- 3-retry loop on LLM call before giving up.
- Auto-targeting endpoint (`/api/auto-target`) infers Role / Locations /
  Workplace Types from CV.txt.

### Job search & apply
- Configurable search role(s) (**comma-separated → rotates between roles each
  iteration**), locations (multi), workplace types (Remote/Hybrid/On-site).
- Easy Apply form handler (`tools/apply_actions.py`):
  - **Modal-scoped operations**: all button/field lookups are scoped to the
    Easy Apply modal — eliminates the previous bug where the bot clicked
    page-level "Next" buttons when the modal never opened.
  - **Modal-open verification**: after clicking Easy Apply, polls up to 6s
    for the modal to actually appear; returns `modal_did_not_open` otherwise.
  - **Post-submit verification**: after clicking Submit, verifies that the
    modal closed OR a confirmation message ("application sent" / "candidature
    envoyée" in 6 locales) is visible — otherwise returns
    `submit_no_confirmation`.
  - **Multi-locale button detection** for Easy Apply / Submit / Next / Review
    / Dismiss / Discard (EN, FR, ES, DE, IT, PT) with CSS-class fallback.
  - **Save-vs-Easy-Apply discrimination**: filter checks aria-label and text
    against Save-button keywords in 6 locales.
  - Auto-fills text inputs, radios, and selects using label-text heuristics.
  - Resume upload from a PDF in the project root or `RESUME_PDF_PATH`.
  - Field resolution chain: UI override → `.env` → CV.txt → default.
  - Home-country detection for `authorized to work` / `sponsorship` answers.
  - **Detailed failure reasons** with job context: each `APPLY_FAILED` log
    includes the job title, company, URL, the failing step, modal heading,
    the specific validation message + field label, or the visible field
    labels when stuck. Screenshots saved to `state/errors/<reason>-<ts>.png`.
- Skips already-processed job IDs to avoid duplicates.
- `SEARCHED_EMPTY` action when search finds nothing new — routes back to
  search without wasting an LLM call.
- Per-run cap via `MAX_ITERATIONS` (default 50). Empty-streak terminator
  for JOB mode (default 3 empty cycles).

### Posts (feed) outreach
- `search_post_node` (`agent/graph.py`):
  - Expands each post's "see more" / "voir plus" toggle before scraping so
    the full body (incl. email addresses) is captured.
  - Extracts: author name, **author profile URL**, full content, **all
    emails** matched by regex, search URL.
- LLM evaluator writes a **language-matched** personalized message body
  (120–180 words for emails, 80–120 for DMs) referencing the specific role
  title + tech stack from the post and concrete matching items from the CV.
- **Email path** (`draft_email_node`): when an email is found, creates a
  Gmail draft via Google OAuth (`tools/gmail_actions.py`). User reviews
  before sending.
- **DM path** (`draft_dm_node`): when no email is found:
  1. Enforces a daily cap (`MAX_CONNECTIONS_PER_DAY`, default 30).
  2. Sends an **empty connection request** to the post author
     (`send_empty_connection` — works in EN/FR/ES/DE/IT/PT).
  3. Queues the LLM-generated DM in `state/pending_connections.json`.
- **Pending-connection sweep** (`check_pending_connections`):
  - Visits each pending profile, checks for `Message` button to detect
    acceptance, sends the queued DM if accepted, marks `dm_sent` / `dm_failed`
    / `still_pending`.
  - Triggered automatically every 24h by a background asyncio task in
    `server.py`, and manually via the **"Check Pending Connections"** button
    in the sidebar (`POST /api/check-pending`).

### Watch mode (POST / PERSON)
- POST and PERSON modes never terminate on empty results — keep polling the
  feed/people search indefinitely (up to `MAX_WATCH_ITERATIONS`, default
  1000). Sleep 15–25s between empty-feed reloads to be gentle on LinkedIn.

### People search (`PERSON` mode)
- `search_person` node finds new profiles in the people-search results.
- `network_node` sends a connection request with a static templated message.
  *(The richer LLM-personalized flow described above is currently wired up
  for POSTS only; PERSON still uses the legacy hardcoded template — see
  Medium-priority TODO below.)*

### Profile & CV
- CV upload (`/api/upload-cv`): PDF parsed with pypdf, also runs through
  LLM to extract structured profile fields.
- Profile overrides editor in the UI (`/api/profile`) saves to
  `state/profile_overrides.json` and takes precedence over CV-extracted data.

### Operational tools
- **Clear DB & History** button + `POST /api/db/reset`: wipes
  `state/database.json`, `state/history.json`, and
  `state/pending_connections.json`. Disabled while an agent run is active.
- **Side-panel settings persist** in `localStorage` (role, locations,
  workplace types, company, LLM model, Ollama-cloud flag, headless flag,
  selected modes). Survive page reload.
- **Pending stats endpoint** (`GET /api/pending`): returns counts +
  full list of queued connections (status, queued DM, post content).

### Job-fit pre-screener (`tools/job_screener.py`)
- Reads each search-result card's visible text (title + company + location +
  snippet) **before** opening the job and scores it 0-100 vs the CV with the
  Ollama LLM. Cards below `JOB_FIT_SCREEN_THRESHOLD` (default 40) are marked
  processed and skipped — saving a click, a `get_job_details` call, an
  evaluate LLM call, and a likely-failing Easy Apply attempt.
- Soft-fail: `score=-1` (LLM error / no resume / disabled) falls through to
  normal processing instead of blocking. Toggle with `JOB_SCREENER_ENABLED=false`.

### Pre-submit reviewer (`tools/pre_submit_reviewer.py`)
- Runs immediately before clicking Next/Review/Submit on every Easy Apply step.
  Sends every filled (label, value, kind) to the LLM with the resume + job
  context and gets back a per-field verdict.
- Flags: object-repr leaks (`AIMessage(`, `content=...`), hallucinated
  skills/tools/certifications/languages not in the resume, language mismatch
  (English answer to a French question), logical lies ("Yes, I worked at X"
  when X isn't on the resume), empty-but-required fields.
- Flagged fields are cleared so the next autofill pass re-resolves them with
  fresh context. Toggle with `PRE_SUBMIT_REVIEWER_ENABLED=false`.

### Cover-letter generation (`tools/cover_letter.py`)
- When an Easy Apply form has a **separate** file-upload slot for a motivation /
  cover letter (distinct from the resume slot), the bot generates a tailored
  PDF instead of re-uploading the resume.
- LLM prompt enforces: resume facts only (no invented skills/certs/languages),
  job-language matched (writes in French for a French JD), 250–380 words,
  plain text (no markdown / placeholders).
- Optional self-critic pass behind `COVER_LETTER_CRITIC_ENABLED=true` (default
  on) re-reads the draft and rewrites flagged issues before rendering.
- Output saved to `cover-letters/<company>-<title>-<timestamp>.pdf` (gitignored)
  for the user's records, then uploaded via Playwright.

### Lead persistence (manual-apply queues)
- **External leads** (`tools/external_leads.py`, `state/external_leads.json`):
  every `external_apply` detection (modal didn't open, Workday / Lever /
  Greenhouse / Ashby redirect) is recorded with title, company, destination
  URL, and reason. Endpoints: `GET /api/external-leads`,
  `POST /api/external-leads/status|remove|clear`. Status lifecycle:
  `new → viewed → applied | dismissed`.
- **Apply-link posts** (`tools/apply_link.py`,
  `state/apply_link_posts.json`): hiring posts containing "apply at <url>" /
  external ATS links that the bot deliberately doesn't auto-click. Endpoints:
  `GET /api/outreach` (combined), `POST /api/outreach/links/status|remove|clear`.
- **Outreach emails** (`tools/outreach.py`, `state/outreach_emails.json`):
  every email draft the bot prepared, including failures (`gmail_unauth`,
  `gmail_failed`) — so the user can copy/send manually when Gmail OAuth is
  broken. Endpoints: `POST /api/outreach/emails/status|remove|clear`.

### Custom Easy Apply form filler (hybrid stack)
- Layered answer resolution in `tools/apply_actions.py:_resolve_answer`:
  1. **Heuristics** (`_answer_for`) — hardcoded keyword patterns (phone,
     email, years exp, sponsorship, authorized, salary, notice).
  2. **User overrides** (`tools/qa_overrides.py`,
     `state/qa_overrides.json`) — regex → answer map seeded with 9 sensible
     defaults (start immediately, sponsorship, criminal, relocate,
     driver's license, salary, currently employed). Editable from a new
     **"Form Q&A"** tab in the UI (`/api/qa-overrides` GET/POST,
     `/api/qa-overrides/reset`).
  3. **LLM filler** (`tools/form_llm.py`) — when the prior layers don't
     match, calls Ollama with the full CV text + question label + options
     + field kind. Uses structured output (Pydantic schema), 2 retries on
     failure. Cached per `(label, model, options)`. Cross-locale Yes/No
     mapping (LLM may answer "Yes" → mapped to "Oui"/"Sí"/"Ja").
  4. **Safe Yes/No default** for binary radios with no other signal.
     Defaults to "Yes" unless the question contains negative-impact
     keywords (sponsorship, criminal, currently employed, non-compete) →
     defaults to "No".
- **Field discovery** covers `<input>` (any non-radio/checkbox/hidden/file
  type, including no-type defaults), `<textarea>`, `<fieldset>`,
  `<div role='radiogroup'>`, `<select>`. Radio group label extraction
  uses `<legend>` first, then `aria-labelledby`, then a parent
  `.fb-dash-form-element` wrapper label.
- **Two-pass autofill**: first pass fills via type-specific functions;
  second pass (`_second_pass_required`) walks every required field still
  empty, looks it up by `id`/`name`, and re-resolves via the LLM.
- **Post-fill audit** (`_audit_required_fields`) lists every required
  field still empty before clicking Next, so logs show exactly what was
  missed.
- **Diagnostic dump** (`_dump_modal_html`): when validation_error or
  stuck_unknown_form fires, the modal's `outerHTML` is saved to
  `state/errors/{validation,stuck}-<ts>.html` for inspection.
- Verbose tracing at every layer prefixed with `[Resolve]`, `[form_llm]`,
  `[TextInputs]`, `[Radios]`, `[2ndPass]`, `[Audit]`, `[Dump]` — visible
  via `docker compose logs -f apply-bot`.

---

## What's missing / known limitations

### High priority
- [x] **`modal_did_not_open` on apparently-Easy-Apply jobs**: now
      distinguished from external-ATS / company-site redirects.
      `apply_easy_apply` records `page.url` before clicking, then if
      no modal opens within 6s calls `_detect_external_apply` which
      checks (a) host left linkedin.com, (b) a `<a target='_blank'>`
      link to a non-linkedin host, (c) the "Continue applying on
      company website" interstitial text in 5 locales. When matched,
      returns `external_apply (<signal>)` and the standard
      `apply_node` screenshot logic saves a snapshot tagged
      `apply-external_apply-<ts>.png`.
- [x] **`validation_loop` with no captured error details**: the
      stuck-on-same-step branch now (a) measures modal DOM size before
      the Next click and after the post-click sleep — the delta tells
      us whether the click changed anything, (b) unconditionally calls
      `_dump_modal_html(page, tag="validation_loop")` so the markup is
      always preserved for inspection, (c) calls
      `_collect_validation_messages` even when `_has_validation_error`
      returned false (silent rejections), (d) captures the visible
      modal button labels via the new `_modal_button_texts` helper,
      (e) logs `page.url`, heading, dom-delta, messages, and buttons
      in the reason string.
- [x] **Robust Submit Button Detection**: The `_button_in` locator has
      been updated with fallback strategies (`has-text`, `aria-label`)
      to ensure buttons nested in complex DOM structures (like spans
      inside buttons) are reliably clicked, preventing false validation loops.
- [x] **PERSON / watch-mode runaway loop**: `search_person_node`,
      `search_job_node`, and `search_post_node` now sleep with
      exponential backoff (15-25s / 25-40s / 40-60s) when results are
      empty, keyed on `empty_streak`. The shared `_empty_backoff()`
      helper lives in `agent/graph.py`.
- [x] **Container debug logs not visible in UI**: server installs a
      `_StdoutTap` over `sys.stdout` that passes everything through to
      the real terminal AND, when `_verbose_state['on']` is true, pushes
      any line starting with `[Resolve]`, `[2ndPass]`, `[Audit]`,
      `[Dump]`, `[form_llm]`, `[TextInputs]`, `[Radios]`, `[Apply]`,
      `[Connect]`, `[Snapshot]`, `[JOB]`, `[PERSON]`, or `[POST]` into
      `log_queue` (the SSE feed) as `{type: 'debug', action:
      'VERBOSE'}`. The flag is flipped on while `run_agent_workflow`
      runs whenever `StartRequest.verbose` is true; UI sidebar has a
      "Verbose logs (debug)" checkbox.
- [x] **Sequential Multi-Role Execution**: When a user selects multiple
      roles, they are now strictly processed sequentially (one finishes
      completely before the next begins), avoiding concurrent browser
      interference.
- [x] **Vite IPv6 Proxy `ECONNREFUSED`**: Fixed the frontend development
      server by explicitly targeting `127.0.0.1` rather than `localhost`
      to prevent Node.js IPv6 resolution errors when communicating with
      the IPv4 FastAPI backend.
- [~] **External ATS applications** — *partial: lead capture + persisted
      queue done, ATS form filling still TODO*:
      `_detect_external_apply` returns `(is_external, signal, meta)` where
      `meta` carries `destination_url` + `destination_title`. `apply_node`
      recognises the `external_apply` reason prefix and emits action
      `EXTERNAL_LEAD` (counted in `update_stat('externalLeads')`) instead of
      `APPLY_FAILED`, with the destination URL in the error message and a
      screenshot saved. Each lead is also persisted to
      `state/external_leads.json` via `tools/external_leads.py` with status
      lifecycle `new → viewed → applied | dismissed`, surfaced via
      `/api/external-leads` and a dashboard tab. Generic Workday / Lever /
      Greenhouse / Ashby form filling is still out of scope.
- [x] **Custom Easy Apply questions — edge cases**: `_autofill_step`
      now also runs `_fill_contenteditables`,  `_fill_comboboxes`,
      and `_fill_checkbox_groups`. Contenteditable nodes are filled
      via JS (`innerText` + bubbling `input`/`change` events).
      `[role='combobox']` is typed into and the first
      `[role='listbox'] [role='option']` is clicked (Enter fallback
      if no listbox appears). Multi-select checkbox fieldsets ask the
      LLM free-form (kind="checkbox-group") and check every option
      whose tokens appear in the answer; falls back to the first
      option to avoid leaving a required group empty. Dynamic
      conditional fields still rely on `_second_pass_required` to
      pick them up in the next pass.
- [x] **Pagination**: `search_jobs()` accepts a `start: int = 0` offset
      and appends `&start=N` to the LinkedIn URL. `search_job_node`
      tracks `job_page_start` (and `_last_role`) in agent state:
      advances by 25 when a page yields no new jobs, wraps back to 0
      past `start=975`, and resets to 0 when the rotating role
      changes.
- [x] **Application daily cap**: new `tools/applications.py` mirrors
      the pending-DB pattern: persists day→count to
      `state/applications.json` under a lock, exposes `today_count()`,
      `can_apply_today(cap)`, `record_application()`, `stats()`,
      `reset()`. Cap reads `MAX_APPLICATIONS_PER_DAY` env (default 50).
      `apply_node` gates on `can_apply_today()` before doing any
      Playwright work and emits `SKIP` when the cap is hit; on success
      it calls `record_application()` and logs the new daily total.
      `/api/db/reset` also resets the counter.
- [x] **Dry-run mode**: `StartRequest.dry_run` (sidebar checkbox
      "Dry run (preview only)") propagates into the agent state.
      `apply_node`, `network_node`, `draft_email_node`, and
      `draft_dm_node` each short-circuit when `state['dry_run']` is
      true, logging what they would have done and emitting
      `DRY_RUN_APPLY` / `DRY_RUN_NETWORK` / `DRY_RUN_EMAIL` /
      `DRY_RUN_DM` actions (which the frontend labels as
      "Dry-run: would …"). No Playwright submit/connect/draft work
      runs; LLM evaluation still does.

### Medium priority
- [ ] **Apply human-loop in UI**: surface `APPLY_FAILED` reasons (with
      job title, heading, failing field, screenshot link) as cards in
      the dashboard so the user can quickly see what to fix. Today
      the detailed reasons are only in the SSE log feed.
- [ ] **Pending-connections panel in UI**: display the list of pending
      invites (name, post content snippet, queued DM, days waiting) as
      a tab in the dashboard. Today only summary counts are visible.
- [ ] **Retry queue for DM failures**: `dm_failed` entries in
      `pending_connections.json` never get retried. Add a retry loop
      with backoff, capped at N attempts.
- [~] **Surface emails-found / language-detected fields** — *partial*:
      every email draft is now persisted to `state/outreach_emails.json`
      (recipient, subject, body, post excerpt, match score, status) and
      shown in the dashboard's Outreach tab via `/api/outreach`. The post
      activity card itself still doesn't inline the detected email /
      language — would be a quick win.
- [ ] **Dynamic templating for PERSON mode**: `network_node` still uses
      the hardcoded `"Hi [Name], I noticed your work at [Company]..."`
      string. Reuse the LLM-generated `draft_message` like the POST flow.
- [x] **Cover-letter generation**: separate file-upload slots for a
      motivation letter are now handled by `tools/cover_letter.py` —
      generates a job-aware PDF via the LLM (resume + JD), with an
      optional self-critic rewrite pass (`COVER_LETTER_CRITIC_ENABLED`),
      saved to `cover-letters/` and uploaded via Playwright. *Remaining:
      job-aware free-text cover-letter answers in the form filler itself
      (the `form_llm` path) — see next item.*
- [ ] **Form-LLM job context**: same root issue as above —
      `llm_answer_for_field` only gets the CV + question label. When
      the question is open-ended ("Why are you interested in this
      role?"), passing the job title/company/description would yield
      much better answers.
- [ ] **Email-required connections**: LinkedIn sometimes asks for the
      recipient's email before sending a connection. Currently fails
      with `no_send_button`. Detect and skip gracefully with a clear
      reason.
- [ ] **Frontend `DEFAULT_LLM_MODEL` duplication**: hardcoded in
      `frontend/src/App.jsx:17` and `tools/llm_models.py:6`. Source it
      from `/api/models` at page load so bundle rebuild isn't required
      when defaults change.
- [ ] **History TTL**: `state/history.json` grows forever. Add expiry
      (e.g. drop entries older than 30 days) so reposted jobs can be
      retried, and `pending_connections.json` entries with `dm_sent`
      status older than X days can be archived.
- [ ] **Configurable thresholds in UI**: `APPLY_THRESHOLD` and
      `OUTREACH_THRESHOLD` are env-only. Expose them as sidebar sliders
      so the user can tune at runtime.

- [ ] **Pre-submit reviewer retry budget**: when the reviewer clears
      fields, the next autofill pass may re-fill them with the same bad
      value (LLM determinism + cache). Cap retries at N and skip the
      whole application when the reviewer keeps flagging the same field.
- [ ] **Cover-letter critic loop count**: today the critic runs at most
      once. For French / Spanish letters the first draft sometimes still
      contains English boilerplate from the prompt — allow up to 2
      critic passes when the critic flags a language mismatch.

### Lower priority
- [ ] **High-confidence auto-send for emails**: optional toggle —
      auto-send (not draft) when `match_score ≥ HIGH_AUTOSEND_THRESHOLD`
      (e.g. 90+). Currently we draft 100% of the time per user choice.
- [ ] **Per-job customization of CV / cover letter**: pick the best
      resume variant from a list based on JD keywords.
- [ ] **Reasoning history**: store the `reasoning` field next to each
      skipped/applied job so the user can audit decisions in the UI.
- [ ] **Retry queue for APPLY_FAILED**: jobs that failed with
      `stuck_unknown_form` or `validation_error` could be retried after
      code improvements (custom-form filler, etc.) without re-scraping.
- [ ] **Structured logging**: replace `print()` with Python's `logging`
      module writing to `bot.log` with levels + rotation. Currently logs
      go to stdout + SSE stream only.
- [ ] **Multi-account support**: today `.env` holds one set of LinkedIn
      credentials. Useful for testing with a burner account.
- [ ] **Test coverage**: no tests in the repo. Add at minimum unit tests
      for the post extractor (email regex, see-more click), the apply
      router (terminal conditions, multi-role rotation), and the
      pending DB (daily cap, status transitions).
- [ ] **Local LLM fallback**: `llama3.1:8b` local model currently
      returns HTTP 500 in this env. Either fix the install or hide
      broken local models from the UI dropdown.
- [ ] **Connection-status detection robustness**: current heuristic
      relies on the "Message" button being visible on the profile to
      infer acceptance. Add a fallback: scrape the
      `linkedin.com/mynetwork/invitation-manager/sent/` page to
      cross-check pending vs withdrawn vs accepted.

### Cleanup
- [ ] `agent/nodes.py` and `server.py` both import `ChatOllama` —
      consolidate the LLM client behind `tools/llm_models.py`.
- [ ] `_HOME_TERMS_DEFAULT` is Morocco-specific — move to a config file
      so other users don't have to edit code.
- [ ] The legacy `send_connection_request` function in
      `tools/playwright_actions.py` is no longer called by the new POST
      flow but is still used by `network_node` for PERSON mode. Once
      PERSON migrates to the LLM-templated flow, delete the legacy fn.
- [ ] `draft_dm_node` is now misnamed — it actually performs the
      empty-connect-and-queue flow, not a simple DM draft. Rename to
      `connect_and_queue_dm_node` (or similar) for clarity.
- [ ] `form_llm._ANSWER_CACHE` is process-global and never invalidated.
      Acceptable for a single run, but if the user updates their CV
      mid-run the cached LLM answers become stale. Add a clear-cache
      hook on profile/CV save.
- [ ] `state/errors/*.html` dumps from `_dump_modal_html` accumulate
      forever. Add a startup cleanup that deletes dumps older than
      7 days, or rotate the directory.
