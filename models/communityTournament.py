import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.extensions import db


class CommunityHostStatus:
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class CommunityHostTier:
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class CommunityTournamentStatus:
    DRAFT = "draft"
    PUBLISHED = "published"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CommunityTournamentRegistrationStatus:
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class CommunityHostVerification(db.Model):
    __tablename__ = "community_host_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False)
    email = Column(String(254), nullable=False, index=True)
    phone = Column(String(32), nullable=False, index=True)
    government_id_asset_id = Column(UUID(as_uuid=True), ForeignKey("community_file_assets.id"), nullable=True)
    government_id_reference = Column(String(120), nullable=True)
    upi_id = Column(String(120), nullable=False)
    address = Column(Text, nullable=False)
    verification_status = Column(String(32), nullable=False, default=CommunityHostStatus.PENDING, index=True)
    host_tier = Column(String(32), nullable=False, default=CommunityHostTier.BRONZE, index=True)
    average_rating = Column(Numeric(3, 2), nullable=False, default=0)
    dispute_rate = Column(Numeric(5, 2), nullable=False, default=0)
    completion_rate = Column(Numeric(5, 2), nullable=False, default=0)
    on_time_payout_rate = Column(Numeric(5, 2), nullable=False, default=0)
    policy_violation_count = Column(Integer, nullable=False, default=0)
    rejection_reason = Column(Text, nullable=True)
    reviewed_by_admin_id = Column(BigInteger, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    government_id_asset = relationship("CommunityFileAsset", foreign_keys=[government_id_asset_id])

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": int(self.user_id),
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "government_id_asset_id": str(self.government_id_asset_id) if self.government_id_asset_id else None,
            "government_id_reference": self.government_id_reference,
            "upi_id": self.upi_id,
            "address": self.address,
            "verification_status": self.verification_status,
            "host_tier": self.host_tier,
            "average_rating": float(self.average_rating or 0),
            "dispute_rate": float(self.dispute_rate or 0),
            "completion_rate": float(self.completion_rate or 0),
            "on_time_payout_rate": float(self.on_time_payout_rate or 0),
            "policy_violation_count": int(self.policy_violation_count or 0),
            "rejection_reason": self.rejection_reason,
            "reviewed_by_admin_id": self.reviewed_by_admin_id,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityTournament(db.Model):
    __tablename__ = "community_tournaments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    banner_asset_id = Column(UUID(as_uuid=True), ForeignKey("community_file_assets.id"), nullable=True)
    banner_url = Column(Text, nullable=True)
    game = Column(String(80), nullable=False)
    tournament_type = Column(String(64), nullable=False, default="single_elimination")
    team_mode = Column(String(24), nullable=False, default="solo")
    entry_fee = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="INR")
    max_players = Column(Integer, nullable=False)
    registration_start_at = Column(DateTime(timezone=True), nullable=False)
    registration_end_at = Column(DateTime(timezone=True), nullable=False)
    tournament_start_at = Column(DateTime(timezone=True), nullable=False)
    tournament_end_at = Column(DateTime(timezone=True), nullable=True)
    rules = Column(Text, nullable=True)
    prize_distribution = Column(JSONB, nullable=False, default=list)
    discord_link = Column(Text, nullable=True)
    whatsapp_link = Column(Text, nullable=True)
    room_details = Column(Text, nullable=True)
    room_details_published_at = Column(DateTime(timezone=True), nullable=True)
    visibility = Column(Boolean, nullable=False, default=True, index=True)
    is_featured = Column(Boolean, nullable=False, default=False, index=True)
    status = Column(String(32), nullable=False, default=CommunityTournamentStatus.DRAFT, index=True)
    total_collection = Column(Numeric(12, 2), nullable=False, default=0)
    platform_fee_amount = Column(Numeric(12, 2), nullable=False, default=0)
    host_tier = Column(String(32), nullable=False, default=CommunityHostTier.BRONZE, index=True)
    organizer_commission_rate = Column(Numeric(5, 2), nullable=False, default=8)
    organizer_commission_amount = Column(Numeric(12, 2), nullable=False, default=0)
    prize_pool = Column(Numeric(12, 2), nullable=False, default=0)
    registered_players_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    registrations = relationship("CommunityTournamentRegistration", back_populates="tournament", cascade="all, delete-orphan")
    files = relationship("CommunityFileAsset", back_populates="tournament", foreign_keys="CommunityFileAsset.tournament_id")

    __table_args__ = (
        CheckConstraint("entry_fee >= 0", name="ck_community_tournament_entry_fee_non_negative"),
        CheckConstraint("max_players > 0", name="ck_community_tournament_max_players_positive"),
        CheckConstraint("registered_players_count >= 0", name="ck_community_tournament_registered_non_negative"),
        CheckConstraint("organizer_commission_rate >= 0 AND organizer_commission_rate <= 100", name="ck_community_tournament_commission_rate"),
        Index("ix_community_tournaments_discovery", "visibility", "status", "registration_start_at", "tournament_start_at"),
        Index("ix_community_tournaments_host_status", "host_user_id", "status"),
    )

    def to_dict(self, include_room_details=False):
        payload = {
            "id": str(self.id),
            "host_user_id": int(self.host_user_id),
            "title": self.title,
            "description": self.description,
            "banner_asset_id": str(self.banner_asset_id) if self.banner_asset_id else None,
            "banner_url": self.banner_url,
            "game": self.game,
            "tournament_type": self.tournament_type,
            "team_mode": self.team_mode,
            "entry_fee": float(self.entry_fee or 0),
            "currency": self.currency,
            "max_players": int(self.max_players or 0),
            "registration_start_at": self.registration_start_at.isoformat() if self.registration_start_at else None,
            "registration_end_at": self.registration_end_at.isoformat() if self.registration_end_at else None,
            "tournament_start_at": self.tournament_start_at.isoformat() if self.tournament_start_at else None,
            "tournament_end_at": self.tournament_end_at.isoformat() if self.tournament_end_at else None,
            "rules": self.rules,
            "prize_distribution": self.prize_distribution or [],
            "discord_link": self.discord_link,
            "whatsapp_link": self.whatsapp_link,
            "room_details_published_at": self.room_details_published_at.isoformat() if self.room_details_published_at else None,
            "visibility": bool(self.visibility),
            "is_featured": bool(self.is_featured),
            "status": self.status,
            "total_collection": float(self.total_collection or 0),
            "platform_fee_amount": float(self.platform_fee_amount or 0),
            "host_tier": self.host_tier,
            "organizer_commission_rate": float(self.organizer_commission_rate or 0),
            "organizer_commission_amount": float(self.organizer_commission_amount or 0),
            "prize_pool": float(self.prize_pool or 0),
            "registered_players_count": int(self.registered_players_count or 0),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_room_details:
            payload["room_details"] = self.room_details
        return payload


class CommunityTournamentRegistration(db.Model):
    __tablename__ = "community_tournament_registrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default=CommunityTournamentRegistrationStatus.PENDING_PAYMENT, index=True)
    payment_status = Column(String(32), nullable=False, default="pending", index=True)
    amount_paid = Column(Numeric(12, 2), nullable=False, default=0)
    payment_reference = Column(String(120), nullable=True, index=True)
    checked_in_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    tournament = relationship("CommunityTournament", back_populates="registrations")

    __table_args__ = (
        Index(
            "uq_community_tournament_active_registration",
            "tournament_id",
            "user_id",
            unique=True,
            postgresql_where=db.text("status NOT IN ('cancelled', 'refunded')"),
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "tournament_id": str(self.tournament_id),
            "user_id": int(self.user_id),
            "status": self.status,
            "payment_status": self.payment_status,
            "amount_paid": float(self.amount_paid or 0),
            "payment_reference": self.payment_reference,
            "checked_in_at": self.checked_in_at.isoformat() if self.checked_in_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityFileAsset(db.Model):
    __tablename__ = "community_file_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    tournament_id = Column(UUID(as_uuid=True), ForeignKey("community_tournaments.id", ondelete="CASCADE"), nullable=True, index=True)
    purpose = Column(String(64), nullable=False, index=True)
    file_url = Column(Text, nullable=False)
    storage_key = Column(Text, nullable=True)
    mime_type = Column(String(120), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    checksum = Column(String(128), nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tournament = relationship("CommunityTournament", back_populates="files", foreign_keys=[tournament_id])

    def to_dict(self):
        return {
            "id": str(self.id),
            "owner_user_id": int(self.owner_user_id) if self.owner_user_id else None,
            "tournament_id": str(self.tournament_id) if self.tournament_id else None,
            "purpose": self.purpose,
            "file_url": self.file_url,
            "storage_key": self.storage_key,
            "mime_type": self.mime_type,
            "file_size_bytes": int(self.file_size_bytes) if self.file_size_bytes is not None else None,
            "checksum": self.checksum,
            "metadata": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
