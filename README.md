# LinkedIn Apply Agent

A LangGraph-orchestrated bot that searches LinkedIn for jobs, profiles, and
hiring posts, scores each one against your CV with an Ollama LLM, then
auto-applies via Easy Apply, sends connection requests, or drafts personalized
outreach emails / DMs. Ships with a FastAPI backend, a React dashboard, and a
Dockerized Playwright runtime with NoVNC for browser visibility.

> **Heads up — use at your own risk.** Automating LinkedIn violates their
> Terms of Service and can get your account restricted or banned. This project
> is intended for personal experimentation, research, and learning.
> Run it sparingly, with conservative daily caps, and consider using a
> dedicated account.

---

## Table of contents
- [Features](#features)
- [Architecture](#architecture)
- [Quick start (Docker)](#quick-start-docker)
- [Quick start (native, Windows)](#quick-start-native-windows)
- [First-run setup](#first-run-setup)
- [Configuration](#configuration)
- [Modes](#modes)
- [Project layout](#project-layout)
- [State files](#state-files)
- [Roadmap](#roadmap)

---

## Features

- **Three search modes**: `JOB` (Easy Apply), `PERSON` (connection requests),
  `POST` (feed hiring posts → email or DM).
- **LangGraph state machine** with explicit nodes for search → evaluate →
  apply / network / draft_email / draft_dm.
- **Hybrid Easy Apply form filler**: heuristics → user-editable Q&A overrides
  → LLM filler → safe binary defaults. Two-pass autofill + post-fill audit.
- **Pre-submit reviewer** audits every filled field against the resume + JD
  and clears hallucinated / object-repr / language-mismatched values before
  Submit fires.
- **Job-fit pre-screener** scores each search-result card 0–100 *before* the
  bot opens it, skipping clear mismatches without wasting Playwright cycles
  or LLM evaluate calls.
- **Cover-letter generation**: separate cover-letter file-upload slots trigger
  a job-aware LLM letter (with an optional self-critic pass) rendered to PDF.
- **Persisted manual-apply queues** for cases the bot can't or won't auto-fill:
  external ATS leads, "apply at <url>" posts, and outreach email drafts —
  each with status lifecycle and dashboard tabs.
- **Pending-connection sweeper**: queues a DM after sending an empty
  connection request, then a daily background task checks acceptance and
  sends the queued DM (or marks failed / still-pending).
- **Live SSE log feed** with optional verbose mode (`[Resolve]` / `[2ndPass]`
  / `[form_llm]` / etc.) streamed to the dashboard.
- **Dry-run mode** — full pipeline including LLM eval, but no Playwright
  submit / connect / draft work.
- **Daily caps** for applications and connections; pagination across all 40
  LinkedIn job pages with role rotation.
- **CV upload + LLM auto-target** infers role / locations / workplace types
  from your CV.

---

## Architecture

```
┌──────────────────┐         ┌────────────────────┐         ┌──────────────┐
│  React + Vite    │ ──SSE── │  FastAPI (server)  │ ──────► │  LangGraph   │
│  dashboard       │         │  /api/* + log feed │         │  state graph │
└──────────────────┘         └────────────────────┘         └──────┬───────┘
                                                                   │
                                ┌──────────────────────────────────┼───────────────┐
                                │                                  │               │
                          ┌─────▼─────┐                     ┌──────▼──────┐  ┌─────▼─────┐
                          │ Playwright │                     │  Ollama     │  │  Gmail    │
                          │ (Chromium) │                     │  (LLM)      │  │  (OAuth)  │
                          └────────────┘                     └─────────────┘  └───────────┘
```

- **Orchestration**: `agent/graph.py` defines the LangGraph state machine;
  `agent/nodes.py` implements each node (search / evaluate / apply / network /
  draft_email / draft_dm).
- **Browser**: `agent/browser.py` holds a single persistent Playwright context
  in `state/browser_state.json` (cookies + storage) so login survives across runs.
- **Backend**: `server.py` exposes a FastAPI surface — start/stop/pause, SSE
  log stream, CV upload, profile overrides, Q&A overrides, lead/outreach
  queues, login helpers.
- **Frontend**: `frontend/src/App.jsx` is a single-page React dashboard
  consuming the SSE feed and the REST endpoints.
- **LLM**: by default Ollama at `host.docker.internal:11434` with
  `gpt-oss:120b-cloud`. Configurable per-run via the sidebar.

---

## Quick start (Docker)

Prerequisites: Docker Desktop + a local [Ollama](https://ollama.com) instance
listening on `localhost:11434`.

```bash
cp .env.example .env
# Edit .env if you want — at minimum, leaving everything default is fine.

# Put your CV.txt and (optional) resume.pdf in the project root.
# CV.txt is plain text; resume.pdf is what gets uploaded to Easy Apply forms.

docker compose up --build -d
```

Open:
- **Dashboard**: http://127.0.0.1:8000
- **Browser view (NoVNC)**: http://127.0.0.1:6080/vnc.html — watch the
  Playwright session in real time.

Logs: `docker compose logs -f apply-bot`

Stop: `docker compose down`

---

## Quick start (native, Windows)

For development on Windows with no Docker:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cd frontend && npm install && cd ..

copy .env.example .env

run.bat
```

`run.bat` launches the FastAPI backend on `http://127.0.0.1:8000` and the Vite
dev server on `http://localhost:5173`. Ctrl+C in the launcher window cleans
both up.

---

## First-run setup

1. **CV** — drop your CV as `CV.txt` (plain text) in the project root,
   or upload via the dashboard. Optionally drop `resume.pdf` for the
   Easy Apply file uploader.
2. **LinkedIn login** — open the dashboard, click **Login to LinkedIn**.
   A Playwright Chromium window opens (visible in NoVNC under Docker, or
   directly on your desktop natively). Log in manually once; the session
   is persisted to `state/browser_state.json`.
3. **Auto-target** (optional) — click **Auto-target from CV** to let the LLM
   suggest role / locations / workplace types from your CV.
4. **Profile overrides** — open the Profile tab to set or correct fields
   the form filler will use (phone, years experience, salary expectation,
   notice period). Overrides win over CV-extracted values.
5. **Q&A overrides** — the Form Q&A tab shows the regex-to-answer map used
   by the form filler. Edit the seeded defaults (sponsorship, notice, etc.)
   to match your situation.
6. **Gmail OAuth** (optional, for POST mode email drafts) — drop your Google
   `credentials.json` in the project root and run `python setup_auth.py` to
   produce `token.json`. Both files are gitignored.

---

## Configuration

All configuration lives in `.env`. See `.env.example` for the full list. Key
knobs:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEFAULT_LLM_MODEL` | `gpt-oss:120b-cloud` | Ollama model for eval / form-fill / cover letter. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Compose overrides to `host.docker.internal`. |
| `APPLY_THRESHOLD` | `70` | Min match score for a job to be auto-applied. |
| `OUTREACH_THRESHOLD` | `60` | Min match score for a post → outreach. |
| `JOB_FIT_SCREEN_THRESHOLD` | `40` | Pre-screener cutoff (cards below are skipped). |
| `JOB_SCREENER_ENABLED` | `true` | Turn the pre-screener off. |
| `PRE_SUBMIT_REVIEWER_ENABLED` | `true` | Turn the pre-submit field auditor off. |
| `COVER_LETTER_CRITIC_ENABLED` | `true` | Run a critic pass on generated cover letters. |
| `MAX_APPLICATIONS_PER_DAY` | `50` | Daily cap on Easy Apply submissions. |
| `MAX_CONNECTIONS_PER_DAY` | `30` | Daily cap on outgoing connection requests. |
| `MAX_ITERATIONS` | `50` | Per-run iteration cap in JOB mode. |
| `MAX_WATCH_ITERATIONS` | `1000` | Cap in PERSON / POST watch modes. |
| `APPLICANT_*` | unset | Fallback values used only if profile + CV both lack a field. |

Sidebar settings (role, locations, workplace types, headless, dry-run,
verbose) persist in `localStorage` and survive page reloads — `.env` is for
defaults, the sidebar is for per-run.

---

## Modes

### JOB
Easy Apply hunting. Rotates between comma-separated roles each iteration,
paginates through up to 40 result pages, screens each card with the
pre-screener, evaluates passing cards with the main LLM, then applies if
`match_score ≥ APPLY_THRESHOLD`. External ATS redirects become **External
Leads** for manual review.

### PERSON
Connection-request mode. Searches People by role + location, sends static
templated connection invites. Watch-mode: never terminates on empty results.

### POST
Feed scraping. Expands "see more" on each post, extracts author + content +
emails. High-scoring posts trigger:
- **Email path** if an email was found → Gmail draft created (and recorded
  in `state/outreach_emails.json` regardless of Gmail success).
- **DM path** otherwise → empty connection request sent now, personalized
  DM queued in `state/pending_connections.json` and sent once the invite
  is accepted (background sweep every 24h).
- **Apply-link path** when the post says "apply at <url>" → recorded in
  `state/apply_link_posts.json` for the user to click manually.

---

## Project layout

```
agent/
  graph.py              LangGraph state machine + search nodes
  nodes.py              evaluate / apply / network / draft_email / draft_dm
  browser.py            Playwright persistent context
tools/
  apply_actions.py      Easy Apply orchestrator: modal scoping, autofill, submit
  form_llm.py           LLM filler for unmapped form questions
  playwright_actions.py LinkedIn-specific browser helpers (login, search, connect)
  post_extractor.py     feed-post scraping (author URL, content, emails)
  job_screener.py       pre-card LLM screening (0-100 fit score)
  pre_submit_reviewer.py LLM audit of filled fields before submit
  cover_letter.py       LLM cover-letter PDF generator (+ critic)
  external_leads.py     persisted queue for external ATS redirects
  apply_link.py         persisted queue for "apply at <url>" posts
  outreach.py           persisted log of every email outreach decision
  pending.py            queued DMs awaiting connection acceptance
  gmail_actions.py      Gmail OAuth + draft creation
  human_loop.py         pause / question-the-user flow
  qa_overrides.py       user-editable regex → answer map
  applications.py       daily-cap tracker for Easy Apply submissions
  history.py            already-processed IDs
  llm_models.py         Ollama model resolution + base URL
  resume_parser.py      pypdf → text
  profile_overrides.py  state/profile_overrides.json read/write
frontend/
  src/App.jsx           single-page dashboard
server.py               FastAPI: REST + SSE
setup_auth.py           one-shot Google OAuth bootstrap → token.json
login_helper.py         interactive LinkedIn login helper
Dockerfile              multi-stage: node frontend build + python backend
docker-compose.yml      service definition with volume mounts
start.sh                container entrypoint (Xvfb + x11vnc + uvicorn)
run.bat                 Windows dev launcher (backend + Vite)
```

---

## State files

All under `state/`. The directory itself is committed (for the Python module),
data files are gitignored.

| File | Purpose |
| --- | --- |
| `database.json` | Stats + activity feed shown in dashboard. |
| `history.json` | Already-processed job / person / post IDs. |
| `applications.json` | Daily Easy Apply submission counter. |
| `pending_connections.json` | DMs queued, waiting for connection acceptance. |
| `external_leads.json` | External ATS redirects awaiting manual apply. |
| `apply_link_posts.json` | "Apply at <url>" hiring posts. |
| `outreach_emails.json` | Every email draft the bot prepared. |
| `qa_overrides.json` | User-editable regex → answer map. |
| `profile_overrides.json` | User-edited profile fields. |
| `browser_state.json` | Playwright persistent context (cookies). |
| `errors/` | Screenshots + HTML dumps of failed applies. |
| `debug/`, `incidents/`, `self_heal/` | **PII** — scraped profiles, never commit. |

---

## Roadmap

See [`TODO.md`](TODO.md) for the full status + roadmap (what's done, what's
partial, what's missing).

---

## License

Personal project, no license attached. Don't redeploy publicly without
considering LinkedIn's Terms of Service and the privacy of profiles you scrape.
