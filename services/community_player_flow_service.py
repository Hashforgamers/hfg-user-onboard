"""Player-facing aggregate reads and finalization previews for community UI."""

from services.community_idempotency_service import commit_community
import uuid
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import or_
from db.extensions import db
from models.communityTournament import (
    CommunityTournament,
    CommunityTournamentRegistration,
)
from models.communityTournamentOperations import (
    CommunityTournamentTeam,
    CommunityTournamentTeamMember,
    CommunityTournamentMatch,
    CommunityTournamentDispute,
    CommunityTournamentPayout,
)
from services.community_access_service import (
    eligible_memberships,
    eligible_participant,
    match_team_ids,
)
from services.community_tournament_service import (
    CommunityValidationError,
    CommunityForbiddenError,
    CommunityConflictError,
    _now,
    _pagination,
    _owned_tournament,
    _audit,
    get_tournament,
)


def page_payload(query, filters, serialize=lambda row: row.to_dict()):
    try:
        page, per_page = _pagination(filters)
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("page and per_page must be integers") from exc
    total = query.count()
    return {
        "items": [
            serialize(row)
            for row in query.offset((page - 1) * per_page).limit(per_page).all()
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }


def my_invitations(user_id, filters):
    query = CommunityTournamentTeamMember.query.filter_by(
        user_id=int(user_id), verification_status="invited"
    )

    def serialize(member):
        team = CommunityTournamentTeam.query.filter_by(id=member.team_id).first()
        tournament = CommunityTournament.query.filter_by(
            id=member.tournament_id
        ).first()
        now = _now()
        can_respond = bool(
            team
            and tournament
            and team.status not in {"rejected", "disqualified"}
            and tournament.status not in {"live", "completed", "cancelled", "draft"}
            and now < tournament.tournament_start_at
            and not team.roster_locked_at
            and (not tournament.roster_lock_at or now < tournament.roster_lock_at)
        )
        return {
            **member.to_dict(),
            "tournament_id": str(member.tournament_id),
            "tournament_title": tournament.title if tournament else None,
            "team_name": team.name if team else None,
            "can_respond": can_respond,
        }

    return page_payload(
        query.order_by(CommunityTournamentTeamMember.joined_at.desc()),
        filters,
        serialize,
    )


def my_matches(user_id, tournament_id, filters):
    from services.community_tournament_control_service import _match_payload

    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    ids = {str(m.team_id) for m in eligible_memberships(tournament_id, user_id)}
    query = CommunityTournamentMatch.query.filter_by(tournament_id=tournament_id)
    if filters.get("status"):
        query = query.filter_by(status=filters["status"])
    matches = query.order_by(
        CommunityTournamentMatch.scheduled_at.asc().nullslast(),
        CommunityTournamentMatch.round_number,
        CommunityTournamentMatch.match_number,
    ).all()
    return {
        "items": [
            _match_payload(match) for match in matches if ids & match_team_ids(match)
        ]
    }


def check_in_blocker(tournament, registration, team, user_id, now):
    if tournament.status in {"draft", "published", "completed", "cancelled"}:
        return "check-in is unavailable in this tournament state"
    if tournament.check_in_start_at and now < tournament.check_in_start_at:
        return "check-in has not opened"
    if tournament.check_in_end_at and now > tournament.check_in_end_at:
        return "check-in has closed"
    if not tournament.check_in_start_at and tournament.status != "registration_closed":
        return "close registration or configure a check-in window first"
    if team:
        if int(team.captain_user_id) != int(user_id):
            return "only the captain can check in the team"
        if team.status != "approved":
            return "only approved teams can check in"
    elif tournament.team_mode != "solo":
        return "create and approve a team before checking in"
    if not registration or registration.status != "confirmed":
        return "confirmed registration is required"
    return None


def self_check_in(user_id, tournament_id):
    from services.community_tournament_service import sync_tournament_status

    tournament = (
        CommunityTournament.query.filter_by(id=tournament_id).with_for_update().first()
    )
    if not tournament:
        raise CommunityValidationError("tournament not found")
    sync_tournament_status(tournament)
    registration = (
        CommunityTournamentRegistration.query.filter_by(
            tournament_id=tournament_id, user_id=int(user_id), status="confirmed"
        )
        .with_for_update()
        .first()
    )
    team = (
        CommunityTournamentTeam.query.filter_by(
            tournament_id=tournament_id, captain_user_id=int(user_id)
        )
        .with_for_update()
        .first()
    )
    blocker = check_in_blocker(tournament, registration, team, user_id, _now())
    if blocker:
        raise CommunityConflictError(blocker)
    now = _now()
    registration.checked_in_at = registration.checked_in_at or now
    if team:
        team.checked_in_at = team.checked_in_at or registration.checked_in_at
    _audit(
        "participant_checked_in",
        "community_tournament_registration",
        registration.id,
        user_id,
    )
    commit_community(db.session)
    return {
        "registration": registration.to_dict(),
        "team": team.to_dict() if team else None,
    }


def my_tournament(user_id, tournament_id, invite_code=None):
    from services.community_tournament_control_service import _team_payload

    detail = get_tournament(tournament_id, user_id, invite_code)
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    registration = (
        CommunityTournamentRegistration.query.filter_by(
            tournament_id=tournament_id, user_id=int(user_id)
        )
        .order_by(CommunityTournamentRegistration.created_at.desc())
        .first()
    )
    memberships = CommunityTournamentTeamMember.query.filter_by(
        tournament_id=tournament_id, user_id=int(user_id)
    ).all()
    member = next(
        (m for m in memberships if m.verification_status in {"accepted", "verified"}),
        None,
    )
    team = (
        CommunityTournamentTeam.query.filter_by(id=member.team_id).first()
        if member
        else None
    )
    matches = my_matches(user_id, tournament_id, {})["items"]
    current = next(
        (m for m in matches if m["status"] not in {"completed", "cancelled"}), None
    )
    is_host = int(tournament.host_user_id) == int(user_id)
    active = registration and registration.status in {
        "pending_payment",
        "confirmed",
        "refund_pending",
    }
    return {
        "tournament": detail,
        "registration": registration.to_dict() if registration else None,
        "team": _team_payload(team) if team else None,
        "invitations": [
            m.to_dict() for m in memberships if m.verification_status == "invited"
        ],
        "current_match": current,
        "matches": matches,
        "server_time": _now().isoformat(),
        "actions": {
            "can_manage": is_host,
            "can_join": not is_host
            and not active
            and tournament.status == "registration_open"
            and tournament.registered_players_count < tournament.max_players,
            "can_continue_payment": bool(
                registration
                and registration.status == "pending_payment"
                and tournament.status == "registration_open"
            ),
            "can_check_in": not is_host
            and check_in_blocker(tournament, registration, team, user_id, _now())
            is None,
            "can_cancel_registration": bool(
                active and tournament.status not in {"live", "completed"}
            ),
            "can_view_match": bool(current),
            "can_play": bool(
                current
                and current["status"] == "in_progress"
                and eligible_participant(tournament_id, user_id)
            ),
        },
    }


def _visible_disputes(user_id):
    # Accepted members retain access to their case history after an event ends.
    team_ids = [
        str(m.team_id)
        for m in CommunityTournamentTeamMember.query.filter_by(user_id=int(user_id))
        .filter(
            CommunityTournamentTeamMember.verification_status.in_(
                {"accepted", "verified"}
            )
        )
        .all()
    ]
    matches = (
        CommunityTournamentMatch.query.filter(
            or_(
                CommunityTournamentMatch.team_a_id.in_(team_ids),
                CommunityTournamentMatch.team_b_id.in_(team_ids),
                *[
                    CommunityTournamentMatch.participant_team_ids.contains([tid])
                    for tid in team_ids
                ]
            )
        ).all()
        if team_ids
        else []
    )
    hosted = CommunityTournament.query.with_entities(CommunityTournament.id).filter_by(
        host_user_id=int(user_id)
    )
    return CommunityTournamentDispute.query.filter(
        or_(
            CommunityTournamentDispute.reported_by_user_id == int(user_id),
            CommunityTournamentDispute.tournament_id.in_(hosted),
            CommunityTournamentDispute.match_id.in_([m.id for m in matches]),
        )
    )


def my_disputes(user_id, filters):
    query = _visible_disputes(user_id)
    if filters.get("status"):
        query = query.filter_by(status=filters["status"])
    return page_payload(
        query.order_by(CommunityTournamentDispute.created_at.desc()), filters
    )


def dispute_detail(user_id, dispute_id):
    dispute = (
        _visible_disputes(user_id)
        .filter(CommunityTournamentDispute.id == dispute_id)
        .first()
    )
    if not dispute:
        raise CommunityForbiddenError("dispute is not accessible to this user")
    return dispute.to_dict()


def my_payouts(user_id, filters):
    query = CommunityTournamentPayout.query.filter_by(user_id=int(user_id))
    if filters.get("status"):
        query = query.filter_by(status=filters["status"])
    return page_payload(
        query.order_by(CommunityTournamentPayout.created_at.desc()),
        filters,
        lambda p: {**p.to_dict(), "destination": "hash_wallet"},
    )


def resolve_winner_payee(tournament, winner):
    """Team awards go to their confirmed captain's Hash wallet; never implicit splits."""
    team = None
    if winner.get("team_id"):
        try:
            team_id = uuid.UUID(str(winner["team_id"]))
        except (ValueError, TypeError) as exc:
            raise CommunityValidationError("team_id must be a UUID") from exc
        team = CommunityTournamentTeam.query.filter_by(
            id=team_id, tournament_id=tournament.id, status="approved"
        ).first()
        if not team:
            raise CommunityValidationError(
                "winner team must be approved in this tournament"
            )
        if winner.get("user_id") is not None and int(winner["user_id"]) != int(
            team.captain_user_id
        ):
            raise CommunityValidationError("team award payee must be its captain")
        user_id = int(team.captain_user_id)
    else:
        try:
            user_id = int(winner["user_id"])
        except (KeyError, ValueError, TypeError) as exc:
            raise CommunityValidationError(
                "winner requires user_id or team_id"
            ) from exc
        if tournament.team_mode != "solo":
            team = CommunityTournamentTeam.query.filter_by(
                tournament_id=tournament.id, captain_user_id=user_id, status="approved"
            ).first()
            if not team:
                raise CommunityValidationError(
                    "team prizes must be assigned to an approved team captain"
                )
    registration = CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament.id, user_id=user_id, status="confirmed"
    ).first()
    if not registration or (team and team.registration_id != registration.id):
        raise CommunityValidationError(
            "winner payee must own the confirmed registration"
        )
    return user_id, team


def finalization_preview(host_user_id, tournament_id):
    tournament = _owned_tournament(host_user_id, tournament_id)
    from services.community_tournament_service import sync_tournament_status

    sync_tournament_status(tournament)
    blockers, unfinished, disputes, payouts = finalization_conditions(tournament)
    registrations = CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament_id, status="confirmed"
    ).all()
    teams = CommunityTournamentTeam.query.filter_by(
        tournament_id=tournament_id, status="approved"
    ).all()
    eligible = [
        {"team_id": str(t.id), "team_name": t.name, "user_id": int(t.captain_user_id)}
        for t in teams
        if any(
            r.id == t.registration_id and int(r.user_id) == int(t.captain_user_id)
            for r in registrations
        )
    ]
    if tournament.team_mode == "solo":
        eligible = [
            {
                "user_id": int(r.user_id),
                "team_id": next(
                    (str(t.id) for t in teams if t.registration_id == r.id), None
                ),
            }
            for r in registrations
        ]
    if not eligible:
        blockers.append("No eligible award recipients.")
    pool = Decimal(str(tournament.prize_pool or 0))
    awards = [
        {
            "rank": int(d.get("rank") or i + 1),
            "amount": float(
                (pool * Decimal(str(d.get("percent") or 0)) / 100).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            ),
        }
        for i, d in enumerate(tournament.prize_distribution or [])
    ]
    return {
        "ready_to_finalize": not blockers,
        "blockers": blockers,
        "unfinished_matches": [m.to_dict() for m in unfinished],
        "open_disputes": [d.to_dict() for d in disputes],
        "eligible_payees": eligible,
        "proposed_awards": awards,
        "requires_winner_selection": True,
        "prize_pool": float(pool),
        "proposed_prize_total": sum(a["amount"] for a in awards),
        "organizer_commission": float(tournament.organizer_commission_amount or 0),
        "currency": tournament.currency,
        "payout_policy": "captain" if tournament.team_mode != "solo" else "individual",
        "destination": "hash_wallet",
        "existing_payouts": [p.to_dict() for p in payouts],
    }


def finalization_conditions(tournament):
    matches = CommunityTournamentMatch.query.filter_by(
        tournament_id=tournament.id
    ).all()
    disputes = (
        CommunityTournamentDispute.query.filter_by(tournament_id=tournament.id)
        .filter(CommunityTournamentDispute.status.in_({"open", "under_review"}))
        .all()
    )
    unfinished = [m for m in matches if m.status not in {"completed", "cancelled"}]
    payouts = CommunityTournamentPayout.query.filter_by(
        tournament_id=tournament.id
    ).all()
    blockers = []
    if tournament.status not in {"live", "completed"}:
        blockers.append("Tournament must be live before finalization.")
    if unfinished:
        blockers.append("Finish or cancel every match before finalization.")
    if disputes:
        blockers.append("Resolve every open dispute before finalization.")
    if payouts:
        blockers.append("Winners have already been submitted.")
    return blockers, unfinished, disputes, payouts
