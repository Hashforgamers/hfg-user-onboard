from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
import os
import re
import uuid
from urllib.parse import urlparse

from flask import current_app
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError

from db.extensions import db
from models.communityTournament import (
    CommunityFileAsset,
    CommunityHostStatus,
    CommunityHostTier,
    CommunityHostVerification,
    CommunityTournament,
    CommunityTournamentRegistration,
    CommunityTournamentRegistrationStatus,
    CommunityTournamentStatus,
)
from models.communityTournamentOperations import (
    CommunityAuditLog,
    CommunityDisputeStatus,
    CommunityMatchResult,
    CommunityPayoutStatus,
    CommunityResultStatus,
    CommunityTournamentDispute,
    CommunityTournamentPayout,
    CommunityPaymentSettlementJob,
    CommunityPaymentSettlementStatus,
    CommunityPaymentAttempt,
    CommunityPaymentAttemptStatus,
    CommunityPaymentWebhookEvent,
    CommunityPaymentWebhookStatus,
)
from models.hashWalletTransaction import HashWalletTransaction
from models.hashWallet import HashWallet
from models.notification import Notification
from models.user import User
from services.community_dispute_chat_service import provision_dispute_chat_room


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UPI_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,256}@[A-Za-z]{2,64}$")
PUBLIC_STATUSES = {
    CommunityTournamentStatus.PUBLISHED,
    CommunityTournamentStatus.REGISTRATION_OPEN,
    CommunityTournamentStatus.REGISTRATION_CLOSED,
    CommunityTournamentStatus.LIVE,
    CommunityTournamentStatus.COMPLETED,
}
HOST_TIER_COMMISSION_RATES = {
    CommunityHostTier.BRONZE: Decimal("8.00"),
    CommunityHostTier.SILVER: Decimal("10.00"),
    CommunityHostTier.GOLD: Decimal("12.00"),
    CommunityHostTier.PLATINUM: Decimal("15.00"),
}
HOST_TIER_REQUIREMENTS = {
    CommunityHostTier.BRONZE: {
        "label": "Bronze Host",
        "organizer_commission_rate": 8.0,
        "requirements": ["Verified host account"],
    },
    CommunityHostTier.SILVER: {
        "label": "Silver Host",
        "organizer_commission_rate": 10.0,
        "requirements": ["High ratings", "Low dispute rates", "Successful tournament completion"],
    },
    CommunityHostTier.GOLD: {
        "label": "Gold Host",
        "organizer_commission_rate": 12.0,
        "requirements": ["High ratings", "Low dispute rates", "Successful tournament completion", "On-time payouts"],
    },
    CommunityHostTier.PLATINUM: {
        "label": "Platinum Host",
        "organizer_commission_rate": 15.0,
        "requirements": [
            "High ratings",
            "Low dispute rates",
            "Successful tournament completion",
            "On-time payouts",
            "No policy violations",
        ],
    },
}
TERMINAL_STATUSES = {
    CommunityTournamentStatus.COMPLETED,
    CommunityTournamentStatus.CANCELLED,
}
TOURNAMENT_FORMATS = {
    "single_elimination",
    "round_robin",
    "double_elimination",
    "group_knockout",
    "battle_royale",
    "league",
}
TEAM_MODES = {"solo", "duo", "squad", "team", "custom"}
PLATFORMS = {"mobile", "pc", "console", "cross_platform"}
REGISTRATION_POLICIES = {"automatic", "manual_approval", "payment", "identity_verification"}


class CommunityValidationError(ValueError):
    pass


class CommunityForbiddenError(PermissionError):
    pass


class CommunityConflictError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _parse_datetime(value, field_name):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommunityValidationError(f"{field_name} must be an ISO datetime") from exc
    else:
        raise CommunityValidationError(f"{field_name} is required")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _money(value, field_name, allow_zero=True):
    try:
        amount = Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise CommunityValidationError(f"{field_name} must be a valid amount") from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise CommunityValidationError(f"{field_name} must be positive")
    return amount


def _room_details_data(value):
    """Accept a game-neutral room/lobby payload without imposing game-specific keys."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CommunityValidationError("room_details_data must be an object")
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("room_details_data must contain JSON-compatible values") from exc
    if len(encoded) > 12000:
        raise CommunityValidationError("room_details_data must not exceed 12 KB")
    return value


def _json_object(value, field_name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CommunityValidationError(f"{field_name} must be an object")
    try:
        json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError(f"{field_name} must contain JSON-compatible values") from exc
    return value


def _bounded_int(value, field_name, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError(f"{field_name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise CommunityValidationError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _invite_code_hash(value):
    return hashlib.sha256(str(value).strip().encode("utf-8")).hexdigest()


def _validated_evidence_asset_ids(values, tournament_id, user_id, allowed_purposes):
    if not isinstance(values, list):
        raise CommunityValidationError("evidence_asset_ids must be a list")
    if not values:
        return []
    try:
        asset_ids = [uuid.UUID(str(value)) for value in values]
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("evidence_asset_ids must contain valid UUIDs") from exc
    if len(set(asset_ids)) != len(asset_ids):
        raise CommunityValidationError("evidence_asset_ids must be unique")
    assets = CommunityFileAsset.query.filter(CommunityFileAsset.id.in_(asset_ids)).all()
    valid_ids = {
        asset.id
        for asset in assets
        if asset.owner_user_id == int(user_id)
        and asset.tournament_id == tournament_id
        and asset.purpose in allowed_purposes
    }
    if valid_ids != set(asset_ids):
        raise CommunityForbiddenError("one or more evidence assets are invalid or not owned by the caller")
    return [str(asset_id) for asset_id in asset_ids]


def _banner_asset(value, user_id, tournament_id=None):
    if not value:
        return None
    try:
        asset_id = uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("banner_asset_id must be a valid UUID") from exc
    asset = CommunityFileAsset.query.filter_by(id=asset_id, owner_user_id=int(user_id), purpose="banner").first()
    if not asset:
        raise CommunityForbiddenError("banner asset is invalid or not owned by the host")
    if asset.tournament_id and tournament_id and asset.tournament_id != tournament_id:
        raise CommunityConflictError("banner asset belongs to another tournament")
    if asset.tournament_id and not tournament_id:
        raise CommunityConflictError("banner asset is already attached to a tournament")
    return asset


def _host_commission_rate(host_tier):
    return HOST_TIER_COMMISSION_RATES.get(str(host_tier or CommunityHostTier.BRONZE).lower(), HOST_TIER_COMMISSION_RATES[CommunityHostTier.BRONZE])


def _percent_metric(value, field_name):
    try:
        metric = Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise CommunityValidationError(f"{field_name} must be a valid percentage") from exc
    if metric < 0 or metric > 100:
        raise CommunityValidationError(f"{field_name} must be between 0 and 100")
    return metric


def _rating_metric(value, field_name):
    try:
        metric = Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise CommunityValidationError(f"{field_name} must be a valid rating") from exc
    if metric < 0 or metric > 5:
        raise CommunityValidationError(f"{field_name} must be between 0 and 5")
    return metric


def host_program_config():
    monthly_fee = Decimal(str(current_app.config.get("COMMUNITY_HOST_VERIFICATION_MONTHLY_FEE", 199))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    included_per_week = int(current_app.config.get("COMMUNITY_HOST_INCLUDED_TOURNAMENTS_PER_WEEK", 3) or 3)
    return {
        "platform_fee_rate": float(Decimal(str(current_app.config.get("COMMUNITY_PLATFORM_FEE_RATE", 10)))),
        "verification_fee": {
            "amount": float(monthly_fee),
            "currency": "INR",
            "billing_period": "monthly",
            "included_tournaments_per_week": included_per_week,
        },
        "performance_levels": HOST_TIER_REQUIREMENTS,
    }


def _audit(action, entity_type, entity_id, actor_user_id=None, actor_type="user", metadata=None):
    db.session.add(
        CommunityAuditLog(
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            meta=metadata or {},
        )
    )


def _notify(user_id, notification_type, title, message, reference_id=None):
    if user_id:
        db.session.add(
            Notification(
                user_id=int(user_id),
                type=notification_type,
                reference_id=str(reference_id) if reference_id else None,
                title=title,
                message=message,
                is_read=False,
            )
        )


def _apply_wallet_transaction(user_id, amount, transaction_type, reference_id):
    """Keep the wallet balance and its immutable transaction ledger in sync."""
    wallet = HashWallet.query.filter_by(user_id=int(user_id)).with_for_update().first()
    if not wallet:
        wallet = HashWallet(user_id=int(user_id), balance=0)
        db.session.add(wallet)
        db.session.flush()
    wallet_amount = int(amount)
    wallet.balance += wallet_amount
    db.session.add(
        HashWalletTransaction(
            user_id=int(user_id),
            amount=wallet_amount,
            type=transaction_type,
            reference_id=str(reference_id),
        )
    )


def _derive_status(tournament, now=None):
    if tournament.status in {CommunityTournamentStatus.DRAFT, *TERMINAL_STATUSES}:
        return tournament.status
    current = now or _now()
    if current < tournament.registration_start_at:
        return CommunityTournamentStatus.PUBLISHED
    if tournament.registration_start_at <= current <= tournament.registration_end_at:
        if int(tournament.registered_players_count or 0) >= int(tournament.max_players or 0):
            return CommunityTournamentStatus.REGISTRATION_CLOSED
        return CommunityTournamentStatus.REGISTRATION_OPEN
    if current < tournament.tournament_start_at:
        return CommunityTournamentStatus.REGISTRATION_CLOSED
    # Reaching the scheduled end must not bypass unfinished matches, disputes,
    # or payout/result checks. Completion is an explicit finalization action.
    return CommunityTournamentStatus.LIVE


def sync_tournament_status(tournament, now=None):
    next_status = _derive_status(tournament, now)
    changed = tournament.status != next_status
    if changed:
        tournament.status = next_status
    return changed


def _recalculate_prize_pool(tournament):
    total = Decimal(str(tournament.entry_fee or 0)) * Decimal(int(tournament.registered_players_count or 0))
    commission_rate = Decimal(str(tournament.organizer_commission_rate or _host_commission_rate(tournament.host_tier)))
    platform_fee_rate = Decimal(str(getattr(tournament, "platform_fee_rate", 0) or 0))
    if commission_rate + platform_fee_rate > Decimal("100"):
        raise CommunityValidationError("platform and organizer fee rates cannot exceed 100 percent")
    commission = (total * commission_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    platform_fee = (total * platform_fee_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tournament.total_collection = total
    tournament.organizer_commission_rate = commission_rate
    tournament.organizer_commission_amount = commission
    tournament.platform_fee_rate = platform_fee_rate
    tournament.platform_fee_amount = platform_fee
    tournament.prize_pool = total - commission - platform_fee


def _host_verification(user_id):
    return CommunityHostVerification.query.filter_by(user_id=int(user_id)).first()


def _require_host_for_paid_tournament(user_id, entry_fee):
    verification = _host_verification(user_id)
    if entry_fee > 0 and (not verification or verification.verification_status != CommunityHostStatus.VERIFIED):
        raise CommunityForbiddenError("Only verified hosts can create paid community tournaments")
    if verification and verification.verification_status == CommunityHostStatus.SUSPENDED:
        raise CommunityForbiddenError("Host account is suspended")
    return verification


def submit_host_verification(user_id, payload):
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    phone = str(payload.get("phone") or "").strip()
    upi_id = str(payload.get("upi_id") or payload.get("upiId") or "").strip()
    address = str(payload.get("address") or "").strip()
    government_id_reference = str(payload.get("government_id") or payload.get("governmentId") or "").strip() or None
    government_id_asset_id = payload.get("government_id_asset_id") or payload.get("governmentIdAssetId")

    if not name or len(name) > 160:
        raise CommunityValidationError("name is required and must be under 160 characters")
    if not EMAIL_RE.match(email):
        raise CommunityValidationError("email is invalid")
    if len(phone) < 8 or len(phone) > 32:
        raise CommunityValidationError("phone is invalid")
    if not UPI_RE.match(upi_id):
        raise CommunityValidationError("upi_id is invalid")
    if len(address) < 10:
        raise CommunityValidationError("address is required")
    government_asset = None
    if government_id_asset_id:
        try:
            parsed_asset_id = uuid.UUID(str(government_id_asset_id))
        except (TypeError, ValueError) as exc:
            raise CommunityValidationError("government_id_asset_id must be a valid UUID") from exc
        government_asset = CommunityFileAsset.query.filter_by(
            id=parsed_asset_id,
            owner_user_id=int(user_id),
            purpose="government_id",
            tournament_id=None,
        ).first()
        if not government_asset:
            raise CommunityForbiddenError("government ID asset is invalid or not owned by the caller")

    verification = _host_verification(user_id)
    if not verification:
        verification = CommunityHostVerification(user_id=int(user_id))
        db.session.add(verification)
    elif verification.verification_status == CommunityHostStatus.SUSPENDED:
        raise CommunityForbiddenError("Host verification is suspended")

    verification.name = name
    verification.email = email
    verification.phone = phone
    verification.upi_id = upi_id
    verification.address = address
    verification.government_id_reference = government_id_reference
    verification.government_id_asset_id = government_asset.id if government_asset else None
    verification.verification_status = CommunityHostStatus.PENDING
    verification.rejection_reason = None
    db.session.flush()
    _audit("host_verification_submitted", "community_host_verification", verification.id, user_id)
    db.session.commit()
    return verification


def review_host_verification(verification_id, payload, admin_id=None):
    status = str(payload.get("verification_status") or payload.get("status") or "").strip().lower()
    if status not in {
        CommunityHostStatus.VERIFIED,
        CommunityHostStatus.REJECTED,
        CommunityHostStatus.SUSPENDED,
        CommunityHostStatus.PENDING,
    }:
        raise CommunityValidationError("status must be pending, verified, rejected, or suspended")
    verification = CommunityHostVerification.query.filter_by(id=verification_id).first()
    if not verification:
        raise CommunityValidationError("verification request not found")
    verification.verification_status = status
    if "host_tier" in payload or "tier" in payload:
        host_tier = str(payload.get("host_tier") or payload.get("tier") or "").strip().lower()
        if host_tier not in HOST_TIER_COMMISSION_RATES:
            raise CommunityValidationError("host_tier must be bronze, silver, gold, or platinum")
        verification.host_tier = host_tier
    for field in ("average_rating", "dispute_rate", "completion_rate", "on_time_payout_rate"):
        if field in payload:
            setattr(
                verification,
                field,
                _rating_metric(payload[field], field) if field == "average_rating" else _percent_metric(payload[field], field),
            )
    if "policy_violation_count" in payload:
        try:
            policy_violation_count = int(payload.get("policy_violation_count") or 0)
        except (TypeError, ValueError) as exc:
            raise CommunityValidationError("policy_violation_count must be a non-negative integer") from exc
        if policy_violation_count < 0:
            raise CommunityValidationError("policy_violation_count cannot be negative")
        verification.policy_violation_count = policy_violation_count
    verification.rejection_reason = str(payload.get("rejection_reason") or "").strip() or None
    verification.reviewed_by_admin_id = int(admin_id) if admin_id else None
    verification.reviewed_at = _now()
    _audit("host_verification_reviewed", "community_host_verification", verification.id, admin_id, "admin", {"status": status})
    _notify(
        verification.user_id,
        "community_host_approval",
        "Host verification updated",
        f"Your host verification status is now {status}.",
        verification.id,
    )
    db.session.commit()
    return verification


def create_tournament(host_user_id, payload):
    entry_fee = _money(payload.get("entry_fee", 0), "entry_fee")
    verification = _require_host_for_paid_tournament(host_user_id, entry_fee)
    host_tier = verification.host_tier if verification else CommunityHostTier.BRONZE
    organizer_commission_rate = _host_commission_rate(host_tier)
    platform_fee_rate = Decimal(str(current_app.config.get("COMMUNITY_PLATFORM_FEE_RATE", 10))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    if platform_fee_rate < 0 or platform_fee_rate + organizer_commission_rate > 100:
        raise CommunityValidationError("configured platform and organizer fee rates are invalid")

    title = str(payload.get("title") or "").strip()
    game = str(payload.get("game") or "").strip()
    max_players = int(payload.get("max_players") or 0)
    if len(title) < 3 or len(title) > 200:
        raise CommunityValidationError("title must be 3-200 characters")
    if not game:
        raise CommunityValidationError("game is required")
    if max_players <= 0 or max_players > 10000:
        raise CommunityValidationError("max_players must be between 1 and 10000")
    tournament_type = str(payload.get("tournament_type") or "single_elimination").strip().lower()
    team_mode = str(payload.get("team_mode") or "solo").strip().lower()
    platform = str(payload.get("platform") or "cross_platform").strip().lower()
    registration_policy = str(payload.get("registration_policy") or ("payment" if entry_fee > 0 else "automatic")).strip().lower()
    if tournament_type not in TOURNAMENT_FORMATS:
        raise CommunityValidationError("unsupported tournament_type")
    if team_mode not in TEAM_MODES:
        raise CommunityValidationError("unsupported team_mode")
    if platform not in PLATFORMS:
        raise CommunityValidationError("unsupported platform")
    if registration_policy not in REGISTRATION_POLICIES:
        raise CommunityValidationError("unsupported registration_policy")
    team_size = _bounded_int(payload.get("team_size", 1 if team_mode == "solo" else 2), "team_size", 1, 100)
    substitute_limit = _bounded_int(payload.get("substitute_limit", 0), "substitute_limit", 0, 20)
    min_entries = _bounded_int(payload.get("min_entries", min(2, max_players)), "min_entries", 1, max_players)
    minimum_age = payload.get("minimum_age")
    minimum_age = _bounded_int(minimum_age, "minimum_age", 13, 100) if minimum_age is not None else None
    banner_asset = _banner_asset(payload.get("banner_asset_id"), host_user_id)

    registration_start_at = _parse_datetime(payload.get("registration_start_at"), "registration_start_at")
    registration_end_at = _parse_datetime(payload.get("registration_end_at"), "registration_end_at")
    tournament_start_at = _parse_datetime(payload.get("tournament_start_at") or payload.get("tournament_date"), "tournament_start_at")
    tournament_end_at = payload.get("tournament_end_at")
    tournament_end_at = _parse_datetime(tournament_end_at, "tournament_end_at") if tournament_end_at else None

    if registration_end_at <= registration_start_at:
        raise CommunityValidationError("registration_end_at must be after registration_start_at")
    if tournament_start_at < registration_end_at:
        raise CommunityValidationError("tournament_start_at must be after registration_end_at")
    if tournament_end_at and tournament_end_at <= tournament_start_at:
        raise CommunityValidationError("tournament_end_at must be after tournament_start_at")

    tournament = CommunityTournament(
        host_user_id=int(host_user_id),
        title=title,
        description=str(payload.get("description") or "").strip() or None,
        banner_url=str(payload.get("banner_url") or "").strip() or None,
        banner_asset_id=banner_asset.id if banner_asset else None,
        game=game,
        game_mode=str(payload.get("game_mode") or "").strip() or None,
        platform=platform,
        organization_name=str(payload.get("organization_name") or "").strip() or None,
        tournament_type=tournament_type,
        team_mode=team_mode,
        team_size=team_size,
        substitute_limit=substitute_limit,
        minimum_age=minimum_age,
        region=str(payload.get("region") or "").strip() or None,
        registration_policy=registration_policy,
        is_private=payload.get("is_private", False),
        invite_code_hash=_invite_code_hash(payload["invite_code"]) if payload.get("invite_code") else None,
        min_entries=min_entries,
        entry_fee=entry_fee,
        host_tier=host_tier,
        organizer_commission_rate=organizer_commission_rate,
        platform_fee_rate=platform_fee_rate,
        currency=str(payload.get("currency") or "INR").strip().upper(),
        max_players=max_players,
        registration_start_at=registration_start_at,
        registration_end_at=registration_end_at,
        tournament_start_at=tournament_start_at,
        tournament_end_at=tournament_end_at,
        roster_lock_at=_parse_datetime(payload["roster_lock_at"], "roster_lock_at") if payload.get("roster_lock_at") else None,
        check_in_start_at=_parse_datetime(payload["check_in_start_at"], "check_in_start_at") if payload.get("check_in_start_at") else None,
        check_in_end_at=_parse_datetime(payload["check_in_end_at"], "check_in_end_at") if payload.get("check_in_end_at") else None,
        match_duration_minutes=_bounded_int(payload.get("match_duration_minutes", 45), "match_duration_minutes", 5, 480),
        break_duration_minutes=_bounded_int(payload.get("break_duration_minutes", 15), "break_duration_minutes", 0, 240),
        max_matches_per_team_per_day=_bounded_int(payload.get("max_matches_per_team_per_day", 6), "max_matches_per_team_per_day", 1, 32),
        result_submission_window_minutes=_bounded_int(payload.get("result_submission_window_minutes", 15), "result_submission_window_minutes", 1, 1440),
        dispute_window_minutes=_bounded_int(payload.get("dispute_window_minutes", 30), "dispute_window_minutes", 1, 10080),
        schedule_config=_json_object(payload.get("schedule_config"), "schedule_config"),
        rules_config=_json_object(payload.get("rules_config"), "rules_config"),
        rules=str(payload.get("rules") or "").strip() or None,
        prize_distribution=payload.get("prize_distribution") or [],
        discord_link=str(payload.get("discord_link") or "").strip() or None,
        whatsapp_link=str(payload.get("whatsapp_link") or "").strip() or None,
        room_details=str(payload.get("room_details") or "").strip() or None,
        room_details_data=_room_details_data(payload.get("room_details_data")),
        visibility=bool(payload.get("visibility", True)),
        status=str(payload.get("status") or CommunityTournamentStatus.DRAFT).strip().lower(),
    )
    if tournament.status not in {CommunityTournamentStatus.DRAFT, CommunityTournamentStatus.PUBLISHED}:
        raise CommunityValidationError("new tournament status must be draft or published")
    if not isinstance(tournament.is_private, bool):
        raise CommunityValidationError("is_private must be a boolean")
    if tournament.is_private and not tournament.invite_code_hash:
        raise CommunityValidationError("private tournaments require an invite_code")
    if tournament.room_details or tournament.room_details_data:
        tournament.room_details_published_at = _now()
    if tournament.check_in_start_at and tournament.check_in_end_at and tournament.check_in_end_at <= tournament.check_in_start_at:
        raise CommunityValidationError("check_in_end_at must be after check_in_start_at")
    if tournament.roster_lock_at and tournament.roster_lock_at > tournament.tournament_start_at:
        raise CommunityValidationError("roster_lock_at cannot be after tournament_start_at")
    sync_tournament_status(tournament)
    _recalculate_prize_pool(tournament)
    db.session.add(tournament)
    db.session.flush()
    if banner_asset:
        banner_asset.tournament_id = tournament.id
    _audit("tournament_created", "community_tournament", tournament.id, host_user_id)
    db.session.commit()
    return tournament


def update_tournament(host_user_id, tournament_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id)).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    if tournament.status in TERMINAL_STATUSES:
        raise CommunityConflictError("terminal tournaments cannot be edited")
    from models.communityTournamentOperations import CommunityTournamentMatch, CommunityTournamentTeam

    active_registration_query = CommunityTournamentRegistration.query.filter(
        CommunityTournamentRegistration.tournament_id == tournament.id,
        CommunityTournamentRegistration.status.notin_({
            CommunityTournamentRegistrationStatus.CANCELLED,
            CommunityTournamentRegistrationStatus.REFUNDED,
        }),
    )
    active_registration_count = active_registration_query.count()
    if active_registration_count and any(field in payload for field in {"entry_fee", "currency"}):
        raise CommunityConflictError("entry_fee and currency cannot change after registration starts")
    if tournament.registered_players_count > 0 and "prize_distribution" in payload:
        raise CommunityConflictError("prize_distribution cannot change after confirmed registrations")
    if any(field in payload for field in {"team_mode", "team_size", "substitute_limit"}) and CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id).first():
        raise CommunityConflictError("team configuration cannot change after a team is created")
    if "tournament_type" in payload and CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).first():
        raise CommunityConflictError("tournament_type cannot change after matches are generated")

    editable = {
        "title", "description", "banner_url", "game", "tournament_type", "team_mode",
        "rules", "prize_distribution", "discord_link", "whatsapp_link", "room_details", "room_details_data",
        "game_mode", "organization_name", "region", "schedule_config", "rules_config",
    }
    for field in editable:
        if field in payload:
            value = payload[field]
            if field == "room_details_data":
                setattr(tournament, field, _room_details_data(value))
                continue
            if field in {"schedule_config", "rules_config"}:
                setattr(tournament, field, _json_object(value, field))
                continue
            if field in {"title", "game"}:
                value = str(value or "").strip()
                if (field == "title" and not 3 <= len(value) <= 200) or (field == "game" and not value):
                    raise CommunityValidationError(f"{field} is invalid")
            elif field in {"description", "banner_url", "tournament_type", "team_mode", "rules", "discord_link", "whatsapp_link", "room_details"}:
                value = str(value or "").strip() or None
            setattr(tournament, field, value)

    if "banner_asset_id" in payload:
        banner_asset = _banner_asset(payload["banner_asset_id"], host_user_id, tournament.id)
        tournament.banner_asset_id = banner_asset.id if banner_asset else None
        if banner_asset:
            banner_asset.tournament_id = tournament.id
    if "visibility" in payload:
        if not isinstance(payload["visibility"], bool):
            raise CommunityValidationError("visibility must be a boolean")
        tournament.visibility = payload["visibility"]
    for field, valid in (
        ("platform", PLATFORMS),
        ("tournament_type", TOURNAMENT_FORMATS),
        ("team_mode", TEAM_MODES),
        ("registration_policy", REGISTRATION_POLICIES),
    ):
        if field in payload:
            value = str(payload[field] or "").strip().lower()
            if value not in valid:
                raise CommunityValidationError(f"unsupported {field}")
            setattr(tournament, field, value)
    if "is_private" in payload:
        if not isinstance(payload["is_private"], bool):
            raise CommunityValidationError("is_private must be a boolean")
        tournament.is_private = payload["is_private"]
    if "invite_code" in payload:
        tournament.invite_code_hash = _invite_code_hash(payload["invite_code"]) if payload["invite_code"] else None
    for field, minimum, maximum in (
        ("team_size", 1, 100),
        ("substitute_limit", 0, 20),
        ("min_entries", 1, 10000),
        ("minimum_age", 13, 100),
        ("match_duration_minutes", 5, 480),
        ("break_duration_minutes", 0, 240),
        ("max_matches_per_team_per_day", 1, 32),
        ("result_submission_window_minutes", 1, 1440),
        ("dispute_window_minutes", 1, 10080),
    ):
        if field in payload:
            setattr(tournament, field, _bounded_int(payload[field], field, minimum, maximum) if payload[field] is not None else None)
    if "max_players" in payload:
        try:
            max_players = int(payload["max_players"])
        except (TypeError, ValueError) as exc:
            raise CommunityValidationError("max_players must be an integer") from exc
        if max_players <= 0 or max_players > 10000:
            raise CommunityValidationError("max_players must be between 1 and 10000")
        tournament.max_players = max_players
    if "currency" in payload:
        currency = str(payload["currency"] or "").strip().upper()
        if not 3 <= len(currency) <= 8:
            raise CommunityValidationError("currency must be 3-8 characters")
        tournament.currency = currency
    if "status" in payload:
        status = str(payload["status"] or "").strip().lower()
        if status not in {CommunityTournamentStatus.DRAFT, CommunityTournamentStatus.PUBLISHED}:
            raise CommunityValidationError("status can only be draft or published; use the cancel endpoint to cancel")
        tournament.status = status
    for field in ("registration_start_at", "registration_end_at", "tournament_start_at"):
        if field in payload:
            setattr(tournament, field, _parse_datetime(payload[field], field))
    for field in ("roster_lock_at", "check_in_start_at", "check_in_end_at"):
        if field in payload:
            setattr(tournament, field, _parse_datetime(payload[field], field) if payload[field] else None)
    if "tournament_end_at" in payload:
        tournament.tournament_end_at = _parse_datetime(payload["tournament_end_at"], "tournament_end_at") if payload["tournament_end_at"] else None
    if "entry_fee" in payload:
        new_fee = _money(payload["entry_fee"], "entry_fee")
        _require_host_for_paid_tournament(host_user_id, new_fee)
        tournament.entry_fee = new_fee

    if tournament.max_players < active_registration_count:
        raise CommunityValidationError("max_players cannot be lower than active registrations")
    if tournament.registration_end_at <= tournament.registration_start_at:
        raise CommunityValidationError("registration_end_at must be after registration_start_at")
    if tournament.tournament_start_at < tournament.registration_end_at:
        raise CommunityValidationError("tournament_start_at must be after registration_end_at")
    if tournament.tournament_end_at and tournament.tournament_end_at <= tournament.tournament_start_at:
        raise CommunityValidationError("tournament_end_at must be after tournament_start_at")
    if tournament.min_entries > tournament.max_players:
        raise CommunityValidationError("min_entries cannot exceed max_players")
    if tournament.check_in_start_at and tournament.check_in_end_at and tournament.check_in_end_at <= tournament.check_in_start_at:
        raise CommunityValidationError("check_in_end_at must be after check_in_start_at")
    if tournament.roster_lock_at and tournament.roster_lock_at > tournament.tournament_start_at:
        raise CommunityValidationError("roster_lock_at cannot be after tournament_start_at")
    if tournament.is_private and not tournament.invite_code_hash:
        raise CommunityValidationError("private tournaments require an invite_code")
    if (tournament.room_details or tournament.room_details_data) and not tournament.room_details_published_at:
        tournament.room_details_published_at = _now()
    sync_tournament_status(tournament)
    _recalculate_prize_pool(tournament)
    _audit("tournament_updated", "community_tournament", tournament.id, host_user_id)
    db.session.commit()
    return tournament


def close_registration(host_user_id, tournament_id):
    """Close an active registration window early without moving the start time."""
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    now = _now()
    sync_tournament_status(tournament, now)

    if tournament.status == CommunityTournamentStatus.REGISTRATION_CLOSED:
        return tournament
    if tournament.status != CommunityTournamentStatus.REGISTRATION_OPEN:
        raise CommunityConflictError("registration can be closed only while it is open")
    if now >= tournament.tournament_start_at:
        raise CommunityConflictError("registration cannot be closed after the tournament starts")

    # Make the close durable across future time-based status synchronizations.
    tournament.registration_end_at = now - timedelta(microseconds=1)
    tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
    _audit("registration_closed_early", "community_tournament", tournament.id, host_user_id)
    _notify(
        tournament.host_user_id,
        "community_registration_closed",
        "Registration closed",
        f"Registration for {tournament.title} has been closed by the organizer.",
        tournament.id,
    )
    db.session.commit()
    return tournament


def cancel_tournament(host_user_id, tournament_id, reason=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id)).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    if tournament.status == CommunityTournamentStatus.COMPLETED:
        raise CommunityConflictError("completed tournaments cannot be cancelled")
    registrations = (
        CommunityTournamentRegistration.query
        .filter(
            CommunityTournamentRegistration.tournament_id == tournament.id,
            CommunityTournamentRegistration.status.in_({
                CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
                CommunityTournamentRegistrationStatus.CONFIRMED,
                CommunityTournamentRegistrationStatus.REFUND_PENDING,
            }),
        )
        .with_for_update()
        .all()
    )
    for reg in registrations:
        try:
            _refund_or_cancel_registration(reg, tournament)
        except Exception:
            db.session.rollback()
            raise
        _notify(reg.user_id, "community_tournament_cancelled", "Tournament cancelled", f"{tournament.title} was cancelled. Refund processing has started.", tournament.id)
    tournament.status = CommunityTournamentStatus.CANCELLED
    _audit("tournament_cancelled", "community_tournament", tournament.id, host_user_id, metadata={"reason": reason})
    db.session.commit()
    return tournament


def list_tournaments(filters):
    page = max(int(filters.get("page") or 1), 1)
    per_page = min(max(int(filters.get("per_page") or filters.get("limit") or 20), 1), 100)
    view = str(filters.get("view") or "").strip().lower()
    search = str(filters.get("search") or "").strip()
    sort = str(filters.get("sort") or "soonest").strip().lower()

    query = CommunityTournament.query.filter(
        CommunityTournament.visibility.is_(True),
        CommunityTournament.is_private.is_(False),
        CommunityTournament.status.in_(PUBLIC_STATUSES),
    )
    if filters.get("game"):
        query = query.filter(func.lower(CommunityTournament.game) == str(filters["game"]).lower())
    if search:
        like = f"%{search}%"
        query = query.filter(or_(CommunityTournament.title.ilike(like), CommunityTournament.description.ilike(like), CommunityTournament.game.ilike(like)))
    if view == "featured":
        query = query.filter(CommunityTournament.is_featured.is_(True))
    elif view == "free":
        query = query.filter(CommunityTournament.entry_fee == 0)
    elif view == "paid":
        query = query.filter(CommunityTournament.entry_fee > 0)
    elif view == "upcoming":
        query = query.filter(CommunityTournament.tournament_start_at >= _now())
    elif view == "popular":
        query = query.order_by(CommunityTournament.registered_players_count.desc())

    if sort == "popular":
        query = query.order_by(CommunityTournament.registered_players_count.desc(), CommunityTournament.tournament_start_at.asc())
    elif sort == "newest":
        query = query.order_by(CommunityTournament.created_at.desc())
    elif sort == "fee_low":
        query = query.order_by(CommunityTournament.entry_fee.asc())
    elif view != "popular":
        query = query.order_by(CommunityTournament.tournament_start_at.asc())

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    changed = False
    now = _now()
    for item in items:
        changed = sync_tournament_status(item, now) or changed
    if changed:
        db.session.commit()
    return {
        "items": [item.to_dict() for item in items],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def get_tournament(tournament_id, requester_user_id=None, invite_code=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    active_registration = (
        CommunityTournamentRegistration.query.filter(
            CommunityTournamentRegistration.tournament_id == tournament.id,
            CommunityTournamentRegistration.user_id == int(requester_user_id),
            CommunityTournamentRegistration.status.notin_({
                CommunityTournamentRegistrationStatus.CANCELLED,
                CommunityTournamentRegistrationStatus.REFUNDED,
            }),
        ).first()
        if requester_user_id else None
    )
    is_host = bool(requester_user_id and int(requester_user_id) == int(tournament.host_user_id))
    if tournament.is_private and not is_host and not active_registration:
        supplied_hash = _invite_code_hash(invite_code or "")
        if not tournament.invite_code_hash or not hmac.compare_digest(tournament.invite_code_hash, supplied_hash):
            raise CommunityForbiddenError("a valid tournament invite code is required")
    if sync_tournament_status(tournament):
        db.session.commit()
    include_room = bool(is_host or (active_registration and active_registration.status == CommunityTournamentRegistrationStatus.CONFIRMED))
    return tournament.to_dict(include_room_details=include_room)


def _queue_payment_settlement(registration, payment_id=None, order_id=None, payload=None):
    """Create or refresh one retry job without confirming the registration."""
    job = CommunityPaymentSettlementJob.query.filter_by(registration_id=registration.id).with_for_update().first()
    if not job:
        job = CommunityPaymentSettlementJob(
            registration_id=registration.id,
            tournament_id=registration.tournament_id,
            provider="razorpay",
            status=CommunityPaymentSettlementStatus.PENDING,
        )
        db.session.add(job)
    payment_id = str(payment_id or "").strip() or None
    order_id = str(order_id or "").strip() or None
    if payment_id:
        job.payment_id = payment_id
    if order_id:
        job.order_id = order_id
    if payload:
        job.payload = {
            **(job.payload or {}),
            **{
                key: float(value) if isinstance(value, Decimal) else value
                for key, value in payload.items()
            },
        }
    if job.status != CommunityPaymentSettlementStatus.SETTLED:
        job.status = CommunityPaymentSettlementStatus.PENDING
        job.next_attempt_at = _now()
        job.last_error = None
    return job


def _payment_attempt_receipt(registration_id, attempt_id=None):
    """Keep the Razorpay receipt unique, stable, and within its 40-character limit."""
    suffix = str(attempt_id or uuid.uuid4()).replace("-", "")[:6]
    return f"ctr_{str(registration_id).replace('-', '')[:29]}_{suffix}"


def _payment_checkout_payload(attempt):
    from services.payment_service import create_payment_intent

    return create_payment_intent(
        amount=float(attempt.amount),
        currency=attempt.currency,
        metadata={
            "registration_id": str(attempt.registration_id),
            "tournament_id": str(attempt.tournament_id),
            "payment_attempt_id": str(attempt.id),
            "receipt": attempt.receipt,
            "source": "community_tournament",
        },
    )


def create_community_payment_attempt(registration_id):
    """Create or reuse the one active Razorpay checkout for a registration.

    The public compatibility endpoint delegates here, so amount, currency and
    ownership metadata are always read from the locked registration server-side.
    """
    registration = CommunityTournamentRegistration.query.filter_by(id=registration_id).with_for_update().first()
    if not registration:
        raise CommunityValidationError("community registration not found")
    if registration.status != CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
        raise CommunityConflictError("payment is not required for this registration")
    tournament = CommunityTournament.query.filter_by(id=registration.tournament_id).first()
    if not tournament or Decimal(tournament.entry_fee or 0) <= 0:
        raise CommunityConflictError("payment is not required for this registration")

    attempt = (
        CommunityPaymentAttempt.query
        .filter(
            CommunityPaymentAttempt.registration_id == registration.id,
            CommunityPaymentAttempt.status.in_({
                CommunityPaymentAttemptStatus.CREATED,
                CommunityPaymentAttemptStatus.PENDING,
            }),
        )
        .order_by(CommunityPaymentAttempt.created_at.desc())
        .with_for_update()
        .first()
    )
    if attempt and attempt.provider_order_id:
        return {
            "provider": attempt.provider,
            "order_id": attempt.provider_order_id,
            "amount": float(attempt.amount),
            "currency": attempt.currency,
            "key": os.getenv("RAZORPAY_KEY_ID"),
            "status": "requires_payment_method",
        }

    if not attempt:
        attempt = CommunityPaymentAttempt(
            registration_id=registration.id,
            tournament_id=tournament.id,
            user_id=registration.user_id,
            provider="razorpay",
            receipt=_payment_attempt_receipt(registration.id),
            amount=tournament.entry_fee,
            currency=str(tournament.currency or "INR").upper(),
            status=CommunityPaymentAttemptStatus.CREATED,
            expires_at=_now() + timedelta(minutes=int(current_app.config.get("COMMUNITY_PAYMENT_ATTEMPT_TTL_MINUTES", 30))),
        )
        db.session.add(attempt)
        db.session.flush()

    try:
        checkout = _payment_checkout_payload(attempt)
    except Exception:
        attempt.status = CommunityPaymentAttemptStatus.FAILED
        db.session.commit()
        raise
    if checkout.get("provider") != "razorpay" or not checkout.get("order_id"):
        attempt.status = CommunityPaymentAttemptStatus.FAILED
        db.session.commit()
        raise CommunityConflictError("Razorpay checkout is not configured")
    attempt.provider_order_id = str(checkout["order_id"])
    attempt.status = CommunityPaymentAttemptStatus.PENDING
    registration.razorpay_order_id = attempt.provider_order_id
    _queue_payment_settlement(registration, order_id=attempt.provider_order_id)
    db.session.commit()
    return checkout


def _bind_verified_payment_attempt(registration, payment_details):
    """Attach a provider-verified payment to its registration exactly once."""
    payment_id = str(payment_details.get("payment_id") or "").strip()
    order_id = str(payment_details.get("order_id") or "").strip()
    if not payment_id or not order_id:
        raise CommunityValidationError("verified payment is missing its provider IDs")
    attempt = CommunityPaymentAttempt.query.filter(
        or_(
            CommunityPaymentAttempt.provider_payment_id == payment_id,
            CommunityPaymentAttempt.provider_order_id == order_id,
        )
    ).with_for_update().first()
    if attempt and attempt.registration_id != registration.id:
        raise CommunityConflictError("payment attempt belongs to another registration")
    if not attempt:
        # Compatibility for orders created before payment attempts existed. The
        # provider fetch has already verified notes/receipt against this ID.
        attempt = CommunityPaymentAttempt(
            registration_id=registration.id,
            tournament_id=registration.tournament_id,
            user_id=registration.user_id,
            provider=str(payment_details.get("provider") or "razorpay"),
            receipt=str(payment_details.get("receipt") or _payment_attempt_receipt(registration.id)),
            amount=payment_details.get("amount"),
            currency=str(payment_details.get("currency") or "INR").upper(),
            provider_order_id=order_id,
            status=CommunityPaymentAttemptStatus.CAPTURED,
        )
        db.session.add(attempt)
    elif attempt.provider_order_id and attempt.provider_order_id != order_id:
        raise CommunityConflictError("payment attempt order does not match provider payment")
    attempt.provider_order_id = order_id
    attempt.provider_payment_id = payment_id
    attempt.status = CommunityPaymentAttemptStatus.CAPTURED
    return attempt


def _queue_captured_payment_refund(registration, tournament, reason):
    """Never leave a captured payment stranded when a slot is no longer usable."""
    registration.amount_paid = tournament.entry_fee
    registration.payment_verified_at = registration.payment_verified_at or _now()
    registration.paid_at = registration.paid_at or _now()
    registration.status = CommunityTournamentRegistrationStatus.REFUND_PENDING
    registration.payment_status = "refund_pending"
    registration.refund_status = "pending"
    registration.refund_amount = tournament.entry_fee
    registration.refund_requested_at = registration.refund_requested_at or _now()
    registration.refund_error = reason
    job = _queue_payment_settlement(registration, registration.razorpay_payment_id, registration.razorpay_order_id)
    job.status = CommunityPaymentSettlementStatus.SETTLED
    job.settled_at = job.settled_at or _now()
    job.next_attempt_at = None
    _audit(
        "registration_payment_refund_required",
        "community_tournament_registration",
        registration.id,
        registration.user_id,
        metadata={"reason": reason},
    )
    db.session.commit()
    return registration


def enqueue_community_payment_webhook(event_id, event_type, payment_details, payload):
    """Persist an already-authenticated provider event before acknowledging it."""
    event_id = str(event_id or "").strip()
    if not event_id:
        raise CommunityValidationError("payment webhook event ID is required")
    existing = CommunityPaymentWebhookEvent.query.filter_by(provider_event_id=event_id).first()
    if existing:
        return existing, False
    registration_id = payment_details.get("registration_id")
    try:
        registration_id = uuid.UUID(str(registration_id)) if registration_id else None
    except (TypeError, ValueError):
        registration_id = None
    event = CommunityPaymentWebhookEvent(
        provider=str(payment_details.get("provider") or "razorpay"),
        provider_event_id=event_id,
        event_type=str(event_type or "unknown"),
        registration_id=registration_id,
        payment_id=payment_details.get("payment_id"),
        order_id=payment_details.get("order_id"),
        payload=payload if isinstance(payload, dict) else {},
        status=CommunityPaymentWebhookStatus.PENDING,
        next_attempt_at=_now(),
    )
    try:
        db.session.add(event)
        db.session.commit()
        return event, True
    except IntegrityError:
        db.session.rollback()
        return CommunityPaymentWebhookEvent.query.filter_by(provider_event_id=event_id).first(), False


def _retry_webhook_event(event, error):
    event.attempts = int(event.attempts or 0) + 1
    max_attempts = int(current_app.config.get("COMMUNITY_PAYMENT_RECONCILIATION_MAX_ATTEMPTS", 12))
    event.last_error = str(error)[:500]
    if event.attempts >= max_attempts:
        event.status = CommunityPaymentWebhookStatus.FAILED
        event.next_attempt_at = None
    else:
        event.status = CommunityPaymentWebhookStatus.RETRY
        event.next_attempt_at = _now() + timedelta(minutes=min(60, 2 ** min(event.attempts, 6)))


def process_pending_community_payment_webhooks(limit=50):
    """Reconcile durable Razorpay webhook events, including out-of-order delivery."""
    from services.payment_service import fetch_tournament_payment

    now = _now()
    events = (
        CommunityPaymentWebhookEvent.query
        .filter(
            or_(
                and_(
                    CommunityPaymentWebhookEvent.status.in_({
                        CommunityPaymentWebhookStatus.PENDING,
                        CommunityPaymentWebhookStatus.RETRY,
                    }),
                    or_(
                        CommunityPaymentWebhookEvent.next_attempt_at.is_(None),
                        CommunityPaymentWebhookEvent.next_attempt_at <= now,
                    ),
                ),
                and_(
                    CommunityPaymentWebhookEvent.status == CommunityPaymentWebhookStatus.PROCESSING,
                    CommunityPaymentWebhookEvent.updated_at <= now - timedelta(minutes=10),
                ),
            )
        )
        .order_by(CommunityPaymentWebhookEvent.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(min(max(int(limit or 50), 1), 100))
        .all()
    )
    summary = {"processed": 0, "settled": 0, "retried": 0, "failed": 0}
    event_ids = []
    for event in events:
        event.status = CommunityPaymentWebhookStatus.PROCESSING
        event.attempts = int(event.attempts or 0) + 1
        event_ids.append(event.id)
    if event_ids:
        db.session.commit()
    for event_id in event_ids:
        summary["processed"] += 1
        try:
            event = CommunityPaymentWebhookEvent.query.filter_by(id=event_id).first()
            registration = (
                CommunityTournamentRegistration.query.filter_by(id=event.registration_id).first()
                if event and event.registration_id else None
            )
            if not event or not registration:
                raise CommunityValidationError("registration mapping is not available yet")
            tournament = CommunityTournament.query.filter_by(id=registration.tournament_id).first()
            if not tournament:
                raise CommunityValidationError("tournament not found")
            if event.event_type in {"payment.captured", "order.paid"}:
                if not event.payment_id:
                    raise CommunityValidationError("captured webhook has no payment ID")
                payment_details = fetch_tournament_payment(
                    event.payment_id,
                    tournament.entry_fee,
                    tournament.currency,
                    event.order_id,
                    expected_registration_id=registration.id,
                )
                settle_community_registration_payment(registration.id, payment_details)
                summary["settled"] += 1
            elif event.event_type == "payment.failed":
                record_community_registration_payment(registration.id, "failed", payment_reference=event.payment_id)
            # Authenticated non-payment events are retained but never mutate a registration.
            event = CommunityPaymentWebhookEvent.query.filter_by(id=event_id).first()
            event.status = CommunityPaymentWebhookStatus.PROCESSED
            event.processed_at = _now()
            event.next_attempt_at = None
            event.last_error = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            event = CommunityPaymentWebhookEvent.query.filter_by(id=event_id).first()
            if event:
                _retry_webhook_event(event, exc)
                db.session.commit()
                key = "failed" if event.status == CommunityPaymentWebhookStatus.FAILED else "retried"
                summary[key] += 1
    return summary


def register_for_tournament(user_id, tournament_id, payment_reference=None, payment_order_id=None, invite_code=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    if tournament.status != CommunityTournamentStatus.REGISTRATION_OPEN:
        raise CommunityConflictError("registration is not open")
    if tournament.invite_code_hash:
        supplied_hash = _invite_code_hash(invite_code or "")
        if not hmac.compare_digest(tournament.invite_code_hash, supplied_hash):
            raise CommunityForbiddenError("a valid tournament invite code is required")
    if tournament.registered_players_count >= tournament.max_players:
        tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
        raise CommunityConflictError("tournament is full")
    if int(tournament.host_user_id) == int(user_id):
        raise CommunityValidationError("host cannot register for their own tournament")
    user_exists = db.session.query(User.id).filter_by(id=int(user_id)).scalar()
    if not user_exists:
        raise CommunityValidationError("user not found")

    existing = CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament.id,
        user_id=int(user_id),
    ).filter(
        CommunityTournamentRegistration.status.notin_({
            CommunityTournamentRegistrationStatus.CANCELLED,
            CommunityTournamentRegistrationStatus.REFUNDED,
        })
    ).with_for_update().first()
    if existing:
        if existing.status == CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
            _queue_payment_settlement(existing, payment_reference, payment_order_id)
            db.session.commit()
        return existing

    reg = CommunityTournamentRegistration(
        tournament_id=tournament.id,
        user_id=int(user_id),
        status=CommunityTournamentRegistrationStatus.CONFIRMED if tournament.entry_fee == 0 else CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
        payment_status="not_required" if tournament.entry_fee == 0 else "unpaid",
        amount_paid=Decimal("0.00"),
        # Client-supplied IDs are queue hints only until Razorpay confirms and
        # binds them to this registration's order metadata.
        payment_reference=None,
        payment_provider="razorpay" if tournament.entry_fee > 0 else None,
        razorpay_payment_id=None,
        razorpay_order_id=None,
        confirmed_at=_now() if tournament.entry_fee == 0 else None,
    )
    db.session.add(reg)
    try:
        db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        raise CommunityConflictError("user is already registered") from exc

    if reg.status == CommunityTournamentRegistrationStatus.CONFIRMED:
        tournament.registered_players_count += 1
        _recalculate_prize_pool(tournament)
        if tournament.registered_players_count >= tournament.max_players:
            tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
    if tournament.entry_fee > 0:
        _queue_payment_settlement(reg, payment_reference, payment_order_id)
    _audit("registration_created", "community_tournament_registration", reg.id, user_id, metadata={"tournament_id": str(tournament.id)})
    _notify(user_id, "community_registration_success", "Registration received", f"You registered for {tournament.title}.", tournament.id)
    db.session.commit()
    return reg


def record_community_registration_payment(registration_id, status, payment_reference=None, payment_details=None):
    """Apply a verified payment-provider result exactly once to a community registration."""
    registration = CommunityTournamentRegistration.query.filter_by(id=registration_id).with_for_update().first()
    if not registration:
        raise CommunityValidationError("community registration not found")

    payment_details = payment_details or {}
    payment_id = str(payment_details.get("payment_id") or payment_reference or "").strip() or None
    order_id = str(payment_details.get("order_id") or "").strip() or None
    provider = str(payment_details.get("provider") or registration.payment_provider or "razorpay").strip().lower()
    if registration.status in {CommunityTournamentRegistrationStatus.CANCELLED, CommunityTournamentRegistrationStatus.REFUNDED}:
        if status != "succeeded" or not payment_details:
            raise CommunityConflictError("payment cannot be applied to a cancelled registration")
        _bind_verified_payment_attempt(registration, payment_details)
        registration.payment_reference = payment_id
        registration.razorpay_payment_id = payment_id
        registration.razorpay_order_id = order_id
        registration.payment_provider = provider
        tournament = CommunityTournament.query.filter_by(id=registration.tournament_id).first()
        if not tournament:
            raise CommunityValidationError("tournament not found")
        return _queue_captured_payment_refund(registration, tournament, "payment captured after registration cancellation")
    if status == "succeeded":
        _bind_verified_payment_attempt(registration, payment_details)
    if (
        registration.status == CommunityTournamentRegistrationStatus.CONFIRMED
        and registration.payment_status == "paid"
        and payment_id
        and registration.razorpay_payment_id
        and registration.razorpay_payment_id != payment_id
    ):
        raise CommunityConflictError("registration is already settled with a different payment")
    if payment_id:
        duplicate = CommunityTournamentRegistration.query.filter(
            or_(
                CommunityTournamentRegistration.razorpay_payment_id == payment_id,
                CommunityTournamentRegistration.payment_reference == payment_id,
            ),
            CommunityTournamentRegistration.id != registration.id,
        ).first()
        if duplicate:
            raise CommunityConflictError("payment is already settled against another registration")
        registration.payment_reference = payment_id
        registration.razorpay_payment_id = payment_id
    if order_id:
        registration.razorpay_order_id = order_id
    registration.payment_provider = provider
    if status != "succeeded":
        if registration.status == CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
            registration.payment_status = "failed"
            job = CommunityPaymentSettlementJob.query.filter_by(registration_id=registration.id).first()
            if job:
                job.status = CommunityPaymentSettlementStatus.FAILED
                job.last_error = "provider reported payment failure"
                job.next_attempt_at = None
            _audit("registration_payment_failed", "community_tournament_registration", registration.id, registration.user_id)
            db.session.commit()
        return registration

    if registration.status == CommunityTournamentRegistrationStatus.CONFIRMED and registration.payment_status == "paid":
        _queue_payment_settlement(registration, payment_id, order_id)
        job = CommunityPaymentSettlementJob.query.filter_by(registration_id=registration.id).first()
        if job:
            job.status = CommunityPaymentSettlementStatus.SETTLED
            job.settled_at = job.settled_at or _now()
        db.session.commit()
        return registration
    if registration.status != CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
        raise CommunityConflictError("registration cannot be confirmed from its current state")

    tournament = CommunityTournament.query.filter_by(id=registration.tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    if tournament.status not in {CommunityTournamentStatus.REGISTRATION_OPEN, CommunityTournamentStatus.REGISTRATION_CLOSED}:
        return _queue_captured_payment_refund(registration, tournament, "payment captured after registration closed")
    if tournament.registered_players_count >= tournament.max_players:
        tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
        return _queue_captured_payment_refund(registration, tournament, "payment captured after tournament reached capacity")

    registration.status = CommunityTournamentRegistrationStatus.CONFIRMED
    registration.payment_status = "paid"
    registration.amount_paid = tournament.entry_fee
    registration.payment_verified_at = _now()
    registration.confirmed_at = registration.confirmed_at or _now()
    registration.paid_at = registration.paid_at or _now()
    tournament.registered_players_count += 1
    _recalculate_prize_pool(tournament)
    if tournament.registered_players_count >= tournament.max_players:
        tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
    _audit("registration_payment_confirmed", "community_tournament_registration", registration.id, registration.user_id)
    _notify(registration.user_id, "community_registration_confirmed", "Registration confirmed", f"Your registration for {tournament.title} is confirmed.", tournament.id)
    job = _queue_payment_settlement(registration, payment_id, order_id, payment_details)
    job.status = CommunityPaymentSettlementStatus.SETTLED
    job.settled_at = _now()
    job.next_attempt_at = None
    db.session.commit()
    return registration


def settle_community_registration_payment(registration_id, payment_details):
    """Settle a provider-verified community payment exactly once."""
    if str(payment_details.get("status") or "").lower() != "captured":
        raise CommunityConflictError("payment is not captured")
    return record_community_registration_payment(
        registration_id,
        "succeeded",
        payment_reference=payment_details.get("payment_id"),
        payment_details=payment_details,
    )


def process_pending_community_payments(limit=50):
    """Cron worker: fetch pending Razorpay payments and settle captured ones."""
    from services.payment_service import fetch_tournament_payment

    limit = min(max(int(limit or 50), 1), 100)
    webhook_summary = process_pending_community_payment_webhooks(limit)
    now = _now()
    jobs = (
        CommunityPaymentSettlementJob.query
        .filter(
            or_(
                and_(
                    CommunityPaymentSettlementJob.status.in_({
                        CommunityPaymentSettlementStatus.PENDING,
                        CommunityPaymentSettlementStatus.RETRY,
                    }),
                    or_(
                        CommunityPaymentSettlementJob.next_attempt_at.is_(None),
                        CommunityPaymentSettlementJob.next_attempt_at <= now,
                    ),
                ),
                and_(
                    CommunityPaymentSettlementJob.status == CommunityPaymentSettlementStatus.PROCESSING,
                    CommunityPaymentSettlementJob.updated_at <= now - timedelta(minutes=10),
                ),
            ),
        )
        .order_by(CommunityPaymentSettlementJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    summary = {"processed": 0, "settled": 0, "retried": 0, "failed": 0, "items": [], "webhooks": webhook_summary}
    job_ids = []
    for job in jobs:
        job.status = CommunityPaymentSettlementStatus.PROCESSING
        job.attempts = int(job.attempts or 0) + 1
        job_ids.append(job.id)
    if job_ids:
        db.session.commit()
    for job_id in job_ids:
        job = CommunityPaymentSettlementJob.query.filter_by(id=job_id).first()
        if not job:
            continue
        summary["processed"] += 1
        registration = CommunityTournamentRegistration.query.filter_by(id=job.registration_id).first()
        tournament = CommunityTournament.query.filter_by(id=job.tournament_id).first()
        if not registration or not tournament or registration.status != CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
            job.status = CommunityPaymentSettlementStatus.FAILED
            job.last_error = "registration is no longer pending payment"
            db.session.commit()
            summary["failed"] += 1
            summary["items"].append(job.to_dict())
            continue
        if not job.payment_id:
            job.status = CommunityPaymentSettlementStatus.RETRY
            job.last_error = "Razorpay payment ID is not available yet"
        else:
            try:
                payment_details = fetch_tournament_payment(
                    job.payment_id,
                    tournament.entry_fee,
                    tournament.currency,
                    job.order_id,
                    expected_registration_id=registration.id,
                )
                settle_community_registration_payment(registration.id, payment_details)
                summary["settled"] += 1
                summary["items"].append({"registration_id": str(registration.id), "status": "settled"})
                continue
            except Exception as exc:
                error_text = str(exc)[:500]
                if "status: failed" in error_text.lower():
                    record_community_registration_payment(registration.id, "failed", payment_reference=job.payment_id)
                    job.status = CommunityPaymentSettlementStatus.FAILED
                    job.last_error = error_text
                    job.next_attempt_at = None
                    db.session.commit()
                    summary["failed"] += 1
                    summary["items"].append(job.to_dict())
                    continue
                job.status = CommunityPaymentSettlementStatus.RETRY
                job.last_error = error_text
        delay_minutes = min(60, max(1, 2 ** min(job.attempts, 6)))
        job.next_attempt_at = _now() + timedelta(minutes=delay_minutes)
        db.session.commit()
        summary["retried"] += 1
        summary["items"].append(job.to_dict())
    summary["refunds"] = process_pending_community_refunds(limit)
    return summary


def _apply_provider_refund(registration, refund):
    status = str(refund.get("status") or "").lower()
    if status not in {"pending", "processed"}:
        raise CommunityConflictError("payment provider did not accept the refund")
    registration.razorpay_refund_id = str(refund.get("refund_id") or "") or registration.razorpay_refund_id
    registration.refund_amount = _money(refund.get("amount"), "refund_amount")
    registration.refund_status = status
    registration.refund_requested_at = registration.refund_requested_at or _now()
    registration.refund_error = None
    if status == "processed":
        registration.status = CommunityTournamentRegistrationStatus.REFUNDED
        registration.payment_status = "refunded"
        registration.refunded_at = registration.refunded_at or _now()
    else:
        registration.status = CommunityTournamentRegistrationStatus.REFUND_PENDING
        registration.payment_status = "refund_pending"


def _refund_or_cancel_registration(registration, tournament):
    from services.payment_service import refund_tournament_payment

    was_confirmed = registration.status == CommunityTournamentRegistrationStatus.CONFIRMED
    is_paid = registration.payment_status in {"paid", "refund_pending"} and Decimal(registration.amount_paid or 0) > 0
    if is_paid:
        provider = str(registration.payment_provider or "").lower()
        if provider == "wallet":
            if registration.status != CommunityTournamentRegistrationStatus.REFUND_PENDING:
                _apply_wallet_transaction(
                    registration.user_id,
                    registration.amount_paid,
                    "community-tournament-refund",
                    tournament.id,
                )
            registration.refund_amount = registration.amount_paid
            registration.refund_status = "processed"
            registration.refund_requested_at = registration.refund_requested_at or _now()
            registration.refunded_at = registration.refunded_at or _now()
            registration.payment_status = "refunded"
            registration.status = CommunityTournamentRegistrationStatus.REFUNDED
        elif provider in {"razorpay", "mock"}:
            if not registration.razorpay_payment_id:
                raise CommunityConflictError("paid registration is missing its provider payment ID")
            try:
                receipt = f"ctr_{str(registration.id).replace('-', '')}"
                refund = refund_tournament_payment(
                    registration.razorpay_payment_id,
                    registration.amount_paid,
                    tournament.currency,
                    receipt,
                    existing_refund_id=registration.razorpay_refund_id,
                    provider=provider,
                )
            except CommunityConflictError:
                raise
            except Exception as exc:
                raise CommunityConflictError(
                    "refund could not be initiated; registration remains active"
                ) from exc
            _apply_provider_refund(registration, refund)
        else:
            raise CommunityConflictError("paid registration has no supported refund provider")
    else:
        registration.status = CommunityTournamentRegistrationStatus.CANCELLED

    registration.cancelled_at = registration.cancelled_at or _now()
    if was_confirmed:
        tournament.registered_players_count = max(0, tournament.registered_players_count - 1)
    _recalculate_prize_pool(tournament)
    return registration


def process_pending_community_refunds(limit=50):
    """Reconcile provider refunds accepted but not yet processed."""
    from services.payment_service import refund_tournament_payment

    registrations = (
        CommunityTournamentRegistration.query
        .filter_by(status=CommunityTournamentRegistrationStatus.REFUND_PENDING)
        .order_by(CommunityTournamentRegistration.refund_requested_at.asc())
        .limit(min(max(int(limit or 50), 1), 100))
        .all()
    )
    summary = {"processed": 0, "refunded": 0, "pending": 0, "failed": 0, "items": []}
    for registration in registrations:
        summary["processed"] += 1
        registration_id = registration.id
        tournament = CommunityTournament.query.filter_by(id=registration.tournament_id).first()
        try:
            if not tournament or not registration.razorpay_payment_id:
                raise CommunityConflictError("refund registration is missing payment data")
            receipt = f"ctr_{str(registration.id).replace('-', '')}"
            refund = refund_tournament_payment(
                registration.razorpay_payment_id,
                registration.amount_paid,
                tournament.currency,
                receipt,
                existing_refund_id=registration.razorpay_refund_id,
                provider=registration.payment_provider,
            )
            _apply_provider_refund(registration, refund)
            if registration.status == CommunityTournamentRegistrationStatus.REFUNDED:
                _audit(
                    "registration_refund_processed",
                    "community_tournament_registration",
                    registration.id,
                    actor_type="system",
                    metadata={"provider": registration.payment_provider},
                )
                _notify(
                    registration.user_id,
                    "community_registration_refunded",
                    "Refund processed",
                    f"Your refund for {tournament.title} has been processed.",
                    tournament.id,
                )
            db.session.commit()
            key = "refunded" if registration.status == CommunityTournamentRegistrationStatus.REFUNDED else "pending"
            summary[key] += 1
            summary["items"].append({"registration_id": str(registration.id), "status": registration.refund_status})
        except Exception as exc:
            db.session.rollback()
            failed = CommunityTournamentRegistration.query.filter_by(id=registration_id).first()
            if failed:
                failed.refund_error = str(exc)[:500]
                db.session.commit()
            summary["failed"] += 1
            summary["items"].append({"registration_id": str(registration_id), "status": "failed"})
    return summary


def list_pending_community_payments(filters):
    page, per_page = _pagination(filters)
    status = str(filters.get("status") or "").strip().lower()
    query = CommunityPaymentSettlementJob.query
    if status:
        valid = {
            CommunityPaymentSettlementStatus.PENDING,
            CommunityPaymentSettlementStatus.RETRY,
            CommunityPaymentSettlementStatus.PROCESSING,
            CommunityPaymentSettlementStatus.SETTLED,
            CommunityPaymentSettlementStatus.FAILED,
        }
        if status not in valid:
            raise CommunityValidationError("invalid payment queue status")
        query = query.filter_by(status=status)
    total = query.count()
    jobs = query.order_by(CommunityPaymentSettlementJob.created_at.asc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [job.to_dict() for job in jobs],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def cancel_registration(user_id, tournament_id):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    reg = (
        CommunityTournamentRegistration.query
        .filter(
            CommunityTournamentRegistration.tournament_id == tournament_id,
            CommunityTournamentRegistration.user_id == int(user_id),
            CommunityTournamentRegistration.status.in_({
                CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
                CommunityTournamentRegistrationStatus.CONFIRMED,
                CommunityTournamentRegistrationStatus.REFUND_PENDING,
            }),
        )
        .order_by(CommunityTournamentRegistration.created_at.desc())
        .with_for_update()
        .first()
    )
    if not reg:
        raise CommunityValidationError("active registration not found")
    sync_tournament_status(tournament)
    if tournament.status in {CommunityTournamentStatus.LIVE, CommunityTournamentStatus.COMPLETED}:
        raise CommunityConflictError("registration cannot be cancelled after tournament starts")
    try:
        _refund_or_cancel_registration(reg, tournament)
    except Exception:
        db.session.rollback()
        raise
    sync_tournament_status(tournament)
    _audit(
        "registration_cancelled",
        "community_tournament_registration",
        reg.id,
        user_id,
        metadata={"refund_status": reg.refund_status},
    )
    db.session.commit()
    return reg


def my_tournaments(user_id, role):
    if role == "hosted":
        rows = CommunityTournament.query.filter_by(host_user_id=int(user_id)).order_by(CommunityTournament.created_at.desc()).all()
        return [row.to_dict(include_room_details=True) for row in rows]
    query = (
        db.session.query(CommunityTournament, CommunityTournamentRegistration)
        .join(CommunityTournamentRegistration, CommunityTournamentRegistration.tournament_id == CommunityTournament.id)
        .filter(CommunityTournamentRegistration.user_id == int(user_id))
        .order_by(CommunityTournamentRegistration.created_at.desc())
    )
    return [{**t.to_dict(), "registration": r.to_dict()} for t, r in query.all()]


def _owned_tournament(host_user_id, tournament_id, lock=False):
    query = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id))
    if lock:
        query = query.with_for_update()
    tournament = query.first()
    if not tournament:
        raise CommunityForbiddenError("You do not have permission to manage this tournament")
    return tournament


def _pagination(filters):
    page = max(int(filters.get("page") or 1), 1)
    per_page = min(max(int(filters.get("per_page") or filters.get("limit") or 50), 1), 100)
    return page, per_page


def _gamer_summaries(user_ids):
    ids = {int(user_id) for user_id in user_ids if user_id is not None}
    if not ids:
        return {}
    rows = User.query.with_entities(User.id, User.name, User.game_username, User.avatar_path).filter(User.id.in_(ids)).all()
    return {
        int(row.id): {
            "id": int(row.id),
            "display_name": row.name or "",
            "game_username": row.game_username or "",
            "avatar_url": row.avatar_path or None,
        }
        for row in rows
    }


def list_host_registrations(host_user_id, tournament_id, filters):
    tournament = _owned_tournament(host_user_id, tournament_id)
    page, per_page = _pagination(filters)
    status = str(filters.get("status") or "").strip().lower()
    valid_statuses = {
        CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
        CommunityTournamentRegistrationStatus.CONFIRMED,
        CommunityTournamentRegistrationStatus.CANCELLED,
        CommunityTournamentRegistrationStatus.REFUND_PENDING,
        CommunityTournamentRegistrationStatus.REFUNDED,
    }
    if status and status not in valid_statuses:
        raise CommunityValidationError("invalid registration status")
    query = CommunityTournamentRegistration.query.filter_by(tournament_id=tournament.id)
    if status:
        query = query.filter_by(status=status)
    total = query.count()
    registrations = query.order_by(CommunityTournamentRegistration.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    gamers = _gamer_summaries(reg.user_id for reg in registrations)
    return {
        "items": [{**registration.to_dict(), "gamer": gamers.get(int(registration.user_id))} for registration in registrations],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def manage_registration(host_user_id, tournament_id, registration_id, payload):
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    registration = CommunityTournamentRegistration.query.filter_by(id=registration_id, tournament_id=tournament.id).with_for_update().first()
    if not registration:
        raise CommunityValidationError("registration not found")
    action = str(payload.get("action") or "").strip().lower()
    if payload.get("payment_reference") is not None:
        registration.payment_reference = str(payload.get("payment_reference") or "").strip() or None

    sync_tournament_status(tournament)
    if action in {"confirm_payment", "reject_payment"}:
        raise CommunityConflictError("provider payments are managed only by payment verification or webhook")
    elif action in {"check_in", "undo_check_in"}:
        if registration.status != CommunityTournamentRegistrationStatus.CONFIRMED:
            raise CommunityConflictError("only confirmed registrations can be checked in")
        if tournament.status not in {CommunityTournamentStatus.REGISTRATION_CLOSED, CommunityTournamentStatus.LIVE}:
            raise CommunityConflictError("check-in is not available yet")
        registration.checked_in_at = _now() if action == "check_in" else None
    elif action == "remove_participant":
        if tournament.status in {CommunityTournamentStatus.LIVE, CommunityTournamentStatus.COMPLETED, CommunityTournamentStatus.CANCELLED}:
            raise CommunityConflictError("participants cannot be removed after the tournament starts")
        if registration.status not in {
            CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
            CommunityTournamentRegistrationStatus.CONFIRMED,
            CommunityTournamentRegistrationStatus.REFUND_PENDING,
        }:
            raise CommunityConflictError("registration is no longer active")
        try:
            _refund_or_cancel_registration(registration, tournament)
        except Exception:
            db.session.rollback()
            raise
        title = "Refund initiated" if registration.status == CommunityTournamentRegistrationStatus.REFUND_PENDING else "Registration cancelled"
        _notify(registration.user_id, "community_registration_removed", title, f"Your registration for {tournament.title} was cancelled by the host.", tournament.id)
    else:
        raise CommunityValidationError("action must be check_in, undo_check_in, or remove_participant")

    sync_tournament_status(tournament)
    _audit("registration_managed", "community_tournament_registration", registration.id, host_user_id, metadata={"action": action})
    db.session.commit()
    return {**registration.to_dict(), "gamer": _gamer_summaries([registration.user_id]).get(int(registration.user_id))}


def list_host_results(host_user_id, tournament_id, filters):
    tournament = _owned_tournament(host_user_id, tournament_id)
    page, per_page = _pagination(filters)
    query = CommunityMatchResult.query.filter_by(tournament_id=tournament.id)
    status = str(filters.get("status") or "").strip().lower()
    if status:
        valid_statuses = {CommunityResultStatus.SUBMITTED, CommunityResultStatus.VERIFIED, CommunityResultStatus.REJECTED, CommunityResultStatus.ADMIN_OVERRIDDEN}
        if status not in valid_statuses:
            raise CommunityValidationError("invalid result status")
        query = query.filter_by(status=status)
    total = query.count()
    results = query.order_by(CommunityMatchResult.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    gamers = _gamer_summaries([result.winner_user_id for result in results] + [result.submitted_by_user_id for result in results])
    return {
        "items": [
            {
                **result.to_dict(),
                "winner": gamers.get(int(result.winner_user_id)) if result.winner_user_id else None,
                "submitted_by": gamers.get(int(result.submitted_by_user_id)) if result.submitted_by_user_id else None,
            }
            for result in results
        ],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def list_host_disputes(host_user_id, tournament_id, filters):
    tournament = _owned_tournament(host_user_id, tournament_id)
    page, per_page = _pagination(filters)
    query = CommunityTournamentDispute.query.filter_by(tournament_id=tournament.id)
    status = str(filters.get("status") or "").strip().lower()
    if status:
        valid_statuses = {CommunityDisputeStatus.OPEN, CommunityDisputeStatus.UNDER_REVIEW, CommunityDisputeStatus.APPROVED, CommunityDisputeStatus.REJECTED, CommunityDisputeStatus.CLOSED}
        if status not in valid_statuses:
            raise CommunityValidationError("invalid dispute status")
        query = query.filter_by(status=status)
    total = query.count()
    disputes = query.order_by(CommunityTournamentDispute.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    gamers = _gamer_summaries(dispute.reported_by_user_id for dispute in disputes)
    return {
        "items": [{**dispute.to_dict(), "reported_by": gamers.get(int(dispute.reported_by_user_id)) if dispute.reported_by_user_id else None} for dispute in disputes],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def list_host_payouts(host_user_id, tournament_id, filters):
    tournament = _owned_tournament(host_user_id, tournament_id)
    page, per_page = _pagination(filters)
    query = CommunityTournamentPayout.query.filter_by(tournament_id=tournament.id)
    status = str(filters.get("status") or "").strip().lower()
    if status:
        valid_statuses = {CommunityPayoutStatus.PENDING_ADMIN_APPROVAL, CommunityPayoutStatus.APPROVED, CommunityPayoutStatus.PAID, CommunityPayoutStatus.FAILED, CommunityPayoutStatus.CANCELLED}
        if status not in valid_statuses:
            raise CommunityValidationError("invalid payout status")
        query = query.filter_by(status=status)
    total = query.count()
    payouts = query.order_by(CommunityTournamentPayout.rank.asc(), CommunityTournamentPayout.created_at.asc()).offset((page - 1) * per_page).limit(per_page).all()
    gamers = _gamer_summaries(payout.user_id for payout in payouts)
    return {
        "items": [{**payout.to_dict(), "gamer": gamers.get(int(payout.user_id))} for payout in payouts],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def list_admin_disputes(tournament_id, filters):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    page, per_page = _pagination(filters)
    query = CommunityTournamentDispute.query.filter_by(tournament_id=tournament.id)
    status = str(filters.get("status") or "").strip().lower()
    if status:
        valid_statuses = {CommunityDisputeStatus.OPEN, CommunityDisputeStatus.UNDER_REVIEW, CommunityDisputeStatus.APPROVED, CommunityDisputeStatus.REJECTED, CommunityDisputeStatus.CLOSED}
        if status not in valid_statuses:
            raise CommunityValidationError("invalid dispute status")
        query = query.filter_by(status=status)
    total = query.count()
    disputes = query.order_by(CommunityTournamentDispute.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    gamers = _gamer_summaries(dispute.reported_by_user_id for dispute in disputes)
    return {
        "items": [{**dispute.to_dict(), "reported_by": gamers.get(int(dispute.reported_by_user_id)) if dispute.reported_by_user_id else None} for dispute in disputes],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def list_admin_host_verifications(filters):
    page, per_page = _pagination(filters)
    query = CommunityHostVerification.query
    status = str(filters.get("status") or "").strip().lower()
    if status:
        valid_statuses = {CommunityHostStatus.PENDING, CommunityHostStatus.VERIFIED, CommunityHostStatus.REJECTED, CommunityHostStatus.SUSPENDED}
        if status not in valid_statuses:
            raise CommunityValidationError("invalid host verification status")
        query = query.filter_by(verification_status=status)
    total = query.count()
    verifications = query.order_by(CommunityHostVerification.created_at.asc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [verification.to_dict() for verification in verifications],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def list_admin_payouts(tournament_id, filters):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    page, per_page = _pagination(filters)
    query = CommunityTournamentPayout.query.filter_by(tournament_id=tournament.id)
    status = str(filters.get("status") or "").strip().lower()
    if status:
        valid_statuses = {CommunityPayoutStatus.PENDING_ADMIN_APPROVAL, CommunityPayoutStatus.APPROVED, CommunityPayoutStatus.PAID, CommunityPayoutStatus.FAILED, CommunityPayoutStatus.CANCELLED}
        if status not in valid_statuses:
            raise CommunityValidationError("invalid payout status")
        query = query.filter_by(status=status)
    total = query.count()
    payouts = query.order_by(CommunityTournamentPayout.rank.asc(), CommunityTournamentPayout.created_at.asc()).offset((page - 1) * per_page).limit(per_page).all()
    gamers = _gamer_summaries(payout.user_id for payout in payouts)
    return {
        "items": [{**payout.to_dict(), "gamer": gamers.get(int(payout.user_id))} for payout in payouts],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def review_payout(tournament_id, payout_id, payload, admin_id=None):
    payout = CommunityTournamentPayout.query.filter_by(id=payout_id, tournament_id=tournament_id).with_for_update().first()
    if not payout:
        raise CommunityValidationError("payout not found")
    status = str(payload.get("status") or "").strip().lower()
    if status not in {CommunityPayoutStatus.APPROVED, CommunityPayoutStatus.PAID, CommunityPayoutStatus.FAILED, CommunityPayoutStatus.CANCELLED}:
        raise CommunityValidationError("status must be approved, paid, failed, or cancelled")
    if payout.status in {CommunityPayoutStatus.PAID, CommunityPayoutStatus.CANCELLED}:
        raise CommunityConflictError("paid or cancelled payouts cannot be changed")
    if status == CommunityPayoutStatus.PAID and payout.status != CommunityPayoutStatus.APPROVED:
        raise CommunityConflictError("payout must be approved before it can be paid")

    payout.status = status
    if status == CommunityPayoutStatus.APPROVED:
        payout.approved_by_admin_id = int(admin_id) if admin_id else None
        payout.approved_at = _now()
    elif status == CommunityPayoutStatus.PAID:
        payout.paid_at = _now()
        transaction_type = (
            "community-tournament-organizer-commission"
            if payout.payout_type == "organizer_commission"
            else "community-tournament-prize"
        )
        _apply_wallet_transaction(payout.user_id, payout.amount, transaction_type, payout.tournament_id)
    _audit("payout_reviewed", "community_tournament_payout", payout.id, admin_id, "admin", {"status": status})
    _notify(payout.user_id, "community_payout_updated", "Tournament payout updated", f"Your tournament payout is now {status}.", payout.tournament_id)
    db.session.commit()
    return payout


def submit_match_result(user_id, tournament_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    registered = CommunityTournamentRegistration.query.filter_by(tournament_id=tournament.id, user_id=int(user_id), status=CommunityTournamentRegistrationStatus.CONFIRMED).first()
    if int(tournament.host_user_id) != int(user_id) and not registered:
        raise CommunityForbiddenError("only host or registered players can submit results")
    try:
        winner_user_id = int(payload["winner_user_id"]) if payload.get("winner_user_id") else None
        rank = int(payload["rank"]) if payload.get("rank") else None
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("winner_user_id and rank must be integers") from exc
    if winner_user_id and not CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament.id,
        user_id=winner_user_id,
        status=CommunityTournamentRegistrationStatus.CONFIRMED,
    ).first():
        raise CommunityValidationError("winner_user_id must be a confirmed tournament participant")
    if rank is not None and rank <= 0:
        raise CommunityValidationError("rank must be positive")
    result = CommunityMatchResult(
        tournament_id=tournament.id,
        submitted_by_user_id=int(user_id),
        winner_user_id=winner_user_id,
        rank=rank,
        score=str(payload.get("score") or "").strip() or None,
        evidence_asset_ids=_validated_evidence_asset_ids(
            payload.get("evidence_asset_ids") or [],
            tournament.id,
            user_id,
            {"result_evidence"},
        ),
        stream_url=str(payload.get("stream_url") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
    )
    db.session.add(result)
    db.session.flush()
    _audit("match_result_submitted", "community_match_result", result.id, user_id)
    _notify(tournament.host_user_id, "community_result_submitted", "Match result submitted", f"A result was submitted for {tournament.title}.", tournament.id)
    db.session.commit()
    return result


def verify_match_result(host_user_id, tournament_id, result_id, payload):
    result = CommunityMatchResult.query.filter_by(id=result_id, tournament_id=tournament_id).first()
    tournament = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id)).first()
    if not result or not tournament:
        raise CommunityValidationError("result not found")
    status = str(payload.get("status") or CommunityResultStatus.VERIFIED).strip().lower()
    if status not in {CommunityResultStatus.VERIFIED, CommunityResultStatus.REJECTED, CommunityResultStatus.ADMIN_OVERRIDDEN}:
        raise CommunityValidationError("invalid result status")
    result.status = status
    result.verified_by_user_id = int(host_user_id)
    result.verified_at = _now()
    _audit("match_result_verified", "community_match_result", result.id, host_user_id, metadata={"status": status})
    db.session.commit()
    return result


def create_dispute(user_id, tournament_id, payload):
    reason = str(payload.get("reason") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not reason or not description:
        raise CommunityValidationError("reason and description are required")
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    registration = CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament.id,
        user_id=int(user_id),
        status=CommunityTournamentRegistrationStatus.CONFIRMED,
    ).first()
    if int(tournament.host_user_id) != int(user_id) and not registration:
        raise CommunityForbiddenError("only the host or confirmed participants can open disputes")
    result_id = uuid.UUID(str(payload["result_id"])) if payload.get("result_id") else None
    match_id = uuid.UUID(str(payload["match_id"])) if payload.get("match_id") else None
    if result_id and not CommunityMatchResult.query.filter_by(id=result_id, tournament_id=tournament.id).first():
        raise CommunityValidationError("result_id does not belong to this tournament")
    if match_id:
        from models.communityTournamentOperations import CommunityTournamentMatch
        if not CommunityTournamentMatch.query.filter_by(id=match_id, tournament_id=tournament.id).first():
            raise CommunityValidationError("match_id does not belong to this tournament")
    dispute = CommunityTournamentDispute(
        tournament_id=tournament.id,
        result_id=result_id,
        match_id=match_id,
        reported_by_user_id=int(user_id),
        reason=reason,
        description=description,
        evidence_asset_ids=_validated_evidence_asset_ids(
            payload.get("evidence_asset_ids") or [],
            tournament.id,
            user_id,
            {"dispute_evidence", "result_evidence"},
        ),
        response_deadline_at=_now() + timedelta(minutes=int(tournament.dispute_window_minutes or 30)),
    )
    db.session.add(dispute)
    db.session.flush()
    provision_dispute_chat_room(dispute, tournament)
    _audit("dispute_created", "community_tournament_dispute", dispute.id, user_id)
    _notify(tournament.host_user_id, "community_dispute_created", "Tournament dispute opened", f"A dispute was opened for {tournament.title}.", tournament.id)
    db.session.commit()
    return dispute


def review_dispute(dispute_id, payload, admin_id=None):
    dispute = CommunityTournamentDispute.query.filter_by(id=dispute_id).first()
    if not dispute:
        raise CommunityValidationError("dispute not found")
    status = str(payload.get("status") or "").strip().lower()
    if status not in {
        CommunityDisputeStatus.UNDER_REVIEW,
        CommunityDisputeStatus.APPROVED,
        CommunityDisputeStatus.REJECTED,
        CommunityDisputeStatus.CLOSED,
    }:
        raise CommunityValidationError("invalid dispute status")
    dispute.status = status
    dispute.admin_comment = str(payload.get("admin_comment") or "").strip() or None
    dispute.resolution_action = str(payload.get("resolution_action") or "").strip().lower() or None
    dispute.reviewed_by_admin_id = int(admin_id) if admin_id else None
    dispute.reviewed_at = _now()
    _audit("dispute_reviewed", "community_tournament_dispute", dispute.id, admin_id, "admin", {"status": status})
    db.session.commit()
    return dispute


def submit_winners(host_user_id, tournament_id, winners):
    tournament = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id)).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    if tournament.status not in {CommunityTournamentStatus.LIVE, CommunityTournamentStatus.COMPLETED}:
        raise CommunityConflictError("winners can only be submitted after the tournament starts")
    if not isinstance(winners, list) or not winners:
        raise CommunityValidationError("winners must be a non-empty list")
    existing = CommunityTournamentPayout.query.filter_by(tournament_id=tournament.id).first()
    if existing:
        raise CommunityConflictError("winners already submitted")
    open_dispute = CommunityTournamentDispute.query.filter(
        CommunityTournamentDispute.tournament_id == tournament.id,
        CommunityTournamentDispute.status.in_({
            CommunityDisputeStatus.OPEN,
            CommunityDisputeStatus.UNDER_REVIEW,
        }),
    ).first()
    if open_dispute:
        raise CommunityConflictError("winners cannot be submitted while tournament disputes are open")
    from models.communityTournamentOperations import CommunityMatchStatus, CommunityTournamentMatch
    generated_match = CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).first()
    unfinished_match = CommunityTournamentMatch.query.filter(
        CommunityTournamentMatch.tournament_id == tournament.id,
        CommunityTournamentMatch.status.notin_({
            CommunityMatchStatus.COMPLETED,
            CommunityMatchStatus.CANCELLED,
        }),
    ).first()
    if generated_match and unfinished_match:
        raise CommunityConflictError("all generated matches must be completed before winners are submitted")

    distribution = tournament.prize_distribution or []
    payout_rows = []
    winner_user_ids = set()
    ranks = set()
    total_payout = Decimal("0.00")
    for idx, winner in enumerate(winners):
        try:
            winner_user_id = int(winner["user_id"])
            rank = int(winner.get("rank") or idx + 1)
        except (KeyError, TypeError, ValueError) as exc:
            raise CommunityValidationError("each winner requires a valid user_id and rank") from exc
        if rank <= 0 or rank in ranks:
            raise CommunityValidationError("winner ranks must be unique positive integers")
        if winner_user_id in winner_user_ids:
            raise CommunityValidationError("a participant can only receive one payout")
        confirmed_registration = CommunityTournamentRegistration.query.filter_by(
            tournament_id=tournament.id,
            user_id=winner_user_id,
            status=CommunityTournamentRegistrationStatus.CONFIRMED,
        ).first()
        if not confirmed_registration:
            raise CommunityValidationError("winners must be confirmed tournament participants")
        amount = _money(winner.get("amount", 0), "winner amount")
        if amount == 0 and rank <= len(distribution):
            share = Decimal(str(distribution[rank - 1].get("percent", 0))) / Decimal("100")
            amount = (Decimal(str(tournament.prize_pool or 0)) * share).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        winner_user_ids.add(winner_user_id)
        ranks.add(rank)
        total_payout += amount
        payout_rows.append((winner_user_id, rank, amount))
    if total_payout > Decimal(str(tournament.prize_pool or 0)):
        raise CommunityValidationError("winner payout total cannot exceed the tournament prize pool")
    for winner_user_id, rank, amount in payout_rows:
        db.session.add(
            CommunityTournamentPayout(
                tournament_id=tournament.id,
                user_id=winner_user_id,
                rank=rank,
                amount=amount,
                currency=tournament.currency,
                payout_type="player_prize",
                status=CommunityPayoutStatus.PENDING_ADMIN_APPROVAL,
            )
        )
    organizer_commission = Decimal(str(tournament.organizer_commission_amount or 0))
    if organizer_commission > 0:
        db.session.add(
            CommunityTournamentPayout(
                tournament_id=tournament.id,
                user_id=tournament.host_user_id,
                rank=None,
                payout_type="organizer_commission",
                amount=organizer_commission,
                currency=tournament.currency,
                status=CommunityPayoutStatus.PENDING_ADMIN_APPROVAL,
            )
        )
    tournament.status = CommunityTournamentStatus.COMPLETED
    _audit("winners_submitted", "community_tournament", tournament.id, host_user_id, metadata={"winner_count": len(winners)})
    db.session.commit()
    return CommunityTournamentPayout.query.filter_by(tournament_id=tournament.id).order_by(CommunityTournamentPayout.rank.asc().nullslast()).all()


def create_file_asset(user_id, payload):
    purpose = str(payload.get("purpose") or "").strip()
    file_url = str(payload.get("file_url") or "").strip()
    if not purpose or not file_url:
        raise CommunityValidationError("purpose and file_url are required")
    allowed_purposes = {"banner", "government_id", "result_evidence", "dispute_evidence"}
    if purpose not in allowed_purposes:
        raise CommunityValidationError("unsupported file purpose")
    parsed_url = urlparse(file_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise CommunityValidationError("file_url must be an absolute http or https URL")
    try:
        file_size_bytes = int(payload["file_size_bytes"]) if payload.get("file_size_bytes") is not None else None
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("file_size_bytes must be an integer") from exc
    if file_size_bytes is not None and (file_size_bytes < 0 or file_size_bytes > 100 * 1024 * 1024):
        raise CommunityValidationError("file_size_bytes must be between 0 and 100 MB")
    tournament_id = uuid.UUID(str(payload["tournament_id"])) if payload.get("tournament_id") else None
    if purpose == "government_id" and tournament_id:
        raise CommunityValidationError("government_id assets cannot be attached to a tournament")
    if purpose in {"result_evidence", "dispute_evidence"} and not tournament_id:
        raise CommunityValidationError("tournament_id is required for evidence assets")
    if tournament_id:
        tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
        if not tournament:
            raise CommunityValidationError("tournament not found")
        is_host = int(tournament.host_user_id) == int(user_id)
        registration = CommunityTournamentRegistration.query.filter_by(
            tournament_id=tournament.id,
            user_id=int(user_id),
            status=CommunityTournamentRegistrationStatus.CONFIRMED,
        ).first()
        if purpose == "banner" and not is_host:
            raise CommunityForbiddenError("only the tournament host can create banner assets")
        if purpose in {"result_evidence", "dispute_evidence"} and not is_host and not registration:
            raise CommunityForbiddenError("only the host or confirmed participants can create evidence assets")
    asset = CommunityFileAsset(
        owner_user_id=int(user_id),
        tournament_id=tournament_id,
        purpose=purpose,
        file_url=file_url,
        storage_key=str(payload.get("storage_key") or "").strip() or None,
        mime_type=str(payload.get("mime_type") or "").strip() or None,
        file_size_bytes=file_size_bytes,
        checksum=str(payload.get("checksum") or "").strip() or None,
        meta=payload.get("metadata") or {},
    )
    db.session.add(asset)
    db.session.flush()
    _audit("file_asset_created", "community_file_asset", asset.id, user_id)
    db.session.commit()
    return asset
