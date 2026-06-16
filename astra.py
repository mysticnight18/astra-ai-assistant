#!/usr/bin/env python3
"""
Astra v4.1 — Your Personal Voice AI Assistant
═══════════════════════════════════════════════════
New in v4.0:
  ✅ Persistent Memory   — auto-save facts, preferences, dates; recall anytime
  ✅ Conversation Context — follow-up questions (e.g. "what about tomorrow?")
  ✅ Plugin System        — plugins/ folder; easy to add/remove features
  ✅ Voice Profiles       — professional / friendly / JARVIS / minimal (auto + manual)
  ✅ Better Error Recovery — internet monitor, mic reconnect, retry logic
  ✅ WhatsApp Fix         — improved UI automation that actually sends messages
v4.1:
  ✅ Gemini Fix           — new google-genai SDK, gemini-2.5-flash

Project layout:
  astra.py             ← this file
  memory/
    memory_manager.py  ← persistent JSON memory
    context.py         ← per-session conversation context
  plugins/
    weather.py         ← weather plugin
    messaging.py       ← WhatsApp + iMessage (fixed)
    voice_profiles.py  ← voice profile system
    error_recovery.py  ← internet/mic/retry helpers
"""

import os
import subprocess
import threading
import time
import datetime
import sys
import json
import urllib.request
import urllib.parse
import re
import traceback
import numpy as np
import rumps
import speech_recognition as sr

# ── Add project root to path so plugins/memory are importable ─────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Gemini — new google-genai SDK (pip install google-genai) ─────────────────
try:
    from google import genai as _genai_mod
    _GENAI_AVAILABLE = True
except ImportError:
    _genai_mod = None
    _GENAI_AVAILABLE = False

import openwakeword
from openwakeword.model import Model as WakeModel

# ── Memory + plugins ──────────────────────────────────────────────────────────
from memory import (
    remember, recall, forget,
    try_auto_remember, try_auto_recall, try_auto_forget,
    push as ctx_push, build_context_block, last_city
)
from plugins import dispatch as plugin_dispatch
import plugins.voice_profiles as vp
import plugins.error_recovery as er


# ══════════════════════════════════════════════
#  CONFIG  (edit these)
# ══════════════════════════════════════════════
USER_NAME        = "User"   # ← change this to your name
CITY             = "Mumbai"  # ← change this to your city
COUNTRY_CODE     = "IN"
WEATHER_API_KEY  = "2306a9e13291e5a915ae450ba44e8fcd"

# ── Gemini API key rotation pool ─────────────────────────────────────────────
# Keys are tried in order. When one hits quota, Astra silently moves to the next.
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY", ""),          # env var takes priority
    # "YOUR_API_KEY_HERE",                          # add backup keys here if needed
]
# Remove empty entries (e.g. if env var not set)
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k.strip()]
GEMINI_API_KEY  = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
_key_index      = 0   # currently active key index

if not GEMINI_API_KEYS:
    print("⚠️  No Gemini API keys configured. Gemini features disabled.")

WAKE_THRESHOLD   = 0.35
VERIFIER_PATH    = os.path.join(_ROOT, "hey_astra_verifier.joblib")

# Inject weather key into weather plugin
import plugins.weather as _wp_mod
_wp_mod.WEATHER_API_KEY = WEATHER_API_KEY
_wp_mod.DEFAULT_CITY    = CITY
_wp_mod.COUNTRY_CODE    = COUNTRY_CODE


# ══════════════════════════════════════════════
#  CRASH GUARD
# ══════════════════════════════════════════════
def _safe_thread(name: str, fn, *args, restart: bool = True, delay: float = 2.0):
    def _wrapper():
        while True:
            try:
                fn(*args)
            except Exception as e:
                print(f"⚠️  Thread '{name}' crashed: {e}")
                traceback.print_exc()
                if not restart:
                    break
                print(f"   Restarting '{name}' in {delay}s…")
                time.sleep(delay)
    t = threading.Thread(target=_wrapper, name=name, daemon=True)
    t.start()
    return t


# ══════════════════════════════════════════════
#  SPEAK  — uses active voice profile
# ══════════════════════════════════════════════
_speak_proc = None
_speak_lock = threading.Lock()


def speak(text: str, blocking: bool = False):
    global _speak_proc
    print(f"🔊 Astra: {text}")
    say_args = vp.get_say_args()
    with _speak_lock:
        try:
            if _speak_proc and _speak_proc.poll() is None:
                _speak_proc.terminate()
                _speak_proc.wait(timeout=0.3)
        except Exception:
            pass
        try:
            cmd = ["say"] + say_args + [text]
            if blocking:
                subprocess.run(cmd, timeout=30)
            else:
                _speak_proc = subprocess.Popen(cmd)
        except Exception as e:
            print(f"Speak error: {e}")


# ══════════════════════════════════════════════
#  NOTIFY
# ══════════════════════════════════════════════
def notify(title: str, msg: str):
    try:
        script = f'display notification "{msg}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], timeout=3, check=False)
    except Exception:
        pass


# ══════════════════════════════════════════════
#  APP / URL CONTROL
# ══════════════════════════════════════════════
def open_app(name: str) -> bool:
    try:
        r = subprocess.run(["open", "-a", name], capture_output=True, timeout=10)
        if r.returncode != 0:
            speak(f"Couldn't find {name}.")
            return False
        return True
    except Exception as e:
        print(f"open_app error: {e}")
        return False


def close_app(name: str):
    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{name}" to quit'],
            check=False, timeout=5
        )
    except Exception as e:
        print(f"close_app error: {e}")


def open_url(url: str):
    try:
        subprocess.run(["open", url], check=False, timeout=5)
    except Exception as e:
        print(f"open_url error: {e}")


def run_as(script: str):
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=8)
    except Exception as e:
        print(f"AppleScript error: {e}")


# ══════════════════════════════════════════════
#  SPOTIFY
# ══════════════════════════════════════════════
_spotify_lock = threading.Lock()


def _spotify_state() -> str:
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to (name of processes) contains "Spotify"'],
            capture_output=True, timeout=3
        )
        if b"false" in r.stdout.lower():
            return "closed"
        r2 = subprocess.run(
            ["osascript", "-e", 'tell application "Spotify" to player state as string'],
            capture_output=True, timeout=3
        )
        state = r2.stdout.decode().strip().lower()
        if "playing" in state:
            return "playing"
        elif "paused" in state:
            return "paused"
        else:
            return "stopped"
    except Exception:
        return "unknown"


def _spotify_ensure_open():
    if _spotify_state() == "closed":
        open_app("Spotify")
        for _ in range(20):
            time.sleep(0.5)
            if _spotify_state() != "closed":
                time.sleep(1.5)
                return


def spotify_play():
    with _spotify_lock:
        _spotify_ensure_open()
        state = _spotify_state()
        if state == "playing":
            speak("Already playing.")
            return
        run_as('tell application "Spotify" to play')
        time.sleep(0.5)
        if _spotify_state() != "playing":
            time.sleep(1)
            run_as('tell application "Spotify" to play')
        speak("Playing.")


def spotify_pause():
    with _spotify_lock:
        if _spotify_state() in ("closed", "paused"):
            speak("Not playing." if _spotify_state() == "closed" else "Already paused.")
            return
        run_as('tell application "Spotify" to pause')
        speak("Paused.")


def spotify_next():
    with _spotify_lock:
        if _spotify_state() == "closed":
            speak("Spotify isn't open.")
            return
        run_as('tell application "Spotify" to next track')
        speak("Next track.")


def spotify_prev():
    with _spotify_lock:
        if _spotify_state() == "closed":
            speak("Spotify isn't open.")
            return
        run_as('tell application "Spotify" to previous track')
        speak("Previous track.")


def spotify_open_play():
    with _spotify_lock:
        _spotify_ensure_open()
        run_as('tell application "Spotify" to play')
        time.sleep(0.5)
        if _spotify_state() != "playing":
            time.sleep(1.5)
            run_as('tell application "Spotify" to play')


def spotify_search(query: str):
    open_url(f"https://open.spotify.com/search/{urllib.parse.quote(query)}")
    speak(f"Searching Spotify for {query}.")


# ══════════════════════════════════════════════
#  BG HELPER
# ══════════════════════════════════════════════
def _bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# ══════════════════════════════════════════════
#  WEATHER
# ══════════════════════════════════════════════
_wx = {"data": None, "ts": 0}


def get_weather(city: str = None) -> str:
    city = city or CITY
    now = time.time()
    if city == CITY and _wx["data"] and now - _wx["ts"] < 600:
        return _wx["data"]
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={urllib.parse.quote(city)},{COUNTRY_CODE}"
            f"&appid={WEATHER_API_KEY}&units=metric"
        )
        with urllib.request.urlopen(url, timeout=6) as r:
            d = json.loads(r.read())
        temp    = round(d["main"]["temp"])
        feels   = round(d["main"]["feels_like"])
        humidity= d["main"]["humidity"]
        desc    = d["weather"][0]["description"].capitalize()
        result  = f"{desc} in {city}. {temp}°C, feels like {feels}. Humidity {humidity}%."
        if city == CITY:
            _wx.update({"data": result, "ts": now})
        return result
    except Exception as e:
        print(f"Weather error: {e}")
        return "Weather isn't available right now."


# ══════════════════════════════════════════════
#  GREETING
# ══════════════════════════════════════════════
def greet():
    now    = datetime.datetime.now()
    period = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    day    = now.strftime("%A")
    date   = now.strftime("%B %d")
    speak(
        f"Good {period}, {USER_NAME}! Today is {day}, {date}. "
        f"{get_weather()} "
        f"Astra is online. Say Hey Jarvis anytime."
    )


# ══════════════════════════════════════════════
#  WORKSPACE MODES
# ══════════════════════════════════════════════
def mode_video():
    speak("Opening video editing workspace.")
    def _run():
        open_app("DaVinci Resolve"); open_app("Finder"); time.sleep(2)
        spotify_open_play()
        notify("🎬 Video Editing", "DaVinci Resolve + Spotify ready.")
    _bg(_run)


def mode_design():
    speak("Opening design workspace.")
    def _run():
        open_url("https://www.canva.com"); time.sleep(0.5)
        open_app("Adobe Photoshop 2024"); open_app("Adobe Illustrator 2024"); time.sleep(2)
        spotify_open_play()
        notify("🎨 Design Mode", "Canva, Photoshop, Illustrator + Spotify ready.")
    _bg(_run)


def mode_coding():
    speak("Opening coding workspace.")
    def _run():
        open_app("Visual Studio Code"); time.sleep(1)
        open_app("Terminal");           time.sleep(1)
        open_url("https://github.com"); time.sleep(0.3)
        open_url("https://claude.ai"); time.sleep(2)
        spotify_open_play()
        notify("💻 Coding Mode", "VS Code, Terminal, GitHub, Claude + Spotify ready.")
    _bg(_run)


def mode_study():
    speak("Opening study workspace. Say Hey Jarvis start pomodoro when ready.")
    def _run():
        open_app("Notion"); time.sleep(0.5)
        open_url("https://www.youtube.com/results?search_query=lofi+study+music")
        notify("📚 Study Mode", "Notion opened. Pomodoro ready.")
    _bg(_run)


def mode_work():
    speak("Opening work workspace.")
    def _run():
        open_url("https://mail.google.com"); time.sleep(0.3)
        open_url("https://calendar.google.com"); time.sleep(0.5)
        open_app("Slack"); time.sleep(2)
        spotify_open_play()
        notify("💼 Work Mode", "Gmail, Calendar, Slack + Spotify ready.")
    _bg(_run)


def mode_relax():
    speak(f"Time to recharge, {USER_NAME}.")
    def _run():
        open_url("https://www.youtube.com"); time.sleep(1)
        spotify_open_play()
        notify("😌 Relax Mode", "YouTube + Spotify opened.")
    _bg(_run)


# ══════════════════════════════════════════════
#  POMODORO
# ══════════════════════════════════════════════
_pom_running = False


def _pom_loop(work_min, break_min):
    global _pom_running
    cycle = 0
    try:
        while _pom_running:
            cycle += 1
            speak(f"Cycle {cycle}. Focus for {work_min} minutes. Let's go!")
            notify("🍅 Focus!", f"Cycle {cycle} — {work_min} min")
            end = time.time() + work_min * 60
            while time.time() < end and _pom_running:
                time.sleep(3)
            if not _pom_running:
                break
            speak(f"Great work! Take a {break_min} minute break.")
            notify("☕ Break!", f"Cycle {cycle} done. {break_min} min break.")
            end = time.time() + break_min * 60
            while time.time() < end and _pom_running:
                time.sleep(3)
    finally:
        _pom_running = False
        if cycle > 0:
            speak(f"Pomodoro complete. {cycle} cycles done. Well done, {USER_NAME}!")
            notify("✅ Done!", f"{cycle} Pomodoro cycles complete.")


def start_pomodoro(work: int = 25, break_: int = 5):
    global _pom_running
    if _pom_running:
        speak("A session is already running.")
        return
    speak(f"Starting Pomodoro. {work} minutes focus, {break_} minute break.")
    _pom_running = True
    threading.Thread(target=_pom_loop, args=(work, break_), daemon=True).start()


def stop_pomodoro():
    global _pom_running
    _pom_running = False
    speak("Pomodoro stopped.")
    notify("⏹ Stopped", "Pomodoro ended early.")


# ══════════════════════════════════════════════
#  GEMINI AI BRAIN  (FIXED — legacy SDK only)
# ══════════════════════════════════════════════
_gemini_client = None   # google.genai.Client instance
_gemini_ok     = False
_key_index     = 0
GEMINI_MODEL   = "gemini-2.5-flash"


def init_gemini(key_idx: int = 0):
    global _gemini_client, _gemini_ok, _key_index
    if not _GENAI_AVAILABLE:
        print("google-genai not installed. Run: pip3 install google-genai --break-system-packages")
        return
    if not GEMINI_API_KEYS:
        print("No Gemini API keys configured. Gemini disabled.")
        return
    idx = key_idx % len(GEMINI_API_KEYS)
    key = GEMINI_API_KEYS[idx]
    try:
        _gemini_client = _genai_mod.Client(api_key=key)
        _gemini_ok     = True
        _key_index     = idx
        print(f"✅ Gemini AI ready — key #{idx + 1} of {len(GEMINI_API_KEYS)} ({GEMINI_MODEL}).")
    except Exception as e:
        print(f"Gemini init failed on key #{idx + 1}: {e}")
        _gemini_ok = False


def _rotate_key(reason: str = "quota"):
    """Switch to the next API key in the pool silently."""
    global _key_index
    next_idx = (_key_index + 1) % len(GEMINI_API_KEYS)
    if next_idx == _key_index:
        print("⚠️  All Gemini keys exhausted. Add more keys to GEMINI_API_KEYS.")
        return False
    print(f"🔄 Rotating Gemini key ({reason}): #{_key_index + 1} → #{next_idx + 1}")
    init_gemini(next_idx)
    return _gemini_ok


def _gemini_generate(prompt: str, config=None):
    """
    Call Gemini with automatic key rotation on quota errors.
    Returns response object or raises on non-quota errors.
    """
    global _key_index
    attempts = len(GEMINI_API_KEYS)
    for attempt in range(attempts):
        try:
            if config:
                return _gemini_client.models.generate_content(
                    model=GEMINI_MODEL, contents=prompt, config=config
                )
            else:
                return _gemini_client.models.generate_content(
                    model=GEMINI_MODEL, contents=prompt
                )
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                print(f"Quota hit on key #{_key_index + 1}, rotating...")
                if not _rotate_key("quota"):
                    raise
            else:
                raise   # non-quota error, don't rotate
    raise RuntimeError("All Gemini API keys exhausted.")


# ─── System prompt ────────────────────────────────────────────────────────────
_SYSTEM = """You are Astra, a voice assistant for the user on macOS.
Classify his voice command. Return ONLY raw JSON — no markdown, no backticks, nothing else.

Intents:
video_editing, design, coding, study, work, relax,
pomodoro_start, pomodoro_stop,
spotify_play, spotify_pause, spotify_next, spotify_prev, spotify_search,
open_app, close_app, open_url,
volume_up, volume_down, volume_mute, volume_unmute, volume_set,
brightness_up, brightness_down, brightness_set,
battery, system_info,
send_whatsapp, send_imessage,
calendar, reminder,
weather, weather_forecast,
memory_remember, memory_recall, memory_forget,
voice_profile,
web_search,
quit_astra,
time, date, greeting, custom_question, unknown

JSON examples:
{"intent":"pomodoro_start","work_min":25,"break_min":5}
{"intent":"spotify_search","query":"lofi"}
{"intent":"open_app","app_name":"Safari"}
{"intent":"volume_set","level":50}
{"intent":"brightness_set","level":70}
{"intent":"send_whatsapp","contact":"Mom","message":"I'll be late"}
{"intent":"send_imessage","contact":"Rahul","message":"Coming soon"}
{"intent":"voice_profile","profile":"jarvis"}
{"intent":"reminder","message":"call dad","minutes":30}
{"intent":"weather","city":"Mumbai"}
{"intent":"weather_forecast","city":"Mumbai"}
{"intent":"memory_remember","key":"favourite IDE","value":"VS Code","category":"facts"}
{"intent":"memory_recall","query":"favourite IDE"}
{"intent":"memory_forget","key":"favourite IDE"}
{"intent":"custom_question","question":"<full question>"}
{"intent":"web_search","query":"Pushpa 2 review rating"}
{"intent":"quit_astra"}

Rules:
- "quit" / "exit" / "shutdown" / "close astra" / "bye astra" / "goodbye" → quit_astra
- "review", "rating", "rotten tomatoes", "imdb", "box office", "news about", "latest on", "who won", "price of", "score of the match", "what happened" → web_search
- "weather tomorrow / next day" → weather_forecast
- "remember my X is Y" or "my X is Y" → memory_remember
- "what's my X" or "do you know my X" → memory_recall
- "forget my X" → memory_forget
- "send message / WhatsApp to X saying Y" → send_whatsapp
- "iMessage / imessage to X saying Y" → send_imessage
- "switch to X voice / X mode / X profile" or "sound more X" → voice_profile with profile=X (values: professional, friendly, jarvis, minimal)
- "play [X]" → spotify_search
- Any curiosity / motivation / tip / advice → custom_question
- If prior context mentions a city for weather and user says "what about tomorrow" → weather_forecast with that city
"""


def classify(text: str, context: str = "") -> dict:
    if _gemini_ok and _gemini_client:
        try:
            prompt = context + _SYSTEM + f"\n\nCommand: {text}"
            resp = _gemini_generate(prompt)
            raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
            try:
                result = json.loads(raw)
            except Exception:
                m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
                if not m:
                    raise
                result = json.loads(m.group(0))
            print(f"   Gemini → {result}")
            return result
        except Exception as e:
            print(f"   Gemini classify error: {e}")
    result = _fallback(text)
    print(f"   Fallback → {result}")
    return result


# ─── Fallback classifier ──────────────────────────────────────────────────────
def _fallback(t: str) -> dict:
    t = t.lower().strip()

    # Memory
    auto_rem = try_auto_remember(t)
    if auto_rem:
        key, value, cat = auto_rem
        return {"intent": "memory_remember", "key": key, "value": value, "category": cat}
    auto_rec = try_auto_recall(t)
    if auto_rec:
        return {"intent": "memory_recall", "query": auto_rec}
    auto_fgt = try_auto_forget(t)
    if auto_fgt:
        return {"intent": "memory_forget", "key": auto_fgt}

    # Voice profile switch
    profile = vp.try_parse_profile_switch(t)
    if profile:
        return {"intent": "voice_profile", "profile": profile}

    # Weather forecast
    if any(w in t for w in ["tomorrow", "forecast", "next day", "tonight"]):
        city = CITY
        city_m = re.search(r"(?:in|for)\s+(\w+)", t)
        if city_m:
            city = city_m.group(1).capitalize()
        return {"intent": "weather_forecast", "city": city}

    # Video editing
    if any(w in t for w in ["video edit","edit video","editing","davinci","premiere",
                             "final cut","reel","reels","shorts","footage","render","vfx"]):
        return {"intent": "video_editing"}

    # Design
    if any(w in t for w in ["design","canva","photoshop","illustrator","graphic",
                             "poster","logo","thumbnail","figma"]):
        return {"intent": "design"}

    # Coding
    if any(w in t for w in ["cod","program","develop","vs code","github",
                             "terminal","python","javascript","debug"]):
        return {"intent": "coding"}

    # Study
    if any(w in t for w in ["study","homework","learn","revise","notes",
                             "assignment","exam","chapter"]):
        return {"intent": "study"}

    # Work
    if any(w in t for w in ["work","email","meeting","slack","office","client"]):
        return {"intent": "work"}

    # Relax
    if any(w in t for w in ["relax","chill","rest","movie","youtube","netflix","break"]):
        return {"intent": "relax"}

    # Pomodoro
    if any(w in t for w in ["stop pomodoro","stop timer","end timer","cancel timer"]):
        return {"intent": "pomodoro_stop"}
    if any(w in t for w in ["pomodoro","focus timer","start timer","focus for","focus session"]):
        mins = re.search(r"(\d+)\s*min", t)
        return {"intent": "pomodoro_start", "work_min": int(mins.group(1)) if mins else 25, "break_min": 5}

    # Spotify
    if any(w in t for w in ["pause music","pause spotify","stop music","pause"]):
        return {"intent": "spotify_pause"}
    if any(w in t for w in ["next song","next track","skip","next"]):
        return {"intent": "spotify_next"}
    if any(w in t for w in ["previous song","previous track","go back","previous","prev"]):
        return {"intent": "spotify_prev"}
    if any(w in t for w in ["play music","resume music","play spotify","resume"]):
        return {"intent": "spotify_play"}
    if t.startswith("play") or "put on" in t:
        q = re.sub(r"\b(play|put on|some|me|a|the|please)\b","",t).strip()
        return {"intent": "spotify_search", "query": q or "music"}

    # App control
    if any(w in t for w in ["close","quit","exit","kill"]):
        app = re.sub(r"\b(close|quit|exit|kill|shut down|shut)\b","",t).strip()
        return {"intent": "close_app", "app_name": app}
    if any(w in t for w in ["open","launch","start"]):
        app = re.sub(r"\b(open|launch|start)\b","",t).strip()
        return {"intent": "open_app", "app_name": app}

    # Volume
    if "unmute" in t:                                         return {"intent": "volume_unmute"}
    if any(w in t for w in ["mute","silence","quiet"]):       return {"intent": "volume_mute"}
    if "volume up" in t or "turn up" in t or "louder" in t:  return {"intent": "volume_up"}
    if "volume down" in t or "turn down" in t:                return {"intent": "volume_down"}
    if "volume" in t:
        n = re.search(r"(\d+)", t)
        return {"intent": "volume_set", "level": int(n.group(1)) if n else 50}

    # Brightness
    if "brightness up" in t or "brighter" in t:  return {"intent": "brightness_up"}
    if "brightness down" in t or "dim" in t:      return {"intent": "brightness_down"}
    if "brightness" in t:
        n = re.search(r"(\d+)", t)
        return {"intent": "brightness_set", "level": int(n.group(1)) if n else 50}

    # Battery / System
    if any(w in t for w in ["battery","charge","charging"]): return {"intent": "battery"}
    if any(w in t for w in ["system info","cpu","memory","ram"]): return {"intent": "system_info"}

    # Messaging — WhatsApp
    wa_m = re.search(r"(?:send\s+)?(?:message|text|whatsapp)(?:\s+to)?\s+(.+?)\s+(?:saying|that\s+)(.+)$", t)
    if wa_m:
        return {"intent": "send_whatsapp", "contact": wa_m.group(1).strip(), "message": wa_m.group(2).strip()}
    if "whatsapp" in t:
        return {"intent": "send_whatsapp", "contact": "", "message": ""}

    # Messaging — iMessage
    if "imessage" in t:
        im_m = re.search(r"imessage\s+(?:to\s+)?(.+?)\s+(?:saying\s+)?(.+)$", t)
        if im_m:
            return {"intent": "send_imessage", "contact": im_m.group(1).strip(), "message": im_m.group(2).strip()}

    # Calendar
    if any(w in t for w in ["calendar","schedule","events","my day"]):
        return {"intent": "calendar"}

    # Reminders
    if any(w in t for w in ["remind","reminder","don't forget","remember to"]):
        mins = re.search(r"(\d+)\s*min", t)
        msg  = re.sub(r"(remind\s*(me\s*)?(to\s*)?|in\s*\d+\s*min.*)", "", t).strip()
        return {"intent": "reminder", "message": msg, "minutes": int(mins.group(1)) if mins else 0}

    # Custom questions
    if any(w in t for w in ["glow up","fitness tip","motivate","motivation","life advice",
                             "productivity tip","fun fact","did you know","quote","inspire",
                             "health tip","workout","mindset","self improvement"]):
        return {"intent": "custom_question", "question": t}

    # Info
    if "weather" in t:
        city_m = re.search(r"(?:in|for)\s+(\w+)", t)
        city   = city_m.group(1).capitalize() if city_m else CITY
        return {"intent": "weather", "city": city}
    if "time" in t:   return {"intent": "time"}
    if "date" in t or "day" in t or "today" in t: return {"intent": "date"}
    if any(w in t for w in ["quit","exit","shutdown","goodbye","bye astra","close astra"]): return {"intent": "quit_astra"}
    if any(w in t for w in ["hello","hi","hey","what's up","sup","yo"]): return {"intent": "greeting"}
    if any(w in t for w in ["review","rating","imdb","rotten tomatoes","box office","news","latest","who won","price of","score of","what happened"]):
        return {"intent": "web_search", "query": t}

    return {"intent": "unknown"}


# ══════════════════════════════════════════════
#  VOLUME CONTROL
# ══════════════════════════════════════════════
def set_volume(level: int):
    level = max(0, min(100, level))
    run_as(f'set volume output volume {level}')
    speak(f"Volume set to {level}%.")


def volume_up():
    r = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                       capture_output=True, text=True)
    try:
        cur = int(r.stdout.strip())
    except:
        cur = 50
    set_volume(min(100, cur + 10))


def volume_down():
    r = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                       capture_output=True, text=True)
    try:
        cur = int(r.stdout.strip())
    except:
        cur = 50
    set_volume(max(0, cur - 10))


def volume_mute():
    run_as("set volume with output muted")
    speak("Muted.")


def volume_unmute():
    run_as("set volume without output muted")
    speak("Unmuted.")


# ══════════════════════════════════════════════
#  BRIGHTNESS CONTROL
# ══════════════════════════════════════════════
def _brightness_cli(level: float) -> bool:
    try:
        r = subprocess.run(["brightness", str(round(level, 2))], capture_output=True, timeout=5)
        return r.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _brightness_keys(delta: int):
    key   = 144 if delta > 0 else 145
    steps = abs(delta)
    script = "\n".join([f'tell application "System Events" to key code {key}'] * steps)
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def _brightness_cli_step(direction: int) -> bool:
    try:
        r = subprocess.run(["brightness", "-l"], capture_output=True, text=True, timeout=3)
        m = re.search(r"brightness\s+([\d.]+)", r.stdout)
        if not m:
            return False
        cur = float(m.group(1))
        new = max(0.0, min(1.0, cur + direction * 0.15))
        return _brightness_cli(new)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_brightness(level: int):
    level = max(0, min(100, level))
    if _brightness_cli(level / 100.0):
        speak(f"Brightness set to {level}%.")
        return
    _brightness_keys(-16)
    time.sleep(0.1)
    steps = round(level / 6.25)
    if steps > 0:
        _brightness_keys(steps)
    speak(f"Brightness set to around {level}%.")


def brightness_up():
    if _brightness_cli_step(+1):
        speak("Brighter.")
        return
    _brightness_keys(3)
    speak("Brighter. If it didn't change, run: brew install brightness")


def brightness_down():
    if _brightness_cli_step(-1):
        speak("Dimmer.")
        return
    _brightness_keys(-3)
    speak("Dimmer. If it didn't change, run: brew install brightness")


# ══════════════════════════════════════════════
#  BATTERY & SYSTEM INFO
# ══════════════════════════════════════════════
def get_battery() -> str:
    try:
        r = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
        for line in r.stdout.strip().split("\n"):
            if "%" in line:
                pct      = re.search(r"(\d+)%", line)
                charging = "charging" in line.lower() or "ac power" in r.stdout.lower()
                if pct:
                    status = "charging" if charging else "on battery"
                    return f"Battery is at {pct.group(1)}%, {status}."
        return "Couldn't read battery info."
    except Exception as e:
        return f"Battery check failed: {e}"


def get_system_info() -> str:
    try:
        cpu = subprocess.run(
            ["bash", "-c", "top -l 1 | grep 'CPU usage' | awk '{print $3}'"],
            capture_output=True, text=True
        ).stdout.strip()
        battery = get_battery()
        return f"{battery} CPU usage is around {cpu}."
    except:
        return get_battery()


# ══════════════════════════════════════════════
#  REMINDERS
# ══════════════════════════════════════════════
def set_reminder(message: str, minutes: int = 0, time_str: str = ""):
    try:
        if minutes > 0:
            remind_at = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
            time_fmt  = remind_at.strftime("%B %d, %Y at %I:%M %p")
        elif time_str:
            time_fmt = time_str
        else:
            speak("When should I remind you?")
            return
        script = f'''
tell application "Reminders"
    set newReminder to make new reminder
    set name of newReminder to "{message}"
    set due date of newReminder to date "{time_fmt}"
    activate
end tell
'''
        run_as(script)
        speak(f"Reminder set: {message}" + (f" in {minutes} minutes." if minutes > 0 else f" at {time_str}."))
    except Exception as e:
        print(f"Reminder error: {e}")
        speak("Couldn't set the reminder.")


# ══════════════════════════════════════════════
#  CALENDAR
# ══════════════════════════════════════════════
def get_todays_events() -> str:
    try:
        script = '''
tell application "Calendar"
    set todayEvents to {}
    set startOfDay to current date
    set hours of startOfDay to 0
    set minutes of startOfDay to 0
    set seconds of startOfDay to 0
    set endOfDay to startOfDay + (24 * 60 * 60)
    repeat with cal in calendars
        set evts to (every event of cal whose start date >= startOfDay and start date < endOfDay)
        repeat with e in evts
            set end of todayEvents to (summary of e & " at " & ((start date of e) as string))
        end repeat
    end repeat
    return todayEvents
end tell
'''
        r   = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        raw = r.stdout.strip()
        if not raw or raw == "{}":
            return "You have no events scheduled today."
        events = [e.strip() for e in raw.split(",") if e.strip()]
        if not events:
            return "No events found for today."
        result = f"You have {len(events)} event{'s' if len(events)>1 else ''} today. "
        result += ". ".join(events[:5])
        return result
    except Exception as e:
        print(f"Calendar error: {e}")
        return "Couldn't read your calendar."


# ══════════════════════════════════════════════
#  CUSTOM QUESTIONS (Gemini)
# ══════════════════════════════════════════════
def answer_custom_question(question: str):
    try:
        ctx = build_context_block()
        prompt = f"""{ctx}You are Astra, a friendly personal assistant for {USER_NAME} on macOS.

Rules:
- Reply with EXACTLY 2-3 short sentences.
- No bullet points, no markdown.
- Conversational + warm Indian English style.
- Start first sentence with: "Sure!", "Here's one!", "Got it!", or "Alright!".
- Practical and safe for fitness/health tips.

Question: {question}
"""
        if _gemini_ok and _gemini_client:
            resp   = _gemini_generate(prompt)
            answer = resp.text.strip()
            speak(answer)
            return answer
        else:
            speak("My AI brain isn't connected. Check your Gemini API key.")
            return ""
    except Exception as e:
        err = str(e)
        print(f"Custom Q error: {e}")
        if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err or "All Gemini" in err:
            speak("My API quota is exhausted for now. Try again later or add a new key.")
        else:
            speak("Something went wrong. Please try again.")
        return ""


# ══════════════════════════════════════════════
#  WEB SEARCH (Gemini grounding — live results)
# ══════════════════════════════════════════════
def answer_web_search(query: str):
    """Answer using Gemini with Google Search grounding."""
    try:
        if not (_gemini_ok and _gemini_client):
            speak("My AI brain isn't connected. Check your Gemini API key.")
            return ""

        speak("Searching.")

        from google.genai import types as _genai_types

        prompt = f"""You are Astra, a voice assistant for {USER_NAME} in {CITY}.
Search the web and answer in spoken format — no markdown, no bullet points, no asterisks.
- Movies/shows: give IMDb rating, Rotten Tomatoes score, and a 2-3 sentence review summary.
- News/sports: key facts in 2-3 sentences.
- Prices/products: current price and a brief note.
- End with one short recommendation sentence.
- Total response: under 5 sentences. Conversational Indian English.

Query: {query}"""

        cfg = _genai_types.GenerateContentConfig(
            tools=[_genai_types.Tool(google_search=_genai_types.GoogleSearch())],
            temperature=0.2,
        )
        resp = _gemini_generate(prompt, config=cfg)
        answer = resp.text.strip()
        speak(answer)
        return answer
    except Exception as e:
        err = str(e)
        print(f"Web search error: {e}")
        if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err or "All Gemini" in err:
            speak("My API quota is exhausted for now. Try again later or add a new key.")
        else:
            speak("Something went wrong with the search. Please try again.")
        return ""


# ══════════════════════════════════════════════
#  TYPED INPUT  (Cmd+Shift+A global hotkey)
# ══════════════════════════════════════════════
def _show_type_dialog():
    """Show a native macOS input dialog, process typed command via Astra."""
    script = r"""
set userInput to text returned of (display dialog "Type your command for Astra:" default answer "" with title "Astra" buttons {"Cancel", "Send"} default button "Send" giving up after 60)
return userInput
"""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=70
        )
        text = r.stdout.strip()
        if text and r.returncode == 0:
            print(f"⌨️  Typed: {text}")
            ctx_block = build_context_block()
            handle(classify(text, ctx_block), text)
    except Exception as e:
        print(f"Type dialog error: {e}")


def _hotkey_listener():
    """Listen for Cmd+Shift+A globally using pynput."""
    try:
        from pynput import keyboard as _kb

        _pressed = set()

        def on_press(key):
            try:
                if key in (_kb.Key.cmd, _kb.Key.cmd_l, _kb.Key.cmd_r):
                    _pressed.add("cmd")
                elif key in (_kb.Key.shift, _kb.Key.shift_l, _kb.Key.shift_r):
                    _pressed.add("shift")
                elif hasattr(key, "char") and key.char and key.char.lower() == "a":
                    if "cmd" in _pressed and "shift" in _pressed:
                        threading.Thread(target=_show_type_dialog, daemon=True).start()
            except Exception:
                pass

        def on_release(key):
            try:
                if key in (_kb.Key.cmd, _kb.Key.cmd_l, _kb.Key.cmd_r):
                    _pressed.discard("cmd")
                elif key in (_kb.Key.shift, _kb.Key.shift_l, _kb.Key.shift_r):
                    _pressed.discard("shift")
            except Exception:
                pass

        with _kb.Listener(on_press=on_press, on_release=on_release) as listener:
            print("⌨️  Hotkey active: Cmd+Shift+A → type a command")
            listener.join()

    except ImportError:
        print("⚠️  pynput not installed. Run: pip3 install pynput --break-system-packages")


# ══════════════════════════════════════════════
#  INTENT HANDLER — central dispatch
# ══════════════════════════════════════════════
def handle(result: dict, original_text: str = ""):
    """Route classified intent to the right handler."""
    try:
        i = result.get("intent", "unknown")

        # ── Try plugin dispatch first ─────────────────────────────────────────
        if plugin_dispatch(result, speak, notify_fn=notify,
                           open_app_fn=open_app, run_as_fn=run_as,
                           open_url_fn=open_url):
            vp.auto_select(i)
            ctx_push(original_text, result, "")
            return

        # ── Memory intents ────────────────────────────────────────────────────
        if i == "memory_remember":
            key   = result.get("key", "")
            value = result.get("value", "")
            cat   = result.get("category", "facts")
            if key and value:
                msg = remember(key, value, cat)
                speak(msg)
            else:
                speak("What should I remember?")
            ctx_push(original_text, result, "")
            return

        if i == "memory_recall":
            query = result.get("query", "")
            if query:
                ans = recall(query)
                if ans:
                    speak(ans)
                else:
                    # Fall through to Gemini for a natural response
                    speak(f"I don't have anything stored about {query}.")
            else:
                speak("What would you like me to recall?")
            ctx_push(original_text, result, "")
            return

        if i == "memory_forget":
            key = result.get("key", "")
            if key:
                speak(forget(key))
            else:
                speak("What should I forget?")
            ctx_push(original_text, result, "")
            return

        # ── Voice profile switch (must come before auto_select) ───────────────
        if i == "voice_profile":
            profile = result.get("profile", "")
            if vp.set_profile(profile):
                speak(f"Switched to {profile} mode.")
            else:
                speak(f"I don't have a {profile} profile. Try: professional, friendly, JARVIS, or minimal.")
            return

        # ── Auto voice profile selection (skipped for explicit profile switch) ─
        vp.auto_select(i)
        astra_response = ""
        if   i == "video_editing": mode_video()
        elif i == "design":        mode_design()
        elif i == "coding":        mode_coding()
        elif i == "study":         mode_study()
        elif i == "work":          mode_work()
        elif i == "relax":         mode_relax()

        elif i == "pomodoro_start":
            start_pomodoro(result.get("work_min", 25), result.get("break_min", 5))
        elif i == "pomodoro_stop":
            stop_pomodoro()

        elif i == "spotify_play":   _bg(spotify_play)
        elif i == "spotify_pause":  _bg(spotify_pause)
        elif i == "spotify_next":   _bg(spotify_next)
        elif i == "spotify_prev":   _bg(spotify_prev)
        elif i == "spotify_search": _bg(spotify_search, result.get("query","music"))

        elif i == "open_app":
            name = result.get("app_name","").strip()
            if name:
                speak(f"Opening {name}."); _bg(open_app, name)
            else:
                speak("Which app should I open?")
        elif i == "close_app":
            name = result.get("app_name","").strip()
            if name:
                speak(f"Closing {name}."); _bg(close_app, name)
            else:
                speak("Which app?")
        elif i == "open_url":
            url = result.get("url","").strip()
            if url:
                if not url.startswith("http"): url = "https://" + url
                open_url(url); speak("Opening it.")
            else:
                speak("Which website?")

        elif i == "weather":
            city = result.get("city", CITY) or CITY
            astra_response = get_weather(city)
            speak(astra_response)

        elif i == "weather_forecast":
            # Use city from intent, or fall back to last mentioned city in context
            city = result.get("city") or last_city() or CITY
            from plugins.weather import _fetch_forecast
            astra_response = _fetch_forecast(city)
            speak(astra_response)

        elif i == "time":
            astra_response = f"It's {datetime.datetime.now().strftime('%I:%M %p')}, {USER_NAME}."
            speak(astra_response)
        elif i == "date":
            astra_response = f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."
            speak(astra_response)
        elif i == "greeting":
            astra_response = vp.greeting()
            speak(astra_response)

        elif i == "volume_up":    volume_up()
        elif i == "volume_down":  volume_down()
        elif i == "volume_mute":  volume_mute()
        elif i == "volume_unmute":volume_unmute()
        elif i == "volume_set":   set_volume(result.get("level", 50))

        elif i == "brightness_up":   brightness_up()
        elif i == "brightness_down": brightness_down()
        elif i == "brightness_set":  set_brightness(result.get("level", 50))

        elif i == "battery":     speak(get_battery())
        elif i == "system_info": speak(get_system_info())
        elif i == "calendar":    _bg(lambda: speak(get_todays_events()))

        elif i == "reminder":
            msg  = result.get("message","").strip()
            mins = result.get("minutes", 0)
            if msg:
                set_reminder(msg, minutes=mins)
            else:
                speak("What should I remind you about?")

        elif i == "custom_question":
            q = result.get("question","give me a tip")
            _bg(lambda q=q: answer_custom_question(q))

        elif i == "web_search":
            q = result.get("query", original_text)
            _bg(lambda q=q: answer_web_search(q))

        elif i == "quit_astra":
            speak(f"Goodbye {USER_NAME}. Have a great day!", blocking=True)
            rumps.quit_application()

        else:
            speak(er.graceful_fallback())

        # Push to context for follow-up tracking
        ctx_push(original_text, result, astra_response)

    except Exception as e:
        print(f"handle error: {e}")
        traceback.print_exc()
        speak(er.graceful_fallback())


# ══════════════════════════════════════════════
#  SPEECH RECOGNITION
# ══════════════════════════════════════════════
_rec = sr.Recognizer()
_rec.energy_threshold     = 250
_rec.dynamic_energy_threshold = True
_rec.pause_threshold      = 0.7


def listen_command() -> str | None:
    mic_attempts = 0
    while mic_attempts < 2:
        try:
            with sr.Microphone() as src:
                _rec.adjust_for_ambient_noise(src, duration=0.3)
                audio = _rec.listen(src, timeout=6, phrase_time_limit=12)
            text = _rec.recognize_google(audio, language="en-IN")
            print(f"🎤 Heard: {text}")
            er.mic_ok()
            return text
        except sr.WaitTimeoutError:
            speak("Didn't catch that. Say Hey Jarvis to try again.")
            return None
        except sr.UnknownValueError:
            speak("Couldn't understand. Please try again.")
            return None
        except sr.RequestError:
            speak("Speech service unavailable. Check internet.")
            return None
        except Exception as e:
            print(f"Listen error: {e}")
            need_reinit = er.mic_failure(speak)
            if need_reinit:
                mic_attempts += 1
                time.sleep(1)
            else:
                return None
    return None


# ══════════════════════════════════════════════
#  WAKE WORD ENGINE
# ══════════════════════════════════════════════
_astra_active = True
_wake_model   = None
_processing   = False
_proc_lock    = threading.Lock()


def init_wake_model() -> bool:
    global _wake_model, WAKE_THRESHOLD
    try:
        paths       = openwakeword.get_pretrained_model_paths()
        jarvis_path = next((p for p in paths if "jarvis" in p), None)
        if not jarvis_path:
            print("Jarvis model not found")
            return False
        if os.path.exists(VERIFIER_PATH):
            print("✅ Custom 'Hey Astra' verifier found!")
            WAKE_THRESHOLD = 0.5
            _wake_model = WakeModel(
                wakeword_model_paths=[jarvis_path],
                custom_verifier_models={"hey_jarvis_v0.1": VERIFIER_PATH},
                custom_verifier_threshold=WAKE_THRESHOLD,
                vad_threshold=0.2,
            )
        else:
            _wake_model = WakeModel(wakeword_model_paths=[jarvis_path], vad_threshold=0.2)
            print("✅ OpenWakeWord loaded — say 'Hey Jarvis'")
        return True
    except Exception as e:
        print(f"Wake model error: {e}")
        return False


def _trigger_astra(extra: str = ""):
    global _processing
    with _proc_lock:
        if _processing:
            return
        _processing = True
    try:
        if extra and len(extra.strip()) > 2:
            speak(vp.filler(), blocking=False)
            _bg(lambda c=extra: handle(classify(c, build_context_block()), c))
        else:
            speak(f"Yes {USER_NAME}?", blocking=False)
            time.sleep(0.8)
            cmd = listen_command()
            if cmd:
                ctx_block = build_context_block()
                _bg(lambda c=cmd, cx=ctx_block: handle(classify(c, cx), c))
    except Exception as e:
        print(f"Trigger error: {e}")
    finally:
        time.sleep(1.5)
        _processing = False


def _wake_loop_oww():
    import pyaudio
    CHUNK       = 1280
    SAMPLE_RATE = 16000
    COOLDOWN    = 2.5
    last_trig   = 0
    pa     = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                     input=True, frames_per_buffer=CHUNK)
    print("👂 Listening for 'Hey Jarvis'…")
    try:
        while True:
            if not _astra_active:
                time.sleep(0.5)
                continue
            raw   = stream.read(CHUNK, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            preds = _wake_model.predict(audio)
            score = max(preds.values()) if preds else 0
            now   = time.time()
            if score > WAKE_THRESHOLD and (now - last_trig) > COOLDOWN:
                last_trig = now
                print(f"🎙️ Wake! score={score:.3f}")
                threading.Thread(target=_trigger_astra, daemon=True).start()
    finally:
        try:
            stream.stop_stream(); stream.close()
        except: pass
        try:
            pa.terminate()
        except: pass


def _wake_loop_fallback():
    VARIANTS = ["hey jarvis","jarvis","hey astro","hey astra","hey travis",
                "hey garcia","hi jarvis","ok jarvis","hairstyle"]
    recognizer = sr.Recognizer()
    recognizer.energy_threshold        = 200
    recognizer.dynamic_energy_threshold = True
    print("👂 Fallback wake word active…")
    while True:
        if not _astra_active:
            time.sleep(1); continue
        try:
            with sr.Microphone() as src:
                recognizer.adjust_for_ambient_noise(src, duration=0.2)
                audio = recognizer.listen(src, timeout=2, phrase_time_limit=5)
            text = recognizer.recognize_google(audio, language="en-IN").lower()
            print(f"   heard: {text}")
            if any(v in text for v in VARIANTS):
                rest = text
                for v in VARIANTS:
                    rest = rest.replace(v,"").strip()
                threading.Thread(target=_trigger_astra, args=(rest,), daemon=True).start()
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            pass
        except sr.RequestError:
            time.sleep(5)


def start_listener():
    use_oww = init_wake_model()
    if use_oww:
        try:
            import pyaudio
            _safe_thread("oww_wake", _wake_loop_oww, restart=True, delay=3.0)
            print("✅ Using OpenWakeWord (auto-restart enabled)")
            return
        except ImportError:
            print("pyaudio missing, using fallback")
    _safe_thread("fallback_wake", _wake_loop_fallback, restart=True, delay=2.0)
    print("⚠️  Using speech fallback (auto-restart enabled)")


# ══════════════════════════════════════════════
#  MENU BAR
# ══════════════════════════════════════════════
class AstraApp(rumps.App):
    def __init__(self):
        super().__init__("◉", quit_button=None)
        self.menu = [
            rumps.MenuItem("● Astra is listening", callback=None),
            None,
            rumps.MenuItem("Pause / Resume",         callback=self.toggle),
            rumps.MenuItem("Morning Briefing",        callback=lambda _: _bg(greet)),
            rumps.MenuItem("Weather",                 callback=lambda _: _bg(lambda: speak(get_weather()))),
            rumps.MenuItem("Time",                    callback=lambda _: speak(
                f"It's {datetime.datetime.now().strftime('%I:%M %p')}.")),
            None,
            rumps.MenuItem("🎬  Video Editing",       callback=lambda _: mode_video()),
            rumps.MenuItem("🎨  Design",              callback=lambda _: mode_design()),
            rumps.MenuItem("💻  Coding",              callback=lambda _: mode_coding()),
            rumps.MenuItem("📚  Study",               callback=lambda _: mode_study()),
            rumps.MenuItem("💼  Work",                callback=lambda _: mode_work()),
            rumps.MenuItem("😌  Relax",               callback=lambda _: mode_relax()),
            None,
            rumps.MenuItem("⏱  Pomodoro 25 min",      callback=lambda _: start_pomodoro(25, 5)),
            rumps.MenuItem("⏱  Pomodoro 50 min",      callback=lambda _: start_pomodoro(50, 10)),
            rumps.MenuItem("⏹  Stop Pomodoro",        callback=lambda _: stop_pomodoro()),
            None,
            rumps.MenuItem("🗂  Memory — What I know", callback=lambda _: _bg(self._show_memory)),
            rumps.MenuItem("⌨️  Type a Command",       callback=lambda _: _bg(_show_type_dialog)),
            None,
            rumps.MenuItem("Quit Astra",              callback=self.quit_app),
        ]
        _bg(init_gemini)
        _bg(start_listener)
        _safe_thread("hotkey_listener", _hotkey_listener, restart=True, delay=5.0)
        # Start internet monitor
        _safe_thread("internet_monitor", er.internet_monitor_loop, speak, restart=True, delay=15.0)
        threading.Thread(target=lambda: (time.sleep(2), greet()), daemon=True).start()

    def _show_memory(self):
        from memory.memory_manager import recall_all
        data = recall_all()
        parts = []
        for cat in ("facts", "preferences", "dates"):
            store = data.get(cat, {})
            if store:
                parts.append(f"{cat.capitalize()}: " + ", ".join(f"{k}={v}" for k, v in store.items()))
        notes = data.get("notes", [])
        if notes:
            parts.append(f"Notes: {len(notes)} item(s).")
        if parts:
            speak("Here's what I remember: " + ". ".join(parts))
        else:
            speak("I don't have any memories stored yet. Tell me things like 'my favourite IDE is VS Code'.")

    def toggle(self, _):
        global _astra_active
        _astra_active = not _astra_active
        if _astra_active:
            self.title = "◉"
            self.menu["● Astra is listening"].title = "● Astra is listening"
            speak("I'm back online.")
        else:
            self.title = "○"
            self.menu["● Astra is listening"].title = "○ Astra is paused"
            speak("Paused. Click the menu to resume.")

    def quit_app(self, _):
        speak(f"Goodbye {USER_NAME}. Have a great day!", blocking=True)
        rumps.quit_application()


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
def main():
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  🎙️  Astra v4.0 — Starting…")
    print("  Wake word  : 'Hey Jarvis'")
    print("  Menu bar   : look for ◉ top right")
    print("  New in v4.0: Memory · Context · Plugins · Profiles · Better errors")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    AstraApp().run()


if __name__ == "__main__":
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            print("\nAstra stopped.")
            break
        except Exception as e:
            print(f"💥 Main crash: {e}")
            traceback.print_exc()
            print("   Restarting in 3s…")
            time.sleep(3)
