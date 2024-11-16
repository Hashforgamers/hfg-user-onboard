from models import User
from db.extensions import db
from utils.firebase_verification import verify_firebase_token
from datetime import datetime

class UserService:

    @staticmethod
    def login_or_create_user(id_token):
        """Verify the Firebase ID token and either log the user in or create a new user."""
        user_info = verify_firebase_token(id_token)
        if not user_info:
            return None, "Invalid or expired token"
        
        email = user_info.get("email")
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Update last login time for the existing user
            user.update_last_login()
            db.session.commit()
            return user, "Login successful"
        else:
            # Create new user if not found
            name = user_info.get("name", "")
            user = User(email=email, name=name)
            db.session.add(user)
            db.session.commit()
            return user, "User created successfully"

    @staticmethod
    def get_user_by_id(user_id):
        """Fetch user details by user ID."""
        user = User.query.get(user_id)
        if user:
            return user.to_dict()
        return None
