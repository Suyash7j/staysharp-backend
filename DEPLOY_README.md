# Stay Sharp — Deployment Guide

## File Structure

```
staysharp/
├── index.html          ← Daily habit tracker (public)
├── landing.html        ← Homepage (public)
├── dashboard.html      ← Password-gated analytics + settings
├── main.py             ← FastAPI backend
├── requirements.txt    ← Python dependencies
├── Procfile            ← Railway/Render process file
├── railway.toml        ← Railway config
└── netlify.toml        ← Netlify config
```

---

## Security Architecture

**Sensitive data (ntfy topic, WhatsApp number, email) is NEVER rendered on public pages.**

| Where | What's visible |
|---|---|
| `index.html` (public tracker) | Habit log, deadline selector, streaks |
| `dashboard.html` (password-gated) | Everything above + notification settings |
| Backend env vars | ntfy topic, WhatsApp, email at startup |
| Backend memory | All settings after `/update-settings` is called |

Flow:
1. User opens `dashboard.html` → enters password → sees settings form
2. User fills in ntfy/email/WhatsApp → clicks Save → goes to `/update-settings`
3. Backend stores secrets in server memory (never returned to public frontend)
4. Public tracker only sends: `deadline`, `name`, `ninety_day_start`
5. Notifications triggered server-side or via `/trigger-notify` from browser

---

## Step 1 — Deploy Frontend

**Option A: GitHub Pages**
1. Push all files to a GitHub repo
2. Settings → Pages → Deploy from `main` branch, root `/`
3. Live at `https://yourusername.github.io/staysharp`

**Option B: Netlify Drop**
1. Go to `netlify.com/drop`
2. Drag the whole `staysharp/` folder
3. Instant live URL

---

## Step 2 — Deploy Backend to Railway (Free)

1. Go to `railway.app` → Sign up with GitHub
2. New Project → Deploy from GitHub repo
3. Select your repo
4. Railway auto-detects `Procfile` and deploys

**Set Environment Variables in Railway dashboard:**

```
SUPABASE_URL          = your_supabase_url
SUPABASE_KEY          = your_supabase_key
RESEND_API_KEY        = your_resend_key
TWILIO_ACCOUNT_SID    = your_twilio_sid
TWILIO_AUTH_TOKEN     = your_twilio_token
TWILIO_WHATSAPP_NUMBER = whatsapp:+14155238886
NTFY_TOPIC            = your-secret-topic-name
NTFY_SERVER           = https://ntfy.sh
```

5. Settings → Domains → Generate Domain
6. Copy the URL (e.g. `https://staysharp-production.up.railway.app`)

---

## Step 3 — Connect Frontend to Backend

In `index.html` and `dashboard.html`, find:
```javascript
const BACKEND_URL = 'https://staysharp-backend-production.up.railway.app';
```
Replace with your Railway URL.

---

## Step 4 — Setup WhatsApp (Free Twilio Sandbox)

1. Go to `twilio.com/console` — sign up free (no credit card)
2. Navigate to Messaging → Try it out → Send a WhatsApp message
3. Follow sandbox join instructions (text `join <code>` to the sandbox number)
4. Copy Account SID, Auth Token → add to Railway env vars
5. Sandbox number is `+14155238886` (or check your console)

---

## Step 5 — Setup ntfy (Free Push Notifications)

1. Install **ntfy** app: iOS App Store / Android Play Store
2. Subscribe to your chosen topic name
3. Set the topic in Dashboard → Notification Settings
4. Click "Test ntfy" to verify

---

## Step 6 — Change the Dashboard Password

In `dashboard.html`, find:
```javascript
const PASS = "staysharp2025";
```
Change this to your own password before committing.

---

## Step 7 — Setup Supabase (Free DB)

1. Go to `supabase.com` → New project
2. Create a table called `logs` with columns:
   - `date` TEXT PRIMARY KEY
   - `log` JSONB
   - `settings` JSONB
   - `saved_at` TEXT
3. Copy Project URL and anon key → add to Railway env vars

---

## Verify Backend

```
GET  https://your-url.up.railway.app/
→ {"status": "Stay Sharp backend running", "rows": 0}

GET  https://your-url.up.railway.app/health
→ {"ok": true, "supabase": "connected", "twilio": "configured", ...}
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Backend deploy fails | Ensure `requirements.txt` has all packages including `twilio` |
| CORS errors | Backend allows all origins — check BACKEND_URL in HTML files |
| ntfy not firing | Check topic name matches in Dashboard settings |
| WhatsApp not sending | Verify you've joined sandbox; check Twilio env vars |
| Dashboard won't unlock | Default password is `staysharp2025` — check `dashboard.html` |
| Data not persisting | Set SUPABASE_URL and SUPABASE_KEY env vars |
