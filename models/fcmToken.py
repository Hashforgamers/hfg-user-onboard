from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime

# models/fcmToken.py
class FCMToken(db.Model):
    __tablename__ = 'fcm_tokens'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    token = Column(String(512), unique=True, nullable=False)
    platform = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="fcm_tokens")
