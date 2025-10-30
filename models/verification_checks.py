from sqlalchemy import (
    UUID,
    Column,
    String,
    DateTime,
    text,
)
from sqlalchemy.orm import relationship
from db.extensions import db


class VerificationChecks(db.Model):
    __tablename__ = "verification_checks"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id = Column(UUID(as_uuid=True), nullable=False)
    flag = Column(String(100), nullable=False)
    details = Column(String(500), nullable=True)
    team_id = Column(UUID(as_uuid=True), nullable=False)

    # Timestamps

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # relationships
    team_id = relationship(
        "Team",
        foreign_keys=[team_id],
        back_populates="verification_checks",
    )

    event_id = relationship(
        "Event",
        foreign_keys=[event_id],
        back_populates="verification_checks",
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "event_id": str(self.event_id),
            "flag": self.flag,
            "details": self.details,
            "team_id": str(self.team_id),
            "created_at": self.created_at.isoformat(),
        }
