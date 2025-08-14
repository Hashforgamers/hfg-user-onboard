# firebase_service.py
import firebase_admin
from firebase_admin import credentials, messaging
from flask import current_app

firebase_app = None  # Global variable to store the initialized app

def init_firebase():
    global firebase_app
    if not firebase_app:
        cred = credentials.Certificate(current_app.config['FIREBASE_KEY'])
        firebase_app = firebase_admin.initialize_app(cred)

def send_notification(token, title, body, data=None):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=token,
            data=data or {},
        )
        response = messaging.send(message)
        print('Successfully sent message:', response)
    except Exception as e:
        # Log the failure but don’t raise it up
        print(f"⚠️ Failed to send notification to token={token}: {e}")

def notify_user_all_tokens(user, title, message):
    """
    Send an FCM notification to all of a user's registered devices.
    Failures are logged but won't break the user flow.
    """
    if user and user.fcm_tokens:
        for token_obj in user.fcm_tokens:
            send_notification(token_obj.token, title, message)
