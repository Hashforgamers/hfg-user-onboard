import firebase_admin
from firebase_admin import credentials, auth
from firebase_admin.exceptions import FirebaseError
from flask import current_app

# Initialize Firebase Admin SDK
cred = credentials.Certificate("path/to/firebase-admin-sdk.json")
firebase_admin.initialize_app(cred)

def verify_firebase_token(id_token):
    """Verify Firebase ID token and extract user info."""
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token  # returns a dictionary with user info
    except FirebaseError as e:
        current_app.logger.error(f"Firebase token verification failed: {e}")
        return None
