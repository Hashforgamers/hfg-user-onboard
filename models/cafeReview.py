import uuid
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from db.extensions import db


class CafeReview(db.Model):
    __tablename__ = "cafe_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Keep booking_id as plain integer because the booking table lives in another service/schema.
    # Enforcing a FK here breaks ORM flush if the bookings table isn't in this service's metadata.
    booking_id = Column(Integer, nullable=True, index=True)

    rating = Column(Integer, nullable=False)
    title = Column(String(120), nullable=True)
    comment = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="published")
    is_anonymous = Column(Boolean, nullable=False, default=False)

    user_name_snapshot = Column(String(120), nullable=True)
    user_avatar_snapshot = Column(String(255), nullable=True)

    response_text = Column(Text, nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    responded_by = Column(String(120), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_cafe_reviews_booking_id"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_cafe_reviews_rating"),
        Index("ix_cafe_reviews_vendor_status", "vendor_id", "status"),
        Index("ix_cafe_reviews_created_at", "created_at"),
    )
