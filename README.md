# JobPilot

A local, single-user job-application assistant. Upload your resume, and JobPilot finds jobs, tailors your resume to each one using **only facts you've verified**, and tracks your applications (including updates from your email).

> **Automate the workflow, not the truth.** JobPilot never invents employers, titles, dates, skills, certifications or metrics. Every line of a tailored resume is traced to a fact in your profile and checked automatically before you can approve it.

## Install as a desktop app (recommended)

```powershell
.\install-app.ps1
```
Adds a **JobPilot** icon to your Desktop and Start menu. It opens in its own window (no browser tabs, no console) and the background server stops when you close the window. Paste your Gemini API key under **Settings** — it is verified and kept in Windows Credential Manager. Your data lives in `%LOCALAPPDATA%\JobPilot\data` (outside OneDrive). Log: `%LOCALAPPDATA%\JobPilot\data\jobpilot.log`.

Note: autopilot and email checks only run while the app is open.

## Running it online
The same code also runs as a private hosted service: UI on Vercel, backend in a Docker container with Postgres, password login. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Quick start from a terminal (Windows)

Requires Python 3.13 (`py -3.13`) and Node.js 20+.

```powershell
.\start.ps1
```

The first run installs everything, creates `.env` and opens it — add your **Gemini API key** (https://aistudio.google.com/apikey), save, and run `.\start.ps1` again. The app opens at http://localhost:8000.

Developing the UI? `.\start.ps1 -Dev` runs Vite with hot reload on http://localhost:5173.

## How it works

1. **Profile** — upload a PDF, DOCX or DOC resume. It's parsed into a *fact ledger* (roles, achievements, skills, education…). Facts that can't be matched exactly to your resume text are flagged low-confidence. Review and **verify** them; only verified facts are used.
2. **Preferences** — titles, locations, salary, seniority, exclusions… each set as **Hard** (job excluded), **Soft** (ranking only) or **Info**.
3. **Connections** — job sources:
   - **Greenhouse / Lever / Ashby** public job boards (one connection per company, e.g. `stripe`, `openai`)
   - **MyCareersFuture** (Singapore) keyword searches
   - **Job-alert emails** from LinkedIn/Indeed/JobStreet etc. via a connected mailbox
   - Any job **URL** (structured data) or **pasted** description
   Mailboxes: **Gmail** and **Outlook/Hotmail** (read-only) — setup: [docs/SETUP_OAUTH.md](docs/SETUP_OAUTH.md).
4. **Discover** — jobs are filtered by hard requirements, then scored (skills, role, seniority, industry, location, salary — weights adjustable) with an explanation and a list of gaps.
5. **Resume Studio** — generates a tailored **DOCX + PDF** (ATS-friendly), plus an optional cover letter. You get a side-by-side diff against your master resume, a change report, and the results of the factuality checks. Edit wording, then approve.
6. **Apply** — opens the official application page with your documents ready; you submit there and click *Mark as submitted*. Duplicate applications to the same role are blocked.
7. **Track** — application timeline; connected mailboxes automatically detect confirmations, interviews, assessments, offers and rejections. Ambiguous emails wait for you under *Email matches*.
8. **Autopilot** (off by default) — on a schedule, scores new jobs from the sources you enable, tailors and checks resumes for those above your threshold, and queues them for one-click submission. Daily/weekly caps, instant pause, full audit log.

### Why doesn't autopilot click "Submit" for me?
None of these job sources offer an official API for *candidates* to submit applications (Greenhouse/Lever/Ashby's apply APIs need the employer's key; LinkedIn/Indeed/MyCareersFuture have none). Automating their web forms would break their terms and mean bypassing anti-bot checks. So JobPilot does everything up to the final click. The provider adapters have a `submit` capability flag, so an official submit route can be plugged in if one becomes available.

## Factuality checks (run on every tailored resume)
- Every bullet/summary must cite verified fact IDs; unknown or missing citations fail.
- Any number (%, $, team size, volume) must appear in the cited facts. "N+ years" is allowed only up to your actual tenure.
- Job keywords not found anywhere in your profile fail; ones in your profile but not in that bullet's facts are flagged for you to confirm.
- Achievements can't move to a different employer or project.
- Skills must exist in your profile. Employer, title, dates and education are copied from the ledger, never from the model.
- Date/chronology checks, duplicate and keyword-stuffing checks, and a second-pass AI review for overstatement (e.g. "familiar with" turned into "expert in").
- The generated PDF is re-read as an ATS would, to confirm your name, employers and titles come out as text.
On a failed check the model is asked to regenerate once with the errors. If it still fails, the resume can't be approved.

## Changing the AI model
Edit `.env` (`LLM_MODEL`, `LLM_FAST_MODEL`) and restart. To add another provider (e.g. Claude or OpenAI), implement the `LLMProvider` protocol in `backend/app/llm/` and register it in `registry.py`, then set `LLM_PROVIDER`.

## Project layout
```
backend/app/
  ingest/      upload validation, PDF/DOCX/DOC text extraction, AI parsing → fact ledger
  providers/   Greenhouse, Lever, Ashby, MyCareersFuture adapters, URL import
  jobs/        normalisation, cross-source dedupe, requirement extraction
  matching.py  hard filters + weighted scoring
  tailoring/   generation, deterministic QA, change report
  render/      DOCX + HTML→PDF (Chromium) templates
  applications.py  state machine, idempotency, handoff
  email/       Gmail + Microsoft Graph clients, classifier, matcher
  autopilot.py policy, caps, runner
  worker.py    DB-backed task queue + scheduler (retries, backoff, dead-letter)
  api.py       REST API (/api/v1, docs at http://localhost:8000/docs)
frontend/src/  React + TypeScript UI
data/          SQLite DB, original resumes (read-only), generated documents
```

## Tests
```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q
```
The tests cover the factuality gate with fabricated content, idempotency and duplicate prevention, status rules, provider adapters (recorded responses), dedupe, email classification and linking, the sensitive-question guard, autopilot caps/pause and safety invariants, and end-to-end tailoring with real DOCX/PDF rendering. The AI model is replaced by a fake in tests.

## Privacy
Everything runs and is stored locally in `data/`. Resume text, job descriptions and job-related email snippets are sent to the configured AI provider for processing. Export or delete all data from **Settings**.
