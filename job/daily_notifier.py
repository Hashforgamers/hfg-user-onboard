import os
import time
import requests
import logging
import random
from datetime import datetime, timedelta

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None

# ----------------------------
# Logging Configuration
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ----------------------------
# Environment Variables
# ----------------------------
API_BASE = os.getenv("API_BASE", "https://hfg-user-onboard.onrender.com/api")
API_KEY = os.getenv("API_KEY", "")
NOTIFY_INTERVAL = int(os.getenv("NOTIFY_INTERVAL", "14400"))  # seconds

# ----------------------------
# Gemini Setup
# ----------------------------
_GENAI_CLIENT = None
if API_KEY and genai is not None:
    try:
        _GENAI_CLIENT = genai.Client(api_key=API_KEY)
    except Exception:
        _GENAI_CLIENT = None
HASH_AGENT_PROMPT = """
You are HASH for Gamers, India's first gaming café booking platform.

Task:
- Generate a short push notification for gamers about booking slots at nearby gaming cafés.

Guidelines:
- Title: max 7 words, exciting, gaming-themed.
- Message: 1 sentence, casual and fun, encourage immediate booking.
- Do not return JSON, only plain text.
- Format strictly as:
Title: <your title>
Message: <your message>
"""

# ----------------------------
# Hardcoded Fallback Messages
# ----------------------------
FALLBACK_MESSAGES = [
    {"title": "Game Night Awaits!", "message": "Book your café slot before it’s gone!"},
    {"title": "Ready to Play?", "message": "Reserve your spot at your local café now!"},
    {"title": "Squad Up!", "message": "Grab your friends and lock your slots today."},
    {"title": "Level Up IRL", "message": "Play like a pro at your nearby gaming café."},
    {"title": "Book & Play", "message": "Slots filling fast — secure yours today!"},
    {"title": "Don’t Miss Out!", "message": "Your café seat is waiting for you."},
    {"title": "Weekend Grind?", "message": "Reserve your slot before it’s fully booked."},
    {"title": "Game Café Vibes", "message": "Feel the thrill of gaming with friends nearby."},
    {"title": "XP Boost IRL", "message": "Book your café slot and game non-stop!"},
    {"title": "Boss Fight IRL", "message": "Gather your squad and claim your café slot."},
    {"title": "Casual or Ranked?", "message": "Whatever your style, book your café now."},
    {"title": "Play Local, Play Big", "message": "Your gaming café is waiting."},
    {"title": "Slots Running Low!", "message": "Hurry, book your café before it’s full."},
    {"title": "Squad Assemble!", "message": "Lock your café slot today."},
    {"title": "LAN Party Energy", "message": "Nothing beats café gaming with friends."},
    {"title": "Game Café Buzz", "message": "Book a slot and join the fun!"},
    {"title": "Gear Up!", "message": "Your café slot is just a tap away."},
    {"title": "Gamers Unite!", "message": "Slots are filling — don’t wait too long."},
    {"title": "Real Life Lobby", "message": "Your café spot is waiting to be claimed."},
    {"title": "Grind Mode On", "message": "Book your café slot and keep the streak alive."},
    {"title": "Café Gaming FTW", "message": "Secure your slot and game like never before."},
    {"title": "Game Plan Ready?", "message": "Café slots are open now!"},    
    {"title": "Weekend Warriors", "message": "Lock your gaming café slot today."},
    {"title": "Book It, Play It", "message": "Your slot is one click away."},
    {"title": "XP Party!", "message": "Book your café seat and level up IRL."},
    {"title": "Café Mode: ON", "message": "Get your slot before it’s gone!"},
    {"title": "Time to Respawn!", "message": "Your café is waiting, book now."},
    {"title": "Casual Fun, Ranked Thrill", "message": "Reserve your slot today."},
    {"title": "Multiplayer IRL", "message": "Book your café slot with friends."},
    {"title": "Slot Rush!", "message": "Act fast — limited café slots available."},
    {"title": "Next Match IRL", "message": "Book your café spot and join the fun."},
    {"title": "Gaming Reloaded", "message": "Lock your café slot today!"},
    {"title": "Book, Play, Repeat", "message": "Your café experience awaits."},
    {"title": "Squad Goals IRL", "message": "Café slots open now — grab yours."},
    {"title": "Weekend Café Buzz", "message": "Book a slot and feel the vibe."},
    {"title": "Game IRL", "message": "Reserve your café slot now."},
    {"title": "Let’s Play Together", "message": "Book your café seat today."},
    {"title": "Slots Almost Full!", "message": "Don’t wait — secure your café spot."},
    {"title": "Boss Raid IRL", "message": "Book a café slot for the full experience."},
    {"title": "Gaming Café Magic", "message": "Lock your seat today."},
    {"title": "Slot Confirmed!", "message": "Reserve and start your café journey."},
    {"title": "Café Ready", "message": "Your gaming café slot is waiting."},
    {"title": "Playtime IRL", "message": "Book your café slot before it’s late."},
    {"title": "Level Up Fun", "message": "Reserve your café seat now."},
    {"title": "XP Grind", "message": "Café slots are live — book now."},
    {"title": "Time for GG", "message": "Secure your café spot today."},
    {"title": "Play Hard, Chill Harder", "message": "Café slots open now."},
    {"title": "Café Nights", "message": "Reserve your gaming slot tonight."},
    {"title": "Let’s LAN!", "message": "Book your café slot and play together."}
]

# ----------------------------
# Gemini Agent Helper
# ----------------------------
def gemini_agent():
    return _GENAI_CLIENT

def generate_notification():
    logger = logging.getLogger(__name__)
    client = gemini_agent()

    logger.info("Generating notification with HASH agent...")

    try:
        if client is None:
            raise ValueError("Gemini client is not configured")

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=HASH_AGENT_PROMPT,
        )
        raw_text = str(getattr(response, "text", "") or "").strip()
        logger.info(f"Gemini raw response:\n{raw_text}")

        # Parse manually
        title, message = None, None
        for line in raw_text.splitlines():
            if line.lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
            elif line.lower().startswith("message:"):
                message = line.split(":", 1)[1].strip()

        if not title or not message:
            raise ValueError("Missing title or message")

        return {"title": title, "message": message}

    except Exception as e:
        logger.error(f"Gemini error: {e}")
        notif = random.choice(FALLBACK_MESSAGES)
        logger.info(f"Using fallback notification: {notif}")
        return notif

def is_within_time_window():
    """Check if current time is between 6:00 AM and 10:00 PM IST"""
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # Convert to IST
    ist_hour = ist_now.hour
    return 6 <= ist_hour < 22  # 6AM to 10PM


def run_notification_cycle(force=False):
    if not force and not is_within_time_window():
        current_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        logger.info(
            "Skipping notifications (outside window 6AM-10PM IST, current IST time: %s)",
            current_ist.strftime("%H:%M"),
        )
        return {"success": True, "skipped": True, "reason": "outside_notification_window"}

    logger.info("Fetching FCM tokens...")
    resp = requests.get(f"{API_BASE}/getAllFCMToken")
    if resp.status_code != 200:
        logger.error("Error fetching tokens: %s", resp.text)
        return {"success": False, "error": resp.text, "status_code": resp.status_code}

    data = resp.json().get("data", [])
    if not data:
        return {"success": True, "skipped": False, "tokens_found": 0, "sent": 0, "failed": 0}

    logger.info("Found %s tokens to notify.", len(data))
    notif = generate_notification()
    sent = 0
    failed = 0

    for entry in data:
        token = entry.get("token")
        if not token:
            failed += 1
            continue
        payload = {"token": token, "title": notif["title"], "message": notif["message"]}
        r = requests.post(f"{API_BASE}/notify-user", json=payload)
        if 200 <= r.status_code < 300:
            sent += 1
        else:
            failed += 1
        logger.info("Sent to %s... Status %s", token[:10], r.status_code)

    return {
        "success": True,
        "skipped": False,
        "tokens_found": len(data),
        "sent": sent,
        "failed": failed,
        "notification": notif,
    }

def main():
    logger.info("Starting daily notification job...")

    while True:
        run_notification_cycle(force=False)
        logger.info(f"Sleeping {NOTIFY_INTERVAL} seconds...")
        time.sleep(NOTIFY_INTERVAL)

if __name__ == "__main__":
    main()
