from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import httpx
import asyncio
import os
import resend
from supabase import create_client

app = FastAPI()

# --- Supabase ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print(f"✅ Supabase connected: {SUPABASE_URL}")
else:
    print(f"❌ Supabase env vars missing — URL={SUPABASE_URL}, KEY={'set' if SUPABASE_KEY else 'missing'}")

# --- Resend ---
resend.api_key = os.environ.get("RESEND_API_KEY")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://staysharp-1010.netlify.app"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

# --- In-memory store ---
store = {}

def load_data():
    if not supabase:
        print("⚠️ Supabase not available, starting with empty store")
        return {}
    try:
        res = supabase.table("logs").select("*").execute()
        data = {row["date"]: {"log": row["log"], "settings": row["settings"], "saved_at": row["saved_at"]} for row in res.data}
        print(f"✅ Loaded {len(data)} rows from Supabase")
        return data
    except Exception as e:
        print(f"❌ load_data failed: {e}")
        return {}

def save_data_row(date, log, settings, saved_at):
    if not supabase:
        raise Exception("Supabase not configured — check SUPABASE_URL and SUPABASE_KEY in Railway")
    try:
        supabase.table("logs").upsert({
            "date": date,
            "log": log,
            "settings": settings,
            "saved_at": saved_at
        }).execute()
        print(f"✅ Saved row for {date}")
    except Exception as e:
        print(f"❌ save_data_row failed: {e}")
        raise

# --- Models ---
class HabitEntry(BaseModel):
    checked: bool
    mins: int = 0
    note: str = ""
    ref: str = ""

class DayLog(BaseModel):
    book: HabitEntry
    skill: HabitEntry
    proj: HabitEntry

class Settings(BaseModel):
    name: str = ""
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    deadline: str = "10pm"
    acc_email: str = ""

class SavePayload(BaseModel):
    date: str
    log: DayLog
    settings: Settings

# --- Routes ---
@app.get("/health")
async def health():
    return {
        "ok": True,
        "supabase": "connected" if supabase else "missing env vars",
        "resend": "configured" if resend.api_key else "missing",
        "store_rows": len(store)
    }

@app.get("/get-all")
async def get_all():
    """Return all logs — frontend uses this to sync on load from any device."""
    try:
        # Return flattened: { "2026-3-29": { book: {...}, skill: {...}, proj: {...} }, ... }
        result = {}
        for date, entry in store.items():
            result[date] = entry.get("log", {})
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/get-settings")
async def get_settings():
    """Return the most recently saved settings."""
    try:
        if not store:
            return {"ok": True, "settings": {}}
        # Get settings from the most recent date
        latest_date = sorted(store.keys())[-1]
        settings = store[latest_date].get("settings", {})
        return {"ok": True, "settings": settings}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/save")
async def save_day(payload: SavePayload):
    try:
        saved_at = datetime.utcnow().isoformat()
        log = payload.log.dict()
        settings = payload.settings.dict()
        save_data_row(payload.date, log, settings, saved_at)
        store[payload.date] = {"log": log, "settings": settings, "saved_at": saved_at}
        return {"ok": True}
    except Exception as e:
        print(f"❌ /save error: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/test-email")
async def test_email(payload: SavePayload):
    if not resend.api_key:
        return {"ok": False, "error": "API Key missing in Railway"}
    if not payload.settings.acc_email:
        return {"ok": False, "error": "No email provided"}
    try:
        resend.Emails.send({
            "from": "StaySharp <onboarding@resend.dev>",
            "to": payload.settings.acc_email,
            "subject": "🧪 Stay Sharp: Email Test",
            "html": f"<p>Success! Accountability email for <b>{payload.settings.name}</b> is working.</p>"
        })
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/trigger-check")
async def trigger_check():
    now = datetime.now()
    today_key = f"{now.year}-{now.month}-{now.day}"
    entry = store.get(today_key)

    if not entry:
        return {"ok": False, "error": "No data saved for today yet. Hit /save first."}

    settings = entry.get("settings", {})
    log = entry.get("log", {})
    habits = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
    missed = [name for key, name in habits.items() if not log.get(key, {}).get("checked", False)]

    if not missed:
        return {"ok": True, "message": "All habits done — no email sent."}

    acc_email = settings.get("acc_email")
    if acc_email and resend.api_key:
        resend.Emails.send({
            "from": "StaySharp <onboarding@resend.dev>",
            "to": acc_email,
            "subject": f"🚨 [TEST] Accountability Alert: {settings.get('name')} missed habits",
            "html": f"<p><b>[TEST RUN]</b> {settings.get('name')} missed: {', '.join(missed)}.</p>"
        })
        return {"ok": True, "missed": missed, "email_sent_to": acc_email}

    return {"ok": False, "error": "No email configured or Resend key missing."}

# --- Deadline Checker ---
DEADLINE_HOURS = {"8pm": 20, "9pm": 21, "10pm": 22, "11pm": 23, "midnight": 0}
notified_today = set()

async def deadline_checker():
    while True:
        now = datetime.now()
        today_key = f"{now.year}-{now.month}-{now.day}"
        entry = store.get(today_key)

        if entry:
            settings = entry.get("settings", {})
            log = entry.get("log", {})
            deadline_hour = DEADLINE_HOURS.get(settings.get("deadline", "10pm"), 22)
            habits = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
            missed = [name for key, name in habits.items() if not log.get(key, {}).get("checked", False)]

            if missed and now.hour == deadline_hour and today_key not in notified_today:
                notified_today.add(today_key)

                topic = settings.get("ntfy_topic")
                if topic:
                    try:
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"https://ntfy.sh/{topic}",
                                content=f"Missed: {', '.join(missed)}. Shame email sent.",
                                headers={"Title": "⚠️ Deadline Passed!", "Priority": "high", "Tags": "warning"}
                            )
                    except Exception as e:
                        print(f"ntfy failed: {e}")

                acc_email = settings.get("acc_email")
                if acc_email and resend.api_key:
                    try:
                        resend.Emails.send({
                            "from": "StaySharp <onboarding@resend.dev>",
                            "to": acc_email,
                            "subject": f"🚨 Accountability Alert: {settings.get('name')} missed habits",
                            "html": f"<p>This is an automated report. <b>{settings.get('name')}</b> failed to complete: {', '.join(missed)}.</p>"
                        })
                    except Exception as e:
                        print(f"Email failed: {e}")

        await asyncio.sleep(60)

@app.on_event("startup")
async def startup():
    global store
    store = load_data()
    asyncio.create_task(deadline_checker())
