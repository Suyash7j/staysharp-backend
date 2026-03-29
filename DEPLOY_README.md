# Stay Sharp — Deployment Guide

## What you have

```
staysharp/
├── backend/
│   ├── main.py          ← FastAPI server (deadline checker + ntfy)
│   ├── requirements.txt
│   └── Procfile
└── accountability.html  ← Your tracker webpage
```

---

## Step 1 — Deploy backend to Railway (free, ~3 minutes)

1. Go to **railway.app** → Sign up with GitHub (free)
2. Click **"New Project"** → **"Deploy from GitHub repo"**
   - Or use **"Deploy from local"** and drag the `backend/` folder
3. Railway auto-detects the Procfile and starts the server
4. Click your project → **Settings** → **Domains** → **"Generate Domain"**
5. Copy your URL — looks like: `https://staysharp-production.up.railway.app`

> Railway free tier gives you $5/month credit — more than enough for this lightweight server.

---

## Step 2 — Connect your frontend to the backend

Open `accountability.html` in a browser, then run this in the browser console:

```javascript
localStorage.setItem('staysharp_backend', 'https://YOUR-RAILWAY-URL.up.railway.app')
```

That's it. Now every time you hit "Lock In Today", your data gets pushed to the server.
The server checks every minute and fires ntfy when your deadline passes.

---

## Step 3 — Host the frontend (optional, for a real URL)

**Easiest: Netlify Drop**
1. Go to **netlify.com/drop**
2. Drag and drop `accountability.html`
3. You get a live URL like `https://warm-sunshine-abc123.netlify.app`
4. Bookmark it on your phone home screen for app-like access

**Or: GitHub Pages**
1. Create a GitHub repo → upload `accountability.html` as `index.html`
2. Settings → Pages → Deploy from main branch
3. Live at `https://yourusername.github.io/staysharp`

---

## How the deadline check works (server-side)

- Server runs a background loop checking every **60 seconds**
- When `current_hour >= deadline_hour` and any habit is unchecked → fires ntfy
- Only fires **once per day** per topic (won't spam you)
- Works even when your browser/laptop is completely off

---

## Verify it's working

Hit your Railway URL in the browser:
```
https://your-url.up.railway.app/
→ {"status": "Stay Sharp backend running"}

https://your-url.up.railway.app/streak
→ {"all": 3, "book": 5, "skill": 3, "proj": 3}
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Railway deploy fails | Make sure Procfile and requirements.txt are in the root of what you upload |
| ntfy not firing | Check topic name matches exactly between app and webpage |
| CORS error in browser | Already handled — backend allows all origins |
| Data persists? | Saves to data.json on disk; persists between Railway restarts |
