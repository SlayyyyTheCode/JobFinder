# Connecting Gmail and Outlook

JobPilot reads your mailbox **read-only** to detect application confirmations, interview invitations, rejections and job-alert emails. Both providers require you to register your own (free) OAuth app, because JobPilot runs on your own computer. You only need to set up the providers you use.

---

## Gmail

1. Go to https://console.cloud.google.com/ and create a project (e.g. "JobPilot").
2. **APIs & Services → Library** → search **Gmail API** → **Enable**.
3. **APIs & Services → OAuth consent screen**
   - User type: **External** → Create.
   - App name: JobPilot; support email and developer email: your address.
   - **Scopes**: add `https://www.googleapis.com/auth/gmail.readonly`.
   - **Test users**: add the Gmail address you will connect.
   - Leave the app in **Testing** mode (fine for personal use; refresh tokens last 7 days in testing, after which JobPilot will ask you to reconnect).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app** → Create → **Download JSON**.
5. Save the JSON somewhere private (e.g. `C:\Users\<you>\jobpilot\client_secret.json`) and set in `.env`:
   ```
   GOOGLE_CLIENT_SECRETS_FILE=C:\Users\<you>\jobpilot\client_secret.json
   ```
6. Restart JobPilot → **Connections → Connect Gmail**. A browser window opens; approve read-only access.

> Google will show "Google hasn't verified this app" — this is expected for your own personal app. Click **Continue**.

---

## Outlook / Hotmail / Microsoft 365

1. Go to https://entra.microsoft.com/ → **Applications → App registrations → New registration**.
   (Personal Hotmail/Outlook.com accounts can sign in to the Entra portal and create registrations.)
2. Name: JobPilot. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**.
3. Redirect URI: platform **Public client/native (mobile & desktop)**, value `http://localhost` → **Register**.
4. On the app's **Authentication** page, set **Allow public client flows** to **Yes** → Save.
5. **API permissions → Add a permission → Microsoft Graph → Delegated** → add `Mail.Read` and `User.Read`.
6. Copy the **Application (client) ID** from the Overview page into `.env`:
   ```
   MS_CLIENT_ID=00000000-0000-0000-0000-000000000000
   ```
7. Restart JobPilot → **Connections → Connect Outlook / Hotmail** and approve.

---

## What JobPilot does with your mail

- Requests only read-only scopes (`gmail.readonly` / `Mail.Read`).
- Looks at messages from the last 21 days on first connect, then only new ones.
- Skips messages that don't look job-related (keyword and recruiting-system sender filter) — those are never sent to the AI model.
- For job-related messages, sends only sender, subject and preview snippet to the model for classification. For job-alert emails, the body is read in memory to extract job links, then discarded.
- Stores only: message id, sender, subject, detected event type, company, role and confidence. Never full bodies.
- Tokens are encrypted; the encryption key is kept in Windows Credential Manager.
- **Disconnect** deletes the local tokens. To revoke fully, also remove JobPilot at https://myaccount.google.com/permissions or https://account.live.com/consent/Manage.

## Job boards without APIs

LinkedIn, Indeed and JobStreet don't allow automated access. Create job alerts on those sites, delivered to the mailbox you connect — JobPilot will pick up the alert emails and add the jobs to **Discover**. Open each one and paste the full description to score and tailor it.
