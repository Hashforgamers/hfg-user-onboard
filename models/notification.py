import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from db.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(db.BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(64), nullable=False, index=True)
    reference_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "type": self.type,
            "reference_id": self.reference_id,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
