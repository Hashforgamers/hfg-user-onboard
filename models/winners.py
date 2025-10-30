from sqlalchemy import UUID, Column, Integer, DateTime, text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from db.extensions import db


class Winners(db.Model):
    __tablename__ = "winners"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id = Column(UUID(as_uuid=True), nullable=False)
    team_id = Column(UUID(as_uuid=True), nullable=False)
    rank = Column(Integer, nullable=False)
    verified_snapshot = Column(JSONB, nullable=True)

    # Timestamps
    published_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # relationships
    team_id = relationship(
        "Team",
        foreign_keys=[team_id],
        back_populates="winners",
    )

    event_id = relationship(
        "Event",
        foreign_keys=[event_id],
        back_populates="winners",
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "event_id": str(self.event_id),
            "team_id": str(self.team_id),
            "rank": self.rank,
            "verified_snapshot": self.verified_snapshot,
            "published_at": self.published_at.isoformat(),
        }
