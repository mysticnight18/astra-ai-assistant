"""
Messaging plugin — WhatsApp and iMessage.
WhatsApp: uses URL scheme (whatsapp://send?phone=...&text=...) which is
the only reliable method on Electron-based WhatsApp Desktop.
iMessage: uses AppleScript via Messages.app.
"""
import subprocess
import time
import urllib.parse

from .base import AstraPlugin


# ─── Phone book ───────────────────────────────────────────────────────────────
# Add contacts here: "name as Astra hears it" -> "91XXXXXXXXXX"
# Always use full number with country code, no + or spaces.

PHONE_BOOK = {
    "mummy":  "91XXXXXXXXXX",   # ← replace with real number
    "papa":   "91XXXXXXXXXX",   # ← replace with real number
    # add more contacts below:
    # "rahul": "91XXXXXXXXXX",
}


def _lookup_phone(contact: str) -> str | None:
    """Return phone number for contact name, or None if not found."""
    return PHONE_BOOK.get(contact.lower().strip())


# ─── WhatsApp ─────────────────────────────────────────────────────────────────

def _wa_send(phone: str, message: str) -> bool:
    """
    Send WhatsApp message via URL scheme + Enter keystroke.
    URL scheme opens the chat with message pre-filled.
    System Events just presses Enter to send.
    """
    encoded_msg = urllib.parse.quote(message)
    url = f"whatsapp://send?phone={phone}&text={encoded_msg}"

    # Step 1: open the URL (pre-fills chat + message)
    result = subprocess.run(
        ["open", url],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        print(f"[Messaging] Failed to open WhatsApp URL: {result.stderr.strip()}")
        return False

    # Step 2: wait for WhatsApp to load the chat
    time.sleep(4.0)

    # Step 3: press Enter to send
    script = '''
tell application "WhatsApp" to activate
delay 0.5
tell application "System Events"
    tell process "WhatsApp"
        set frontmost to true
        delay 0.5
        key code 36
        delay 0.5
    end tell
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        print(f"[Messaging] WhatsApp Enter keystroke error: {result.stderr.strip()}")
    return result.returncode == 0


def send_whatsapp(contact: str, message: str, speak_fn, notify_fn=None):
    speak_fn(f"Messaging {contact} on WhatsApp.")
    try:
        phone = _lookup_phone(contact)
        if not phone:
            speak_fn(
                f"I don't have {contact}'s number saved. "
                f"Add it to the PHONE_BOOK in messaging.py."
            )
            return

        if phone == "91XXXXXXXXXX":
            speak_fn(
                f"Please replace the placeholder number for {contact} "
                f"in messaging.py with the real number."
            )
            return

        ok = _wa_send(phone, message)
        if ok:
            if notify_fn:
                notify_fn("WhatsApp", f"Sent to {contact}: {message[:40]}")
            speak_fn(f"Done! Message sent to {contact} on WhatsApp.")
        else:
            speak_fn(f"Something went wrong. WhatsApp is open — please send manually.")

    except Exception as e:
        print(f"[Messaging] WhatsApp exception: {e}")
        subprocess.run(["open", "-a", "WhatsApp"], capture_output=True, timeout=5)
        speak_fn("Something went wrong. WhatsApp is open for you.")


# ─── iMessage ─────────────────────────────────────────────────────────────────

def send_imessage(contact: str, message: str, speak_fn, notify_fn=None):
    speak_fn(f"Sending iMessage to {contact}.")
    safe_msg     = message.replace('"', '\\"')
    safe_contact = contact.replace('"', '\\"')

    script = f'''
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to missing value

    try
        set targetBuddy to participant "{safe_contact}" of targetService
    on error
    end try

    if targetBuddy is missing value then
        repeat with b in (participants of targetService)
            if (name of b) contains "{safe_contact}" then
                set targetBuddy to b
                exit repeat
            end if
        end repeat
    end if

    if targetBuddy is missing value then error "Participant not found"
    send "{safe_msg}" to targetBuddy
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=20
    )
    if result.returncode == 0:
        if notify_fn:
            notify_fn("iMessage", f"Sent to {contact}: {message[:40]}")
        speak_fn(f"iMessage sent to {contact}.")
    else:
        print(f"[Messaging] iMessage error: {result.stderr.strip()}")
        subprocess.run(["open", "-a", "Messages"], capture_output=True, timeout=5)
        speak_fn(f"Couldn't auto-send. Messages is open — please message {contact} manually.")


# ─── Plugin class ──────────────────────────────────────────────────────────────

class MessagingPlugin(AstraPlugin):
    name    = "messaging"
    intents = ["send_whatsapp", "send_message", "send_imessage"]

    def handle(self, intent: dict, speak_fn, **kwargs):
        i         = intent.get("intent", "")
        contact   = intent.get("contact", "").strip()
        message   = intent.get("message", "").strip()
        platform  = intent.get("platform", "whatsapp").lower()
        notify_fn = kwargs.get("notify_fn")

        if i not in self.intents:
            return False

        if not contact or not message:
            speak_fn("Who should I message and what should I say?")
            return True

        if i == "send_imessage" or "imessage" in platform:
            send_imessage(contact, message, speak_fn, notify_fn)
        else:
            send_whatsapp(contact, message, speak_fn, notify_fn)
        return True
