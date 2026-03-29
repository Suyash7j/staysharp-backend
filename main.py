from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import httpx
import asyncio
import json
import os

app = FastAPI()

# In your staysharp-backend/main.py
# Updated CORS section in main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://staysharp-1010.netlify.app"], # Only your site can talk to this API
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],      # Added PUT and OPTIONS
    allow_headers=["*"],
)

# Updated ntfy call in deadline_checker
try:
    async with httpx.AsyncClient() as client:
        await client.put( # Switched to PUT
            f"{ntfy_server}/{ntfy_topic}",
            content=f"Missed today: {missed_str}. Deadline passed — get it done.",
            headers={
                "Title": f"⚠️ {name}, you slipped today",
                "Priority": "high",
                "Tags": "warning"
            }
        )
    print(f"[{now.isoformat()}] Fired ntfy for {today_key}")
    notified_today.add(today_key)
except Exception as e:
    print(f"ntfy error: {e}")

# In-memory store (persists while server is running)
# For true persistence across restarts, this writes to a JSON file too
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
    deadline: str = "10pm"  # "8pm" | "9pm" | "10pm" | "11pm" | "midnight"
    acc_email: str = ""

class SavePayload(BaseModel):
    date: str           # "YYYY-M-D"
    log: DayLog
    settings: Settings

# --- Routes ---

@app.get("/")
def root():
    return {"status": "Stay Sharp backend running"}

@app.post("/save")
async def save_day(payload: SavePayload):
    store[payload.date] = {
        "log": payload.log.dict(),
        "settings": payload.settings.dict(),
        "saved_at": datetime.utcnow().isoformat()
    }
    save_data(store)
    return {"ok": True, "date": payload.date}

@app.get("/log/{date_str}")
def get_log(date_str: str):
    entry = store.get(date_str)
    if not entry:
        raise HTTPException(status_code=404, detail="No log for this date")
    return entry

@app.get("/streak")
def get_streak():
    habits = ["book", "skill", "proj"]
    today = date.today()
    streaks = {h: 0 for h in habits}
    streaks["all"] = 0

    # Overall streak
    for i in range(365):
        from datetime import timedelta
        d = today - timedelta(days=i)
        key = f"{d.year}-{d.month}-{d.day}"
        entry = store.get(key, {}).get("log", {})
        all_done = all(entry.get(h, {}).get("checked", False) for h in habits)
        if all_done:
            streaks["all"] += 1
        elif i > 0:
            break

    for h in habits:
        for i in range(365):
            from datetime import timedelta
            d = today - timedelta(days=i)
            key = f"{d.year}-{d.month}-{d.day}"
            entry = store.get(key, {}).get("log", {})
            if entry.get(h, {}).get("checked", False):
                streaks[h] += 1
            elif i > 0:
                break

    return streaks

# --- Deadline checker (runs as background task) ---

DEADLINE_HOURS = {
    "8pm": 20, "9pm": 21, "10pm": 22, "11pm": 23, "midnight": 0
}

notified_today = set()  # tracks which dates we already fired for
# Updated in main.py
    while True:
        await asyncio.sleep(60)  # check every minute
        now = datetime.now()
        today = date.today()
        today_key = f"{today.year}-{today.month}-{today.day}"

        if today_key in notified_today:
            continue

        # Get today's settings (from latest save)
        entry = store.get(today_key, {})
        settings = entry.get("settings", {})
        ntfy_topic = settings.get("ntfy_topic", "")
        ntfy_server = settings.get("ntfy_server", "https://ntfy.sh")
        deadline_str = settings.get("deadline", "10pm")
        name = settings.get("name", "You")

        if not ntfy_topic:
            continue

        deadline_hour = DEADLINE_HOURS.get(deadline_str, 22)
        if now.hour < deadline_hour:
            continue

        # Check what's missed
        log = entry.get("log", {})
        habits = ["book", "skill", "proj"]
        habit_names = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
        missed = [h for h in habits if not log.get(h, {}).get("checked", False)]

        if not missed:
            notified_today.add(today_key)
            continue

        # Fire ntfy
        missed_str = ", ".join(habit_names[h] for h in missed)
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{ntfy_server}/{ntfy_topic}",
                    content=f"Missed today: {missed_str}. Deadline passed — get it done.",
                    headers={
                        "Title": f"⚠️ {name}, you slipped today",
                        "Priority": "high",
                        "Tags": "warning"
                    }
                )
            print(f"[{now.isoformat()}] Fired ntfy for {today_key}: {missed_str}")
            notified_today.add(today_key)
        except Exception as e:
            print(f"ntfy error: {e}")
import resend

# 1. Set your API Key (Get this from resend.com)
resend.api_key = os.environ.get("RESEND_API_KEY")

async def deadline_checker():
    while True:
        now = datetime.now()
        today_key = now.date().isoformat()
        
        for user_id, entry in store.items():
            settings = entry.get("settings", {})
            deadline_hour = DEADLINE_HOURS.get(settings.get("deadline", "10pm"), 22)
            
            # Only trigger exactly at the deadline hour/minute
            if now.hour == deadline_hour and now.minute == 0:
                log = entry.get("log", {}).get(today_key, {})
                missed = [h for h in ["book", "skill", "proj"] if not log.get(h, {}).get("checked", False)]
                
                if missed:
                    # AUTOSEND LOGIC
                    try:
                        resend.Emails.send({
                            "from": "StaySharp <onboarding@resend.dev>",
                            "to": settings.get("acc_email"),
                            "subject": f"⚠️ Accountability Report: {settings.get('name')} missed habits",
                            "html": f"<p>This is an automated report. {settings.get('name')} failed to complete: {', '.join(missed)}.</p>"
                        })
                        print(f"Shame email autosent to {settings.get('acc_email')}")
                    except Exception as e:
                        print(f"Email failed: {e}")
        
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup():
    asyncio.create_task(deadline_checker())
