from sqlalchemy import UUID, Column, Integer, String, DateTime, text
from sqlalchemy.orm import relationship
from db.extensions import db


class Team(db.Model):
    __tablename__ = "teams"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    events_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(255), nullable=False)
    is_individual = Column(
        Integer, nullable=False, default=0
    )  # 0 for team, 1 for individual
    created_by = Column(Integer, nullable=False)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # Relationships
    members = relationship(
        "User", secondary="team_members", back_populates="teams", cascade="all, delete"
    )

    event = relationship("Event", foreign_keys=[events_id], back_populates="teams")

    def to_dict(self):
        return {
            "id": str(self.id),
            "events_id": str(self.events_id),
            "name": self.name,
            "is_individual": self.is_individual,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }
