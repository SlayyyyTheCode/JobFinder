# Deploying JobPilot online (Vercel UI + always-on backend)

```
Browser ──▶ Vercel (static UI) ──/api/*──▶ Backend container (Railway/Fly/VPS) ──▶ Postgres
                                                  └─ volume /data (resumes, generated PDFs)
```
Vercel rewrites `/api/*` to the backend, so the browser only ever talks to **one origin** — the session cookie just works and there is no CORS.

The backend **must stay running** (it polls job boards, checks mail and runs autopilot on a schedule), so it cannot live on Vercel itself.

> Single owner: this deployment has one password and one set of data. It is not a multi-user service.

---

## 0. Generate your secrets (on your PC, once)

```powershell
cd backend
.venv\Scripts\python.exe -m app.auth hash        # prompts for a password (12+ chars) → APP_PASSWORD_HASH
.venv\Scripts\python.exe -m app.auth secret      # → SESSION_SECRET
.venv\Scripts\python.exe -m app.auth fernet-key  # → TOKEN_ENCRYPTION_KEY
```
Keep these somewhere safe (a password manager). Never commit them. **Losing `TOKEN_ENCRYPTION_KEY` means reconnecting your mailboxes.**

## 1. Backend on Railway (similar steps on Fly.io / any Docker host)

1. https://railway.com → **New Project → Deploy from GitHub repo** → pick `JobFinder`. Railway finds the root `Dockerfile`.
2. In the project: **New → Database → PostgreSQL**.
3. Open the backend service → **Variables**:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference the database) |
   | `APP_PASSWORD_HASH` | from step 0 |
   | `SESSION_SECRET` | from step 0 |
   | `TOKEN_ENCRYPTION_KEY` | from step 0 |
   | `GEMINI_API_KEY` | your Gemini key |
   | `PUBLIC_URL` | your Vercel URL, e.g. `https://jobfinder.vercel.app` (set after step 2) |

   (`HOSTED=1`, `DATA_DIR=/data` and `MAX_UPLOAD_MB=4` are already baked into the image.)
4. **Settings → Volumes → add a volume mounted at `/data`.** Without it, uploaded resumes and generated documents are lost on every redeploy.
5. **Settings → Deploy → set replicas to 1.** The scheduler runs inside the process; two copies would duplicate work.
6. **Settings → Networking → Generate domain.** Copy the URL (e.g. `https://jobfinder-production.up.railway.app`). Check `https://…/healthz` returns `{"ok":true}`.

The server refuses to start if `APP_PASSWORD_HASH`, `SESSION_SECRET`, `DATABASE_URL` or `TOKEN_ENCRYPTION_KEY` is missing — a hosted instance can never run unprotected.

## 2. UI on Vercel

1. Edit `frontend/vercel.json` and replace `YOUR-BACKEND-URL` with the backend domain from step 1.6 (no `https://`, no trailing slash). Commit and push.
2. https://vercel.com → **Add New → Project → import `JobFinder`**.
3. **Root Directory: `frontend`**. Framework preset: Vite (auto-detected). Deploy.
4. Copy your Vercel URL and put it in the backend's `PUBLIC_URL` variable (step 1.3), then redeploy the backend.
5. Open the Vercel URL → sign in with your password.

## 3. Gmail / Outlook in hosted mode (optional)

Hosted mode uses a normal web sign-in redirect, so you need **Web** OAuth clients (different from the desktop ones in `SETUP_OAUTH.md`). Redirect URIs use your **Vercel** domain:

- **Google Cloud** → Credentials → OAuth client ID → type **Web application** →
  Authorised redirect URI: `https://<your-vercel-domain>/api/v1/email/gmail/callback`.
  Backend variables: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. (Keep the consent screen in *Testing* with yourself as a test user.)
- **Microsoft Entra** → App registration → Authentication → add platform **Web** →
  Redirect URI: `https://<your-vercel-domain>/api/v1/email/outlook/callback`. Certificates & secrets → New client secret.
  Backend variables: `MS_CLIENT_ID`, `MS_CLIENT_SECRET`. API permissions: `Mail.Read`, `User.Read`.

Then **Connections → Connect Gmail / Outlook** in the app.

## Limits and things to know

- **Upload size:** 4 MB per resume (Vercel's proxy limit is about 4.5 MB). Export large PDFs at lower quality if needed.
- **Backups:** Railway Postgres has snapshot/backup options — turn them on. The `/data` volume holds your original resumes; use **Settings → Export all data** for your own copy.
- **Privacy:** resume text, job descriptions and job-related email snippets are sent to Google's Gemini API, as in desktop mode. Mailbox access is read-only and can be revoked in your Google/Microsoft account.
- **Login protection:** passwords are verified against a scrypt hash, sessions are signed HttpOnly cookies (7 days), failed logins are rate-limited (5 per IP / 30 total per 15 minutes) and every login is in the audit log. Use a long, unique password.
- **Costs:** Railway and Vercel have free/low tiers, but an always-on container + Postgres + volume typically costs a few dollars a month. Gemini usage is billed separately.
- **Desktop app:** unaffected. It runs without a login and keeps data on your PC. The hosted instance has its own, separate data.
