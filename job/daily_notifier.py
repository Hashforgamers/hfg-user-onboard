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
- Style: modern app notification tone (like top food-delivery apps), punchy and high-conversion.
- Audience: Gen-Z/young gamers.
- Language: English, but in around 40% outputs include natural Hinglish words (e.g., "jaldi", "scene", "aaj", "bro", "squad").
- Title: max 6 words, catchy.
- Message: 1 short sentence, max 14 words, clear CTA to book now.
- Keep it safe and friendly (no abuse, no misleading offers).
- Do not return JSON, only plain text.
- Format strictly as:
Title: <your title>
Message: <your message>
"""

# ----------------------------
# Hardcoded Fallback Messages
# ----------------------------
FALLBACK_MESSAGES = [
    {"title": "Bro, Slot Book Kiya?", "message": "Aaj ka gaming scene set karo, jaldi book now."},
    {"title": "Squad Online, Seats Offline", "message": "Cafe slots fast fill ho rahe, lock yours now."},
    {"title": "Rank Push Tonight?", "message": "Nearby cafe me setup ready, abhi slot book kar."},
    {"title": "Aaj Ka Plan Sorted", "message": "Game, snacks, squad vibes, bas slot confirm karo."},
    {"title": "Don’t Get Queue-Lagged", "message": "Late mat ho, peak time slots abhi grab karo."},
    {"title": "GG Starts At Café", "message": "Console ready hai boss, jaldi se booking kar."},
    {"title": "Weekend Grind Alert", "message": "High FPS, low wait, apna slot abhi reserve karo."},
    {"title": "Lobby Full Hone Wali", "message": "Jaldi tap karo and your gaming seat secure karo."},
    {"title": "Noob Move: Delay", "message": "Pro move: slot book now and squad ko ping."},
    {"title": "Aaj Scene Banega", "message": "Nearby gaming cafe me apni seat abhi lock karo."},
    {"title": "Your Setup Is Calling", "message": "Controller uthao, slot book karo, match shuru karo."},
    {"title": "Night Grind Loading", "message": "Respawn mat karo, direct booking karke entry lo."},
    {"title": "Low Ping, High Hype", "message": "Cafe ready hai, bas tumhari booking pending hai."},
    {"title": "Last Seats, Fast Fingers", "message": "Jaldi karo bro, warna waitlist mode on ho jayega."},
    {"title": "Play IRL Tonight", "message": "Squad ke saath cafe plan fix, abhi slot reserve karo."},
    {"title": "Drop In, Dominate Out", "message": "Your next win starts with one quick booking tap."},
    {"title": "Game Mood On", "message": "Aaj ka slot secure karo and full power grind karo."},
    {"title": "Cafe Loot Live", "message": "Nearby seats open hain, before rush book now."},
    {"title": "Boss Battle Tonight?", "message": "Apna battlestation pakka karo, booking abhi karo."},
    {"title": "Tap. Book. Game.", "message": "Simple scene: slot book karo and GG le aao."}
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
