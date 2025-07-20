import firebase_admin
from firebase_admin import credentials, messaging
from flask import current_app

# Initialize Firebase Admin SDK (only once)
cred = credentials.Certificate(current_app.config['FIREBASE_KEY'])
firebase_admin.initialize_app(cred)

def send_notification(token, title, body, data=None):
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        token=token,
        data=data or {},  # Optional custom payload
    )
    response = messaging.send(message)
    print('Successfully sent message:', response)
