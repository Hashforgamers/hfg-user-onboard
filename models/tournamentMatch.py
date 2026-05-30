from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
from db.extensions import db


class MatchStatus:
    PENDING = "pending"
    READY = "ready"
    LOBBY_CREATED = "lobby_created"
    IN_PROGRESS = "in_progress"
    AWAITING_RESULTS = "awaiting_results"
    DISPUTED = "disputed"
    COMPLETED = "completed"
    ADMIN_CLOSED = "admin_closed"


class TournamentMatch(db.Model):
    __tablename__ = "tournament_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)
    match_number = Column(Integer, nullable=False)
    status = Column(String(32), default=MatchStatus.PENDING, nullable=False, index=True)
    team_a_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    team_b_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    winner_team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    scheduled_at = Column(DateTime(timezone=True))
    lobby_instructions = Column(Text)
    map_name = Column(String(80))
    server_region = Column(String(80))
    admin_notes = Column(Text)
    map_pool = Column(JSONB, default=list)
    veto_mode = Column(String(64), default="none", nullable=False)
    team_a_captain_confirmed_at = Column(DateTime(timezone=True))
    team_b_captain_confirmed_at = Column(DateTime(timezone=True))
    observer_user_id = Column(Integer)
    stream_url = Column(Text)
    match_timer_started_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
