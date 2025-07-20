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
