from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import httpx
import asyncio
import os
import resend
from supabase import create_client

app = FastAPI()

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print(f"✅ Supabase connected: {SUPABASE_URL}")
else:
    print("⚠️  Supabase not configured — using in-memory store only")

# ── Resend (email) ────────────────────────────────────────────────────────────
resend.api_key = os.environ.get("RESEND_API_KEY", "")

# ── Twilio (WhatsApp) ─────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WA_NUMBER   = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    from twilio.rest import Client as TwilioClient
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    print("✅ Twilio WhatsApp configured")
else:
    print("⚠️  Twilio not configured — WhatsApp alerts disabled")

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # lock down to your GitHub Pages URL in production
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

# ── In-memory store ───────────────────────────────────────────────────────────
store: dict = {}

# Sensitive config — lives ONLY on the server, never sent to public frontend
server_settings: dict = {
    "name": "",
    "acc_email": "",
    "whatsapp_number": "",
    "ntfy_topic": os.environ.get("NTFY_TOPIC", ""),
    "ntfy_server": os.environ.get("NTFY_SERVER", "https://ntfy.sh"),
    "deadline": "10pm",
    "ninety_day_start": "",
}


# ── DB helpers ────────────────────────────────────────────────────────────────
def load_data():
    if not supabase:
        return {}
    try:
        res = supabase.table("logs").select("*").execute()
        data = {
            row["date"]: {
                "log": row["log"],
                "settings": row.get("settings", {}),
                "saved_at": row["saved_at"],
            }
            for row in res.data
        }
        # Also restore server_settings from latest row
        if data:
            latest = sorted(data.keys())[-1]
            s = data[latest].get("settings", {})
            for k in ("name","acc_email","whatsapp_number","ntfy_topic","ntfy_server","deadline","ninety_day_start"):
                if s.get(k):
                    server_settings[k] = s[k]
        print(f"✅ Loaded {len(data)} rows from Supabase")
        return data
    except Exception as e:
        print(f"❌ load_data failed: {e}")
        return {}


def save_data_row(date: str, log: dict, settings: dict, saved_at: str):
    if not supabase:
        return  # in-memory only
    try:
        supabase.table("logs").upsert({
            "date": date, "log": log, "settings": settings, "saved_at": saved_at
        }).execute()
    except Exception as e:
        print(f"❌ save_data_row: {e}")


# ── Models ────────────────────────────────────────────────────────────────────
class HabitEntry(BaseModel):
    checked: bool
    mins: int = 0
    note: str = ""
    ref: str = ""
    category: Optional[str] = ""
    energy: Optional[int] = 5
    one_min_decision: Optional[str] = ""
    reflection: Optional[str] = ""
    vocal_drills: Optional[dict] = {}
    nonvocal_drills: Optional[dict] = {}


class DayLog(BaseModel):
    book: HabitEntry
    skill: HabitEntry
    proj: HabitEntry
    daily_reflection: Optional[str] = ""
    ninety_day_start: Optional[str] = ""


class PublicSettings(BaseModel):
    """Only non-sensitive fields come from the public tracker page."""
    name: str = ""
    deadline: str = "10pm"
    ninety_day_start: Optional[str] = ""


class SavePayload(BaseModel):
    date: str
    log: DayLog
    settings: PublicSettings


class PrivateSettings(BaseModel):
    """Full settings — only accepted from the password-gated dashboard."""
    name: str = ""
    acc_email: str = ""
    whatsapp_number: str = ""
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    deadline: str = "10pm"
    ninety_day_start: Optional[str] = ""


class TriggerPayload(BaseModel):
    missed: list[str] = []


# ── Notification helpers ───────────────────────────────────────────────────────
async def send_ntfy(title: str, body: str, priority: str = "default", tags: str = ""):
    topic = server_settings.get("ntfy_topic", "")
    server = (server_settings.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
    if not topic:
        return
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{server}/{topic}", content=body, headers=headers, timeout=5)
    except Exception as e:
        print(f"ntfy failed: {e}")


def send_whatsapp(message: str):
    if not twilio_client:
        return
    num = server_settings.get("whatsapp_number", "")
    if not num:
        return
    try:
        twilio_client.messages.create(
            from_=TWILIO_WA_NUMBER,
            body=message,
            to=f"whatsapp:{num}" if not num.startswith("whatsapp:") else num,
        )
        print(f"✅ WhatsApp sent to {num}")
    except Exception as e:
        print(f"❌ WhatsApp failed: {e}")


def send_email(subject: str, html: str):
    email = server_settings.get("acc_email", "")
    if not email or not resend.api_key:
        return
    try:
        resend.Emails.send({
            "from": "StaySharp <onboarding@resend.dev>",
            "to": email,
            "subject": subject,
            "html": html,
        })
        print(f"✅ Email sent to {email}")
    except Exception as e:
        print(f"❌ Email failed: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "Stay Sharp backend running", "rows": len(store)}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "supabase": "connected" if supabase else "in-memory",
        "resend": "configured" if resend.api_key else "missing",
        "twilio": "configured" if twilio_client else "missing",
        "ntfy_topic": "set" if server_settings.get("ntfy_topic") else "not set",
        "store_rows": len(store),
    }


@app.get("/get-all")
async def get_all():
    try:
        return {"ok": True, "data": {k: v.get("log", {}) for k, v in store.items()}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/get-settings")
async def get_settings():
    """Returns only non-sensitive settings to the frontend."""
    return {
        "ok": True,
        "settings": {
            "deadline": server_settings.get("deadline", "10pm"),
            "ninety_day_start": server_settings.get("ninety_day_start", ""),
            "name": server_settings.get("name", ""),
        },
    }


@app.post("/save")
async def save_day(payload: SavePayload):
    """Called by public tracker — only receives non-sensitive fields."""
    try:
        saved_at = datetime.utcnow().isoformat()
        log = payload.log.dict()
        # Merge public settings (deadline, name) into server_settings
        if payload.settings.deadline:
            server_settings["deadline"] = payload.settings.deadline
        if payload.settings.name:
            server_settings["name"] = payload.settings.name
        if payload.settings.ninety_day_start:
            server_settings["ninety_day_start"] = payload.settings.ninety_day_start

        # Store only public settings alongside log
        public_sett = {
            "deadline": server_settings["deadline"],
            "name": server_settings["name"],
            "ninety_day_start": server_settings.get("ninety_day_start", ""),
        }
        save_data_row(payload.date, log, public_sett, saved_at)
        store[payload.date] = {"log": log, "settings": public_sett, "saved_at": saved_at}
        return {"ok": True}
    except Exception as e:
        print(f"❌ /save error: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/update-settings")
async def update_settings(payload: PrivateSettings):
    """Called ONLY from password-gated dashboard. Stores sensitive info server-side."""
    try:
        server_settings.update({
            "name": payload.name,
            "acc_email": payload.acc_email,
            "whatsapp_number": payload.whatsapp_number,
            "ntfy_topic": payload.ntfy_topic,
            "ntfy_server": payload.ntfy_server or "https://ntfy.sh",
            "deadline": payload.deadline,
            "ninety_day_start": payload.ninety_day_start or "",
        })
        print(f"✅ Server settings updated for {payload.name}")
        return {"ok": True}
    except Exception as e:
        print(f"❌ /update-settings error: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/trigger-notify")
async def trigger_notify(payload: TriggerPayload):
    """Called by browser when deadline is past and habits missed."""
    missed = payload.missed
    name = server_settings.get("name") or "You"
    habit_labels = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
    missed_names = [habit_labels.get(h, h) for h in missed] if missed else []

    msg = f"⚠️ {name} missed: {', '.join(missed_names)}. Get it done!" if missed_names else f"⚠️ {name} is behind on habits today."

    await send_ntfy("Stay Sharp: Deadline Alert", msg, priority="high", tags="warning")
    send_whatsapp(f"🚨 *Stay Sharp*\n\n{msg}")
    send_email(
        subject=f"🚨 Accountability Alert: {name} missed habits",
        html=f"<p><b>{name}</b> failed to complete: {', '.join(missed_names) or 'habits'}.</p><p>Sent automatically by Stay Sharp.</p>"
    )
    return {"ok": True, "notified": True}


@app.post("/notify-timer")
async def notify_timer():
    """Called when 5-minute timer completes."""
    name = server_settings.get("name") or "You"
    await send_ntfy("⚡ 5 minutes done!", f"{name} started. Now keep going.", priority="3", tags="tada")
    return {"ok": True}


@app.post("/trigger-check")
async def trigger_check():
    """Manual test endpoint."""
    now = datetime.now()
    today_key = f"{now.year}-{now.month}-{now.day}"
    entry = store.get(today_key)
    if not entry:
        return {"ok": False, "error": "No data saved for today yet"}
    log = entry.get("log", {})
    habits = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
    missed = [name for key, name in habits.items() if not log.get(key, {}).get("checked", False)]
    if not missed:
        return {"ok": True, "message": "All habits done"}
    return {"ok": True, "missed": missed}


# ── Deadline checker (server-side) ────────────────────────────────────────────
DEADLINE_HOURS = {"8pm": 20, "9pm": 21, "10pm": 22, "11pm": 23, "midnight": 0}
notified_today: set = set()


async def deadline_checker():
    while True:
        now = datetime.now()
        today_key = f"{now.year}-{now.month}-{now.day}"
        entry = store.get(today_key)
        if entry:
            deadline = server_settings.get("deadline", "10pm")
            deadline_hour = DEADLINE_HOURS.get(deadline, 22)
            log = entry.get("log", {})
            habits = {"book": "📚 Reading", "skill": "🗣 Soft Skills", "proj": "💻 Side Project"}
            missed = [name for key, name in habits.items() if not log.get(key, {}).get("checked", False)]

            if missed and now.hour == deadline_hour and today_key not in notified_today:
                notified_today.add(today_key)
                name = server_settings.get("name") or "You"
                msg = f"⚠️ {name}, deadline passed! Missed: {', '.join(missed)}."

                await send_ntfy("Stay Sharp: Deadline Passed!", msg, priority="high", tags="warning")
                send_whatsapp(f"🚨 *Stay Sharp*\n\n{msg}")
                send_email(
                    subject=f"🚨 Accountability Alert: {name} missed habits",
                    html=f"<p>This is an automated report. <b>{name}</b> failed to complete: {', '.join(missed)}.</p>"
                )

        await asyncio.sleep(60)


@app.on_event("startup")
async def startup():
    global store
    store = load_data()
    asyncio.create_task(deadline_checker())
    print("🚀 Stay Sharp backend started")
