import uuid
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
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
    reported_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reason = Column(String(120), nullable=False)
    description = Column(Text, nullable=False)
    evidence_asset_ids = Column(JSONB, nullable=False, default=list)
    status = Column(String(32), nullable=False, default=CommunityDisputeStatus.OPEN, index=True)
    admin_comment = Column(Text, nullable=True)
    reviewed_by_admin_id = Column(BigInteger, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "result_id": str(self.result_id) if self.result_id else None,
            "reported_by_user_id": int(self.reported_by_user_id) if self.reported_by_user_id else None,
            "reason": self.reason,
            "description": self.description,
            "evidence_asset_ids": self.evidence_asset_ids or [],
            "status": self.status,
            "admin_comment": self.admin_comment,
            "reviewed_by_admin_id": self.reviewed_by_admin_id,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityTournamentPayout(db.Model):
    __tablename__ = "community_tournament_payouts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=True)
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
