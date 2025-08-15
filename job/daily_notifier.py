import os
import time
import requests
import logging
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
NOTIFY_INTERVAL = int(os.getenv("NOTIFY_INTERVAL", "60"))  # seconds

# ----------------------------
# Gemini Setup
# ----------------------------
genai.configure(api_key=API_KEY)
PROMPT_TEMPLATE = """
You are HASH for Gamers, India's first gaming café booking platform.
Create a short, catchy push notification for gamers about booking slots at nearby gaming cafés.

Guidelines:
- Title: max 7 words, exciting & gaming-themed.
- Message: 1 sentence, friendly & casual, encourage immediate booking.

Return JSON in format:
{
  "title": "...",
  "message": "..."
}
"""

def generate_notification():
    logger.info("Generating notification content using Gemini...")
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content(PROMPT_TEMPLATE)
    try:
        content = response.text.strip()
        notif = eval(content)  # Convert JSON-like string to dict
        logger.info(f"Generated title: {notif['title']}")
        return notif
    except Exception as e:
        logger.error(f"Error parsing Gemini response: {e}")
        return {
            "title": "Game On!",
            "message": "Book your slot now at your local café!"
        }

def main():
    start_time = datetime.now()
    logger.info("Starting daily notification job...")

    while True:
        logger.info("Fetching FCM tokens...")
        resp = requests.get(f"{API_BASE}/getAllFCMToken")
        if resp.status_code != 200:
            logger.error(f"Error fetching tokens: {resp.text}")
            time.sleep(NOTIFY_INTERVAL)
            continue

        data = resp.json().get("data", [])
        logger.info(f"Found {len(data)} tokens to notify.")

        for entry in data:
            token = entry["token"]
            notif = generate_notification()

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
