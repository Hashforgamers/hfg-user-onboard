# models/deleted_user_cooldown.py
from sqlalchemy import Column, Integer, String, DateTime, func
from db.extensions import db
from datetime import datetime, timedelta

class DeletedUserCooldown(db.Model):
    __tablename__ = "deleted_user_cooldown"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)
    referred_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime, nullable=False)

    def __init__(self, email, phone, referred_by=None):
        self.email = email
        self.phone = phone
        self.referred_by = referred_by
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(days=30)
