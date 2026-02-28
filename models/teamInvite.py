import uuid
from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from db.extensions import db


class TeamInvite(db.Model):
    __tablename__ = "team_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    inviter_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending|accepted|rejected|cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'cancelled')", name="ck_team_invites_status"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "event_id": str(self.event_id),
            "team_id": str(self.team_id),
            "inviter_user_id": self.inviter_user_id,
            "invited_user_id": self.invited_user_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
        }
