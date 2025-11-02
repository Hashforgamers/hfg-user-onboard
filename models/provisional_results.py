from sqlalchemy import UUID, Column, Integer, DateTime, text
from sqlalchemy.orm import relationship
from db.extensions import db


class ProvisionalResults(db.Model):
    __tablename__ = "provisional_results"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id = Column(UUID(as_uuid=True), nullable=False)
    team_id = Column(UUID(as_uuid=True), nullable=False)
    proposed_rank = Column(Integer, nullable=False)
    submitted_by_vendor = Column(Integer, nullable=False)

    # Timestamps
    published_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # relationships
    team = relationship(
        "Team",
        foreign_keys=[team_id],
        back_populates="provisional_results",
    )

    event = relationship(
        "Event",
        foreign_keys=[event_id],
        back_populates="provisional_results",
    )

    vendor_id = relationship(
        "User",
        foreign_keys=[submitted_by_vendor],
        back_populates="provisional_results",
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "event_id": str(self.event_id),
            "team_id": str(self.team_id),
            "proposed_rank": self.proposed_rank,
            "submitted_by_vendor": self.submitted_by_vendor,
            "published_at": self.published_at.isoformat(),
        }
