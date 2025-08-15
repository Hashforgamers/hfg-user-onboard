import os
import time
import requests
import google.generativeai as genai
from datetime import datetime

# ENV vars
API_BASE = os.getenv("API_BASE", "https://hfg-user-onboard.onrender.com")
API_KEY = os.getenv("API_KEY", "AIzaSyCMVuu_Ng2THRn4_YaM4-_HjWUlTeBCRv0")  # Your Gemini API key
NOTIFY_INTERVAL = int(os.getenv("NOTIFY_INTERVAL", "60"))  # seconds

# Configure Gemini
genai.configure(api_key=API_KEY)

PROMPT_TEMPLATE = """
You are HASH for Gamers, India's first gaming café booking platform.
Create a short, catchy push notification for gamers about booking slots at nearby gaming cafés.

Guidelines:
- Title: max 7 words, exciting & gaming-themed.
- Message: 1 sentence, friendly & casual, encourage immediate booking.

Return JSON in format:
{{
  "title": "...",
  "message": "..."
}}
"""

def generate_notification():
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content(PROMPT_TEMPLATE)
    try:
        content = response.text.strip()
        return eval(content)  # Convert JSON-like string to dict
    except Exception:
        return {
            "title": "Game On!",
            "message": "Book your slot now at your local café!"
        }

def main():
    while True:
        print(f"[{datetime.now()}] Fetching tokens...")
        resp = requests.get(f"{API_BASE}/getAllFCMToken")
        if resp.status_code != 200:
            print("Error fetching tokens:", resp.text)
            time.sleep(NOTIFY_INTERVAL)
            continue

        data = resp.json().get("data", [])
        print(f"Found {len(data)} tokens.")

        for entry in data:
            token = entry["token"]
            notif = generate_notification()

            payload = {
                "token": token,
                "title": notif["title"],
                "message": notif["message"]
            }
            r = requests.post(f"{API_BASE}/notify-user", json=payload)
            print(f"Sent to {token[:10]}... Status {r.status_code}")

        print(f"Sleeping {NOTIFY_INTERVAL} seconds...")
        time.sleep(NOTIFY_INTERVAL)

if __name__ == "__main__":
    main()
