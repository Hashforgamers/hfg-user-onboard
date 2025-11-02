from sqlalchemy import Column, BigInteger, String, Text, Boolean, DateTime, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from db.extensions import db

class EventStatus:
    DRAFT = "draft"
    PUBLISHED = "published"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELED = "canceled"

class Event(db.Model):
    __tablename__ = 'events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(BigInteger, ForeignKey('vendors.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    registration_fee = Column(Numeric(10,2), default=0, nullable=False)
    currency = Column(String(8), default="INR", nullable=False)
    registration_deadline = Column(DateTime(timezone=True))
    capacity_team = Column(Integer)
    capacity_player = Column(Integer)
    min_team_size = Column(Integer, default=1, nullable=False)
    max_team_size = Column(Integer, default=5, nullable=False)
    allow_solo = Column(Boolean, default=False, nullable=False)
    allow_individual = Column(Boolean, default=False, nullable=False)
    qr_code_url = Column(Text)
    status = Column(String(24), default=EventStatus.DRAFT, nullable=False)
    visibility = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    teams = relationship('Team', back_populates='event', cascade="all, delete-orphan")
    registrations = relationship('Registration', back_populates='event', cascade="all, delete-orphan")

    __table_args__ = (
        db.CheckConstraint('min_team_size <= max_team_size', name='ck_event_team_size_range'),
    )
