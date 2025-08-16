import os
import time
import requests
import logging
import random
import json
import google.generativeai as genai
from datetime import datetime

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
API_KEY = os.getenv("API_KEY", "AIzaSyCMVuu_Ng2THRn4_YaM4-_HjWUlTeBCRv0") 
NOTIFY_INTERVAL = int(os.getenv("NOTIFY_INTERVAL", "7200"))  # seconds

# ----------------------------
# Gemini Setup
# ----------------------------
genai.configure(api_key=API_KEY)
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
    return genai.GenerativeModel("gemini-2.5-flash")

def generate_notification():
    logger = logging.getLogger(__name__)
    model = gemini_agent()

    logger.info("Generating notification with HASH agent...")

    try:
        response = model.generate_content(HASH_AGENT_PROMPT)
        raw_text = response.text.strip()
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

def main():
    start_time = datetime.now()
    logger.info("Starting daily notification job...")

    while True:
        if is_within_time_window():
            logger.info("Fetching FCM tokens (within notification window 6AM-10PM IST)...")
            resp = requests.get(f"{API_BASE}/getAllFCMToken")
            if resp.status_code != 200:
                logger.error(f"Error fetching tokens: {resp.text}")
                time.sleep(NOTIFY_INTERVAL)
                continue
        else:
            current_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
            logger.info(f"Skipping notifications (outside window 6AM-10PM IST, current IST time: {current_ist.strftime('%H:%M')})")
            time.sleep(NOTIFY_INTERVAL)
            continue

        data = resp.json().get("data", [])
        if data:  # Only generate notification if we have recipients
            logger.info(f"Found {len(data)} tokens to notify.")
            notif = generate_notification()

            for entry in data:
                token = entry["token"]
                payload = {
                    "token": token,
                    "title": notif["title"],
                    "message": notif["message"]
                }
                r = requests.post(f"{API_BASE}/notify-user", json=payload)
                logger.info(f"Sent to {token[:10]}... Status {r.status_code}")

        logger.info(f"Sleeping {NOTIFY_INTERVAL} seconds...")
        time.sleep(NOTIFY_INTERVAL)

if __name__ == "__main__":
    main()
