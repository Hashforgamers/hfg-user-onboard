import uuid
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from db.extensions import db


class CommunityResultStatus:
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    ADMIN_OVERRIDDEN = "admin_overridden"


class CommunityDisputeStatus:
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLOSED = "closed"


class CommunityPayoutStatus:
    PENDING_ADMIN_APPROVAL = "pending_admin_approval"
    APPROVED = "approved"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommunityPaymentSettlementStatus:
    PENDING = "pending"
    RETRY = "retry"
    PROCESSING = "processing"
    SETTLED = "settled"
    FAILED = "failed"


class CommunityTeamStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISQUALIFIED = "disqualified"


class CommunityMatchStatus:
    SCHEDULED = "scheduled"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    AWAITING_RESULTS = "awaiting_results"
    RESULT_PENDING = "result_pending"
    DISPUTED = "disputed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CommunityTournamentTeam(db.Model):
    __tablename__ = "community_tournament_teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    registration_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_registrations.id", ondelete="CASCADE"), nullable=False, unique=True)
    captain_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    status = Column(String(32), nullable=False, default=CommunityTeamStatus.PENDING, index=True)
    seed_number = Column(Integer, nullable=True)
    roster_locked_at = Column(DateTime(timezone=True), nullable=True)
    checked_in_at = Column(DateTime(timezone=True), nullable=True)
    warning_count = Column(Integer, nullable=False, default=0)
    rejection_reason = Column(Text, nullable=True)
    disqualification_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_community_team_name", "tournament_id", "name", unique=True),
        Index("uq_community_team_seed", "tournament_id", "seed_number", unique=True, postgresql_where=db.text("seed_number IS NOT NULL")),
        CheckConstraint("warning_count >= 0", name="ck_community_team_warning_count"),
        CheckConstraint("seed_number IS NULL OR seed_number > 0", name="ck_community_team_seed_positive"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "registration_id": str(self.registration_id),
            "captain_user_id": int(self.captain_user_id),
            "name": self.name,
            "status": self.status,
            "seed_number": self.seed_number,
            "roster_locked_at": self.roster_locked_at.isoformat() if self.roster_locked_at else None,
            "checked_in_at": self.checked_in_at.isoformat() if self.checked_in_at else None,
            "warning_count": int(self.warning_count or 0),
            "rejection_reason": self.rejection_reason,
            "disqualification_reason": self.disqualification_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityTournamentTeamMember(db.Model):
    __tablename__ = "community_tournament_team_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(24), nullable=False, default="player")
    game_id = Column(String(120), nullable=False)
    verification_status = Column(String(24), nullable=False, default="pending")
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_community_team_member", "team_id", "user_id", unique=True),
        Index(
            "uq_community_tournament_accepted_member",
            "tournament_id",
            "user_id",
            unique=True,
            postgresql_where=db.text("verification_status IN ('accepted', 'verified')"),
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "team_id": str(self.team_id),
            "user_id": int(self.user_id),
            "role": self.role,
            "game_id": self.game_id,
            "verification_status": self.verification_status,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


class CommunityTournamentMatch(db.Model):
    __tablename__ = "community_tournament_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String(32), nullable=False, default="bracket")
    round_number = Column(Integer, nullable=False)
    match_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default=CommunityMatchStatus.SCHEDULED, index=True)
    team_a_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="SET NULL"), nullable=True, index=True)
    team_b_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="SET NULL"), nullable=True, index=True)
    participant_team_ids = Column(JSONB, nullable=False, default=list)
    winner_team_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="SET NULL"), nullable=True)
    next_match_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_matches.id", ondelete="SET NULL"), nullable=True)
    next_match_slot = Column(String(1), nullable=True)
    team_a_score = Column(Integer, nullable=True)
    team_b_score = Column(Integer, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    result_due_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    lobby_details = Column(JSONB, nullable=False, default=dict)
    standings = Column(JSONB, nullable=False, default=list)
    stream_url = Column(Text, nullable=True)
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_community_match_slot", "tournament_id", "stage", "round_number", "match_number", unique=True),
        CheckConstraint("team_a_score IS NULL OR team_a_score >= 0", name="ck_community_match_team_a_score"),
        CheckConstraint("team_b_score IS NULL OR team_b_score >= 0", name="ck_community_match_team_b_score"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "stage": self.stage,
            "round_number": self.round_number,
            "match_number": self.match_number,
            "status": self.status,
            "team_a_id": str(self.team_a_id) if self.team_a_id else None,
            "team_b_id": str(self.team_b_id) if self.team_b_id else None,
            "participant_team_ids": self.participant_team_ids or [],
            "winner_team_id": str(self.winner_team_id) if self.winner_team_id else None,
            "next_match_id": str(self.next_match_id) if self.next_match_id else None,
            "next_match_slot": self.next_match_slot,
            "team_a_score": self.team_a_score,
            "team_b_score": self.team_b_score,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "result_due_at": self.result_due_at.isoformat() if self.result_due_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "lobby_details": self.lobby_details or {},
            "standings": self.standings or [],
            "stream_url": self.stream_url,
            "admin_notes": self.admin_notes,
        }


class CommunityMatchResultSubmission(db.Model):
    __tablename__ = "community_match_result_submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="CASCADE"), nullable=False)
    submitted_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    winner_team_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="SET NULL"), nullable=True)
    team_a_score = Column(Integer, nullable=True)
    team_b_score = Column(Integer, nullable=True)
    evidence_asset_ids = Column(JSONB, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="submitted")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("uq_community_match_submission_team", "match_id", "team_id", unique=True),)

    def to_dict(self):
        return {
            "id": str(self.id),
            "match_id": str(self.match_id),
            "team_id": str(self.team_id),
            "submitted_by_user_id": int(self.submitted_by_user_id) if self.submitted_by_user_id else None,
            "winner_team_id": str(self.winner_team_id) if self.winner_team_id else None,
            "team_a_score": self.team_a_score,
            "team_b_score": self.team_b_score,
            "evidence_asset_ids": self.evidence_asset_ids or [],
            "notes": self.notes,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CommunityMatchResultProposal(db.Model):
    __tablename__ = "community_match_result_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    match_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    proposed_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    winner_team_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_teams.id", ondelete="RESTRICT"), nullable=False)
    team_a_score = Column(Integer, nullable=False)
    team_b_score = Column(Integer, nullable=False)
    evidence_asset_ids = Column(JSONB, nullable=False, default=list)
    evidence_urls = Column(JSONB, nullable=False, default=list)
    ocr_data = Column(JSONB, nullable=False, default=dict)
    accepted_team_ids = Column(JSONB, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="pending", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    disputed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_community_pending_result_proposal", "match_id", unique=True, postgresql_where=db.text("status = 'pending'")),
        CheckConstraint("team_a_score >= 0", name="ck_community_result_proposal_team_a_score"),
        CheckConstraint("team_b_score >= 0", name="ck_community_result_proposal_team_b_score"),
    )

    def to_dict(self):
        return {
            "id": str(self.id), "tournament_id": str(self.tournament_id), "match_id": str(self.match_id),
            "proposed_by_user_id": int(self.proposed_by_user_id) if self.proposed_by_user_id else None,
            "winner_team_id": str(self.winner_team_id), "team_a_score": self.team_a_score,
            "team_b_score": self.team_b_score, "evidence_asset_ids": self.evidence_asset_ids or [],
            "evidence_urls": self.evidence_urls or [], "ocr_data": self.ocr_data or {},
            "accepted_team_ids": self.accepted_team_ids or [], "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None,
            "disputed_at": self.disputed_at.isoformat() if self.disputed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CommunityTournamentAnnouncement(db.Model):
    __tablename__ = "community_tournament_announcements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    audience = Column(String(32), nullable=False, default="all_participants")
    target_team_ids = Column(JSONB, nullable=False, default=list)
    published_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "created_by_user_id": int(self.created_by_user_id) if self.created_by_user_id else None,
            "title": self.title,
            "message": self.message,
            "audience": self.audience,
            "target_team_ids": self.target_team_ids or [],
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


class CommunityTournamentReview(db.Model):
    __tablename__ = "community_tournament_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    host_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    management_rating = Column(Integer, nullable=False)
    communication_rating = Column(Integer, nullable=False)
    fairness_rating = Column(Integer, nullable=False)
    scheduling_rating = Column(Integer, nullable=False)
    dispute_handling_rating = Column(Integer, nullable=False)
    overall_rating = Column(Numeric(3, 2), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_community_tournament_reviewer", "tournament_id", "reviewer_user_id", unique=True),
        CheckConstraint("management_rating BETWEEN 1 AND 5", name="ck_community_review_management"),
        CheckConstraint("communication_rating BETWEEN 1 AND 5", name="ck_community_review_communication"),
        CheckConstraint("fairness_rating BETWEEN 1 AND 5", name="ck_community_review_fairness"),
        CheckConstraint("scheduling_rating BETWEEN 1 AND 5", name="ck_community_review_scheduling"),
        CheckConstraint("dispute_handling_rating BETWEEN 1 AND 5", name="ck_community_review_disputes"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "host_user_id": int(self.host_user_id),
            "reviewer_user_id": int(self.reviewer_user_id),
            "management_rating": self.management_rating,
            "communication_rating": self.communication_rating,
            "fairness_rating": self.fairness_rating,
            "scheduling_rating": self.scheduling_rating,
            "dispute_handling_rating": self.dispute_handling_rating,
            "overall_rating": float(self.overall_rating or 0),
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CommunityMatchResult(db.Model):
    __tablename__ = "community_match_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    submitted_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    winner_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    rank = Column(Integer, nullable=True)
    score = Column(String(80), nullable=True)
    evidence_asset_ids = Column(JSONB, nullable=False, default=list)
    stream_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default=CommunityResultStatus.SUBMITTED, index=True)
    verified_by_user_id = Column(BigInteger, nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_community_results_tournament_rank", "tournament_id", "rank"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "submitted_by_user_id": int(self.submitted_by_user_id) if self.submitted_by_user_id else None,
            "winner_user_id": int(self.winner_user_id) if self.winner_user_id else None,
            "rank": self.rank,
            "score": self.score,
            "evidence_asset_ids": self.evidence_asset_ids or [],
            "stream_url": self.stream_url,
            "notes": self.notes,
            "status": self.status,
            "verified_by_user_id": self.verified_by_user_id,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityTournamentDispute(db.Model):
    __tablename__ = "community_tournament_disputes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    result_id = Column(UUID(as_uuid=True), ForeignKey("community_match_results.id", ondelete="SET NULL"), nullable=True, index=True)
    match_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_matches.id", ondelete="SET NULL"), nullable=True, index=True)
    reported_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reason = Column(String(120), nullable=False)
    description = Column(Text, nullable=False)
    evidence_asset_ids = Column(JSONB, nullable=False, default=list)
    status = Column(String(32), nullable=False, default=CommunityDisputeStatus.OPEN, index=True)
    admin_comment = Column(Text, nullable=True)
    reviewed_by_admin_id = Column(BigInteger, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    response_deadline_at = Column(DateTime(timezone=True), nullable=True)
    resolution_action = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "result_id": str(self.result_id) if self.result_id else None,
            "match_id": str(self.match_id) if self.match_id else None,
            "reported_by_user_id": int(self.reported_by_user_id) if self.reported_by_user_id else None,
            "reason": self.reason,
            "description": self.description,
            "evidence_asset_ids": self.evidence_asset_ids or [],
            "status": self.status,
            "admin_comment": self.admin_comment,
            "reviewed_by_admin_id": self.reviewed_by_admin_id,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "response_deadline_at": self.response_deadline_at.isoformat() if self.response_deadline_at else None,
            "resolution_action": self.resolution_action,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityTournamentPayout(db.Model):
    __tablename__ = "community_tournament_payouts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=True)
    payout_type = Column(String(32), nullable=False, default="player_prize", index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    status = Column(String(32), nullable=False, default=CommunityPayoutStatus.PENDING_ADMIN_APPROVAL, index=True)
    approved_by_admin_id = Column(BigInteger, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    wallet_transaction_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "user_id": int(self.user_id),
            "rank": self.rank,
            "payout_type": self.payout_type,
            "amount": float(self.amount or 0),
            "currency": self.currency,
            "status": self.status,
            "approved_by_admin_id": self.approved_by_admin_id,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "wallet_transaction_id": self.wallet_transaction_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityAuditLog(db.Model):
    __tablename__ = "community_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id = Column(BigInteger, nullable=True, index=True)
    actor_type = Column(String(32), nullable=False, default="user", index=True)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(80), nullable=False, index=True)
    entity_id = Column(String(80), nullable=False, index=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "actor_user_id": int(self.actor_user_id) if self.actor_user_id else None,
            "actor_type": self.actor_type,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "metadata": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CommunityPaymentSettlementJob(db.Model):
    """Durable retry record for a paid community registration."""

    __tablename__ = "community_payment_settlement_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    registration_id = Column(UUID(as_uuid=True), ForeignKey("community_tournament_registrations.id", ondelete="CASCADE"), nullable=False, index=True)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(32), nullable=False, default="razorpay", index=True)
    payment_id = Column(String(120), nullable=True, index=True)
    order_id = Column(String(120), nullable=True, index=True)
    status = Column(String(32), nullable=False, default=CommunityPaymentSettlementStatus.PENDING, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_community_payment_settlement_job_registration", "registration_id", unique=True),
        Index("ix_community_payment_settlement_ready", "status", "next_attempt_at"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "registration_id": str(self.registration_id),
            "tournament_id": str(self.tournament_id),
            "provider": self.provider,
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "status": self.status,
            "attempts": int(self.attempts or 0),
            "next_attempt_at": self.next_attempt_at.isoformat() if self.next_attempt_at else None,
            "last_error": self.last_error,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
