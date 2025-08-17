# models/booking.py
from sqlalchemy import Column, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime
import pytz

from .availableGame import AvailableGame
from .slot import Slot
from .accessBookingCode import AccessBookingCode

# Helper function to return current IST time
def current_time_ist():
    return datetime.now(pytz.timezone("Asia/Kolkata"))

class Booking(db.Model):
    __tablename__ = 'bookings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    game_id = Column(Integer, nullable=False)
    slot_id = Column(Integer, nullable=False)
    status = db.Column(db.String(20), default='pending_verified')

    # ✅ Auto timestamps with IST
    created_at = Column(DateTime(timezone=True), default=current_time_ist, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=current_time_ist, onupdate=current_time_ist, nullable=False)

    def __repr__(self):
        return f"<Booking user_id={self.user_id} game_id={self.game_id}>"
