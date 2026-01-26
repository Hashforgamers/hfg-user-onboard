from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from db.extensions import db

class Registration(db.Model):
    __tablename__ = 'registrations'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, index=True)
    contact_name = Column(String(120))
    contact_phone = Column(String(32))
    contact_email = Column(String(120))
    waiver_signed = Column(Boolean, default=False, nullable=False)
    payment_status = Column(String(24), default='pending', nullable=False)
    status = Column(String(24), default='pending', nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    event = relationship('Event', back_populates='registrations')
