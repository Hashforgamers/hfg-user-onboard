from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from db.extensions import db


class MatchResultSubmission(db.Model):
    __tablename__ = "match_result_submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("tournament_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    submitted_by_user = Column(BigInteger)
    submitted_by_vendor = Column(BigInteger)
    winner_team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    team_a_score = Column(Integer)
    team_b_score = Column(Integer)
    screenshot_url = Column(Text)
    notes = Column(Text)
    status = Column(String(32), default="submitted", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
