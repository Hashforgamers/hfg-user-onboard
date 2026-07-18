from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import re
import uuid

from flask import current_app
from sqlalchemy import func, or_
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
)
from models.hashWalletTransaction import HashWalletTransaction
from models.hashWallet import HashWallet
from models.notification import Notification
from models.user import User


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
        if tournament.registered_players_count >= tournament.max_players:
            return CommunityTournamentStatus.REGISTRATION_CLOSED
        return CommunityTournamentStatus.REGISTRATION_OPEN
    if current < tournament.tournament_start_at:
        return CommunityTournamentStatus.REGISTRATION_CLOSED
    end_at = tournament.tournament_end_at
    if end_at and current > end_at:
        return CommunityTournamentStatus.COMPLETED
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
    commission = (total * commission_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tournament.total_collection = total
    tournament.organizer_commission_rate = commission_rate
    tournament.organizer_commission_amount = commission
    tournament.platform_fee_amount = commission
    tournament.prize_pool = total - commission


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
    verification.government_id_asset_id = uuid.UUID(str(government_id_asset_id)) if government_id_asset_id else None
    verification.verification_status = CommunityHostStatus.PENDING
    verification.rejection_reason = None
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

    title = str(payload.get("title") or "").strip()
    game = str(payload.get("game") or "").strip()
    max_players = int(payload.get("max_players") or 0)
    if len(title) < 3 or len(title) > 200:
        raise CommunityValidationError("title must be 3-200 characters")
    if not game:
        raise CommunityValidationError("game is required")
    if max_players <= 0 or max_players > 10000:
        raise CommunityValidationError("max_players must be between 1 and 10000")

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
        banner_asset_id=uuid.UUID(str(payload["banner_asset_id"])) if payload.get("banner_asset_id") else None,
        game=game,
        tournament_type=str(payload.get("tournament_type") or "single_elimination").strip(),
        team_mode=str(payload.get("team_mode") or "solo").strip(),
        entry_fee=entry_fee,
        host_tier=host_tier,
        organizer_commission_rate=organizer_commission_rate,
        currency=str(payload.get("currency") or "INR").strip().upper(),
        max_players=max_players,
        registration_start_at=registration_start_at,
        registration_end_at=registration_end_at,
        tournament_start_at=tournament_start_at,
        tournament_end_at=tournament_end_at,
        rules=str(payload.get("rules") or "").strip() or None,
        prize_distribution=payload.get("prize_distribution") or [],
        discord_link=str(payload.get("discord_link") or "").strip() or None,
        whatsapp_link=str(payload.get("whatsapp_link") or "").strip() or None,
        visibility=bool(payload.get("visibility", True)),
        status=str(payload.get("status") or CommunityTournamentStatus.DRAFT).strip().lower(),
    )
    if tournament.status not in {CommunityTournamentStatus.DRAFT, CommunityTournamentStatus.PUBLISHED}:
        raise CommunityValidationError("new tournament status must be draft or published")
    sync_tournament_status(tournament)
    _recalculate_prize_pool(tournament)
    db.session.add(tournament)
    db.session.flush()
    _audit("tournament_created", "community_tournament", tournament.id, host_user_id)
    db.session.commit()
    return tournament


def update_tournament(host_user_id, tournament_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id)).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    if tournament.status in TERMINAL_STATUSES:
        raise CommunityConflictError("terminal tournaments cannot be edited")

    editable = {
        "title", "description", "banner_url", "game", "tournament_type", "team_mode",
        "rules", "prize_distribution", "discord_link", "whatsapp_link", "room_details",
    }
    for field in editable:
        if field in payload:
            value = payload[field]
            if field in {"title", "game"}:
                value = str(value or "").strip()
                if (field == "title" and not 3 <= len(value) <= 200) or (field == "game" and not value):
                    raise CommunityValidationError(f"{field} is invalid")
            elif field in {"description", "banner_url", "tournament_type", "team_mode", "rules", "discord_link", "whatsapp_link", "room_details"}:
                value = str(value or "").strip() or None
            setattr(tournament, field, value)

    if "banner_asset_id" in payload:
        tournament.banner_asset_id = uuid.UUID(str(payload["banner_asset_id"])) if payload["banner_asset_id"] else None
    if "visibility" in payload:
        if not isinstance(payload["visibility"], bool):
            raise CommunityValidationError("visibility must be a boolean")
        tournament.visibility = payload["visibility"]
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
    if "tournament_end_at" in payload:
        tournament.tournament_end_at = _parse_datetime(payload["tournament_end_at"], "tournament_end_at") if payload["tournament_end_at"] else None
    if "entry_fee" in payload:
        new_fee = _money(payload["entry_fee"], "entry_fee")
        if tournament.registered_players_count > 0:
            raise CommunityConflictError("entry_fee cannot be changed after registrations")
        _require_host_for_paid_tournament(host_user_id, new_fee)
        tournament.entry_fee = new_fee

    if tournament.max_players < tournament.registered_players_count:
        raise CommunityValidationError("max_players cannot be lower than current registrations")
    if tournament.registration_end_at <= tournament.registration_start_at:
        raise CommunityValidationError("registration_end_at must be after registration_start_at")
    if tournament.tournament_start_at < tournament.registration_end_at:
        raise CommunityValidationError("tournament_start_at must be after registration_end_at")
    if tournament.tournament_end_at and tournament.tournament_end_at <= tournament.tournament_start_at:
        raise CommunityValidationError("tournament_end_at must be after tournament_start_at")
    if tournament.room_details and not tournament.room_details_published_at:
        tournament.room_details_published_at = _now()
    sync_tournament_status(tournament)
    _recalculate_prize_pool(tournament)
    _audit("tournament_updated", "community_tournament", tournament.id, host_user_id)
    db.session.commit()
    return tournament


def cancel_tournament(host_user_id, tournament_id, reason=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id, host_user_id=int(host_user_id)).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    if tournament.status == CommunityTournamentStatus.COMPLETED:
        raise CommunityConflictError("completed tournaments cannot be cancelled")
    tournament.status = CommunityTournamentStatus.CANCELLED
    registrations = CommunityTournamentRegistration.query.filter_by(tournament_id=tournament.id, status=CommunityTournamentRegistrationStatus.CONFIRMED).all()
    for reg in registrations:
        reg.status = CommunityTournamentRegistrationStatus.REFUNDED
        reg.payment_status = "refunded"
        reg.cancelled_at = _now()
        if reg.amount_paid:
            _apply_wallet_transaction(reg.user_id, reg.amount_paid, "community-tournament-refund", tournament.id)
        _notify(reg.user_id, "community_tournament_cancelled", "Tournament cancelled", f"{tournament.title} was cancelled. Refund processing has started.", tournament.id)
    _audit("tournament_cancelled", "community_tournament", tournament.id, host_user_id, metadata={"reason": reason})
    db.session.commit()
    return tournament


def list_tournaments(filters):
    page = max(int(filters.get("page") or 1), 1)
    per_page = min(max(int(filters.get("per_page") or filters.get("limit") or 20), 1), 100)
    view = str(filters.get("view") or "").strip().lower()
    search = str(filters.get("search") or "").strip()
    sort = str(filters.get("sort") or "soonest").strip().lower()

    query = CommunityTournament.query.filter(CommunityTournament.visibility.is_(True))
    if view != "admin":
        query = query.filter(CommunityTournament.status.in_(PUBLIC_STATUSES))
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


def get_tournament(tournament_id, requester_user_id=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    db.session.commit()
    include_room = bool(requester_user_id and (int(requester_user_id) == int(tournament.host_user_id) or CommunityTournamentRegistration.query.filter_by(tournament_id=tournament.id, user_id=int(requester_user_id), status=CommunityTournamentRegistrationStatus.CONFIRMED).first()))
    return tournament.to_dict(include_room_details=include_room)


def register_for_tournament(user_id, tournament_id, payment_reference=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    if tournament.status != CommunityTournamentStatus.REGISTRATION_OPEN:
        raise CommunityConflictError("registration is not open")
    if tournament.registered_players_count >= tournament.max_players:
        tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
        raise CommunityConflictError("tournament is full")
    if int(tournament.host_user_id) == int(user_id):
        raise CommunityValidationError("host cannot register for their own tournament")
    user_exists = db.session.query(User.id).filter_by(id=int(user_id)).scalar()
    if not user_exists:
        raise CommunityValidationError("user not found")

    reg = CommunityTournamentRegistration(
        tournament_id=tournament.id,
        user_id=int(user_id),
        status=CommunityTournamentRegistrationStatus.CONFIRMED if tournament.entry_fee == 0 else CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
        payment_status="paid" if tournament.entry_fee == 0 else "pending",
        amount_paid=Decimal("0.00") if tournament.entry_fee == 0 else tournament.entry_fee,
        payment_reference=payment_reference,
    )
    if tournament.entry_fee > 0 and payment_reference:
        reg.status = CommunityTournamentRegistrationStatus.CONFIRMED
        reg.payment_status = "paid"
    db.session.add(reg)
    try:
        db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        raise CommunityConflictError("user is already registered") from exc

    if reg.status == CommunityTournamentRegistrationStatus.CONFIRMED:
        tournament.registered_players_count += 1
        if tournament.entry_fee > 0:
            _apply_wallet_transaction(user_id, -tournament.entry_fee, "community-tournament-entry-fee", tournament.id)
        _recalculate_prize_pool(tournament)
        if tournament.registered_players_count >= tournament.max_players:
            tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
    _audit("registration_created", "community_tournament_registration", reg.id, user_id, metadata={"tournament_id": str(tournament.id)})
    _notify(user_id, "community_registration_success", "Registration received", f"You registered for {tournament.title}.", tournament.id)
    db.session.commit()
    return reg


def record_community_registration_payment(registration_id, status, payment_reference=None):
    """Apply a verified payment-provider result exactly once to a community registration."""
    registration = CommunityTournamentRegistration.query.filter_by(id=registration_id).with_for_update().first()
    if not registration:
        raise CommunityValidationError("community registration not found")
    if registration.status in {CommunityTournamentRegistrationStatus.CANCELLED, CommunityTournamentRegistrationStatus.REFUNDED}:
        raise CommunityConflictError("payment cannot be applied to a cancelled registration")

    if payment_reference:
        registration.payment_reference = str(payment_reference).strip()[:120] or registration.payment_reference
    if status != "succeeded":
        if registration.status == CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
            registration.payment_status = "failed"
            _audit("registration_payment_failed", "community_tournament_registration", registration.id, registration.user_id)
            db.session.commit()
        return registration

    if registration.status == CommunityTournamentRegistrationStatus.CONFIRMED and registration.payment_status == "paid":
        return registration
    if registration.status != CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
        raise CommunityConflictError("registration cannot be confirmed from its current state")

    tournament = CommunityTournament.query.filter_by(id=registration.tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    if tournament.status not in {CommunityTournamentStatus.REGISTRATION_OPEN, CommunityTournamentStatus.REGISTRATION_CLOSED}:
        raise CommunityConflictError("registration is not open")
    if tournament.registered_players_count >= tournament.max_players:
        tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
        raise CommunityConflictError("tournament is full")

    registration.status = CommunityTournamentRegistrationStatus.CONFIRMED
    registration.payment_status = "paid"
    tournament.registered_players_count += 1
    if registration.amount_paid:
        _apply_wallet_transaction(registration.user_id, -registration.amount_paid, "community-tournament-entry-fee", tournament.id)
    _recalculate_prize_pool(tournament)
    if tournament.registered_players_count >= tournament.max_players:
        tournament.status = CommunityTournamentStatus.REGISTRATION_CLOSED
    _audit("registration_payment_confirmed", "community_tournament_registration", registration.id, registration.user_id)
    _notify(registration.user_id, "community_registration_confirmed", "Registration confirmed", f"Your registration for {tournament.title} is confirmed.", tournament.id)
    db.session.commit()
    return registration


def cancel_registration(user_id, tournament_id):
    reg = CommunityTournamentRegistration.query.filter_by(tournament_id=tournament_id, user_id=int(user_id)).with_for_update().first()
    if not reg or reg.status in {CommunityTournamentRegistrationStatus.CANCELLED, CommunityTournamentRegistrationStatus.REFUNDED}:
        raise CommunityValidationError("active registration not found")
    tournament = CommunityTournament.query.filter_by(id=tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    if tournament.status in {CommunityTournamentStatus.LIVE, CommunityTournamentStatus.COMPLETED}:
        raise CommunityConflictError("registration cannot be cancelled after tournament starts")
    reg.status = CommunityTournamentRegistrationStatus.CANCELLED
    reg.cancelled_at = _now()
    if reg.payment_status == "paid" and reg.amount_paid:
        reg.payment_status = "refunded"
        reg.status = CommunityTournamentRegistrationStatus.REFUNDED
        _apply_wallet_transaction(user_id, reg.amount_paid, "community-tournament-refund", tournament.id)
    tournament.registered_players_count = max(0, tournament.registered_players_count - 1)
    _recalculate_prize_pool(tournament)
    sync_tournament_status(tournament)
    _audit("registration_cancelled", "community_tournament_registration", reg.id, user_id)
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
    if action == "confirm_payment":
        if registration.status != CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
            raise CommunityConflictError("only pending-payment registrations can be confirmed")
        if tournament.status not in {CommunityTournamentStatus.REGISTRATION_OPEN, CommunityTournamentStatus.REGISTRATION_CLOSED}:
            raise CommunityConflictError("registration payment can no longer be confirmed")
        if tournament.registered_players_count >= tournament.max_players:
            raise CommunityConflictError("tournament is full")
        if tournament.entry_fee > 0 and not registration.payment_reference:
            raise CommunityValidationError("payment_reference is required to confirm a paid registration")
        registration.status = CommunityTournamentRegistrationStatus.CONFIRMED
        registration.payment_status = "paid"
        tournament.registered_players_count += 1
        if registration.amount_paid:
            _apply_wallet_transaction(registration.user_id, -registration.amount_paid, "community-tournament-entry-fee", tournament.id)
        _recalculate_prize_pool(tournament)
        _notify(registration.user_id, "community_registration_confirmed", "Registration confirmed", f"Your registration for {tournament.title} is confirmed.", tournament.id)
    elif action == "reject_payment":
        if registration.status != CommunityTournamentRegistrationStatus.PENDING_PAYMENT:
            raise CommunityConflictError("only pending-payment registrations can be rejected")
        registration.status = CommunityTournamentRegistrationStatus.CANCELLED
        registration.payment_status = "failed"
        registration.cancelled_at = _now()
        _notify(registration.user_id, "community_registration_rejected", "Registration payment rejected", f"Your registration for {tournament.title} could not be confirmed.", tournament.id)
    elif action in {"check_in", "undo_check_in"}:
        if registration.status != CommunityTournamentRegistrationStatus.CONFIRMED:
            raise CommunityConflictError("only confirmed registrations can be checked in")
        if tournament.status not in {CommunityTournamentStatus.REGISTRATION_CLOSED, CommunityTournamentStatus.LIVE}:
            raise CommunityConflictError("check-in is not available yet")
        registration.checked_in_at = _now() if action == "check_in" else None
    elif action == "remove_participant":
        if tournament.status in {CommunityTournamentStatus.LIVE, CommunityTournamentStatus.COMPLETED, CommunityTournamentStatus.CANCELLED}:
            raise CommunityConflictError("participants cannot be removed after the tournament starts")
        if registration.status not in {CommunityTournamentRegistrationStatus.PENDING_PAYMENT, CommunityTournamentRegistrationStatus.CONFIRMED}:
            raise CommunityConflictError("registration is no longer active")
        if registration.status == CommunityTournamentRegistrationStatus.CONFIRMED:
            tournament.registered_players_count = max(0, tournament.registered_players_count - 1)
        registration.cancelled_at = _now()
        if registration.payment_status == "paid" and registration.amount_paid:
            registration.status = CommunityTournamentRegistrationStatus.REFUNDED
            registration.payment_status = "refunded"
            _apply_wallet_transaction(registration.user_id, registration.amount_paid, "community-tournament-refund", tournament.id)
        else:
            registration.status = CommunityTournamentRegistrationStatus.CANCELLED
        _recalculate_prize_pool(tournament)
        _notify(registration.user_id, "community_registration_removed", "Registration cancelled", f"Your registration for {tournament.title} was cancelled by the host.", tournament.id)
    else:
        raise CommunityValidationError("action must be confirm_payment, reject_payment, check_in, undo_check_in, or remove_participant")

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
        _apply_wallet_transaction(payout.user_id, payout.amount, "community-tournament-prize", payout.tournament_id)
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
        evidence_asset_ids=payload.get("evidence_asset_ids") or [],
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
    dispute = CommunityTournamentDispute(
        tournament_id=tournament.id,
        result_id=uuid.UUID(str(payload["result_id"])) if payload.get("result_id") else None,
        reported_by_user_id=int(user_id),
        reason=reason,
        description=description,
        evidence_asset_ids=payload.get("evidence_asset_ids") or [],
    )
    db.session.add(dispute)
    db.session.flush()
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
                status=CommunityPayoutStatus.PENDING_ADMIN_APPROVAL,
            )
        )
    tournament.status = CommunityTournamentStatus.COMPLETED
    _audit("winners_submitted", "community_tournament", tournament.id, host_user_id, metadata={"winner_count": len(winners)})
    db.session.commit()
    return CommunityTournamentPayout.query.filter_by(tournament_id=tournament.id).order_by(CommunityTournamentPayout.rank.asc()).all()


def create_file_asset(user_id, payload):
    purpose = str(payload.get("purpose") or "").strip()
    file_url = str(payload.get("file_url") or "").strip()
    if not purpose or not file_url:
        raise CommunityValidationError("purpose and file_url are required")
    asset = CommunityFileAsset(
        owner_user_id=int(user_id),
        tournament_id=uuid.UUID(str(payload["tournament_id"])) if payload.get("tournament_id") else None,
        purpose=purpose,
        file_url=file_url,
        storage_key=str(payload.get("storage_key") or "").strip() or None,
        mime_type=str(payload.get("mime_type") or "").strip() or None,
        file_size_bytes=int(payload["file_size_bytes"]) if payload.get("file_size_bytes") is not None else None,
        checksum=str(payload.get("checksum") or "").strip() or None,
        meta=payload.get("metadata") or {},
    )
    db.session.add(asset)
    db.session.flush()
    _audit("file_asset_created", "community_file_asset", asset.id, user_id)
    db.session.commit()
    return asset
