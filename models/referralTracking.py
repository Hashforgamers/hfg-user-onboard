from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from db.extensions import db

class ReferralTracking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    referrer_code = db.Column(db.String(10))
    referred_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
