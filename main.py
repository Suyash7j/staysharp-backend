from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, date, timedelta
import httpx
import asyncio
import json
import os
import resend

app = FastAPI()
# Add to requirements.txt:
# supabase

from supabase import create_client
import os

# Replace the load_data/save_data setup with this:
supabase = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)

# Replace load_data()
def load_data():
    res = supabase.table("logs").select("*").execute()
    return {row["date"]: row for row in res.data}

# Replace save_data()
def save_data_row(date, log, settings, saved_at):
    supabase.table("logs").upsert({
        "date": date,
        "log": log,
        "settings": settings,
        "saved_at": saved_at
    }).execute()
    
# 1. SECURITY: Only allow your Netlify frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://staysharp-1010.netlify.app"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

# 2. CREDENTIALS: Set via Railway Environment Variables
resend.api_key = os.environ.get("RESEND_API_KEY")
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

store = load_data()

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
@app.post("/save")
async def save_day(payload: SavePayload):
    save_data_row(
        date=payload.date,
        log=payload.log.dict(),
        settings=payload.settings.dict(),
        saved_at=datetime.utcnow().isoformat()
    )
    # Keep this for in-memory access by deadline_checker
    store[payload.date] = {
        "log": payload.log.dict(),
        "settings": payload.settings.dict(),
        "saved_at": datetime.utcnow().isoformat()
    }
    return {"ok": True}


@app.post("/test-email")
async def test_email(payload: SavePayload):
    settings = payload.settings
    acc_email = settings.acc_email
    
    if not resend.api_key:
        return {"ok": False, "error": "API Key missing in Railway"}
    if not acc_email:
        return {"ok": False, "error": "No email provided"}

    try:
        resend.Emails.send({
            "from": "StaySharp <onboarding@resend.dev>",
            "to": "stevens032093@gmail.com",
            "subject": "🧪 Stay Sharp: Email Test",
            "html": f"<p>Success! Your accountability email for <b>{settings.name}</b> is working.</p>"
        })
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def deadline_checker():
    while True:
        now = datetime.now()
        # Ensure key matches your frontend format (YYYY-M-D)
        today_key = f"{now.year}-{now.month}-{now.day}"
        
        if now.minute == 0: # Only check at the top of every minute
            entry = store.get(today_key)
            if entry:
                settings = entry.get("settings", {})
                log = entry.get("log", {})
                deadline_hour = DEADLINE_HOURS.get(settings.get("deadline", "10pm"), 22)

                # Identify missed habits
                habits = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
                missed = [name for key, name in habits.items() if not log.get(key, {}).get("checked", False)]

                if missed and now.hour == deadline_hour:
                    # A. Send ntfy Push Alert
                    topic = settings.get("ntfy_topic")
                    if topic:
                        try:
                            async with httpx.AsyncClient() as client:
                                await client.put(
                                    f"https://ntfy.sh/{topic}",
                                    content=f"Missed: {', '.join(missed)}. Shame email sent.",
                                    headers={"Title": "⚠️ Deadline Passed!", "Priority": "high", "Tags": "warning"}
                                )
                        except Exception as e: print(f"ntfy failed: {e}")

                    # B. Auto-Send Shame Email via Resend
                    acc_email = settings.get("acc_email")
                    if acc_email and resend.api_key:
                        try:
                            resend.Emails.send({
                                "from": "StaySharp <onboarding@resend.dev>",
                                "to": acc_email,
                                "subject": f"🚨 Accountability Alert: {settings.get('name')} missed habits",
                                "html": f"<p>This is an automated report. <b>{settings.get('name')}</b> failed to complete: {', '.join(missed)}.</p>"
                            })
                        except Exception as e: print(f"Email failed: {e}")

        await asyncio.sleep(60)

@app.on_event("startup")
async def startup():
    global store
    store = load_data()  # now loads from Supabase
    asyncio.create_task(deadline_checker())