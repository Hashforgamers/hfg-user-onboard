from sqlalchemy import (
    UUID,
    Column,
    String,
    DateTime,
    text,
)
from sqlalchemy.orm import relationship
from db.extensions import db


class TeamMembers(db.Model):
    __tablename__ = "team_members"

    team_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    role = Column(String, nullable=False)

    # Timestamps
    joined_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # relationships
    team = relationship(
        "Team",
        foreign_keys=[team_id],
        back_populates="members",
    )

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="team_memberships",
    )

    def to_dict(self):
        return {
            "team_id": str(self.team_id),
            "user_id": str(self.user_id),
            "role": self.role,
            "joined_at": self.joined_at.isoformat(),
        }
