from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from db.extensions import db


class Events(db.Model):
    __tablename__ = "events"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    registrations_fee = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)
    capacity_team = Column(Integer, nullable=False)
    capacity_player = Column(Integer, nullable=False)
    max_team_size = Column(Integer, nullable=False)
    min_team_size = Column(Integer, nullable=False)
    allow_solo = Column(Boolean, nullable=False, default=False)
    qr_code_url = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="upcoming")
    visibility = Column(String, nullable=False, default="public")
    vendor_id = Column(BigInteger, nullable=False)

    # Timestamps
    start_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    registration_deadline = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        onupdate=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # relationships
    provisional_results = relationship(
        "ProvisionalResults",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    vendor_id = relationship(
        "Vendor",
        foreign_keys=[vendor_id],
        back_populates="events",
    )


def to_dict(self):
    return {
        "id": str(self.id),
        "title": self.title,
        "description": self.description,
        "registrations_fee": self.registrations_fee,
        "currency": self.currency,
        "capacity_team": self.capacity_team,
        "capacity_player": self.capacity_player,
        "max_team_size": self.max_team_size,
        "min_team_size": self.min_team_size,
        "allow_solo": self.allow_solo,
        "qr_code_url": self.qr_code_url,
        "status": self.status,
        "visibility": self.visibility,
        "vendor_id": self.vendor_id,
        "start_at": self.start_at.isoformat() if self.start_at else None,
        "end_at": self.end_at.isoformat() if self.end_at else None,
        "registration_deadline": self.registration_deadline.isoformat()
        if self.registration_deadline
        else None,
        "created_at": self.created_at.isoformat() if self.created_at else None,
        "updated_at": self.updated_at.isoformat() if self.updated_at else None,
    }
