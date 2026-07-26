from datetime import timedelta
from decimal import Decimal
import hmac
import math
import uuid
from urllib.parse import urlparse

from sqlalchemy import func, or_

from db.extensions import db
from models.communityTournament import (
    CommunityHostStatus,
    CommunityHostVerification,
    CommunityTournament,
    CommunityTournamentRegistration,
    CommunityTournamentRegistrationStatus,
    CommunityTournamentStatus,
)
from models.communityTournamentOperations import (
    CommunityAuditLog,
    CommunityDisputeStatus,
    CommunityMatchResultSubmission,
    CommunityMatchResultProposal,
    CommunityMatchStatus,
    CommunityTeamStatus,
    CommunityTournamentAnnouncement,
    CommunityTournamentDispute,
    CommunityTournamentMatch,
    CommunityTournamentPayout,
    CommunityTournamentReview,
    CommunityTournamentTeam,
    CommunityTournamentTeamMember,
)
from models.user import User
from services.community_tournament_service import (
    CommunityConflictError,
    CommunityForbiddenError,
    CommunityValidationError,
    _audit,
    _gamer_summaries,
    _invite_code_hash,
    _notify,
    _now,
    _owned_tournament,
    _pagination,
    _validated_evidence_asset_ids,
    _refund_or_cancel_registration,
    sync_tournament_status,
)


def _require_private_access(tournament, invite_code=None):
    if not tournament.is_private:
        return
    supplied = _invite_code_hash(invite_code or "")
    if not tournament.invite_code_hash or not hmac.compare_digest(tournament.invite_code_hash, supplied):
        raise CommunityForbiddenError("a valid tournament invite code is required")


def _registration_for_user(tournament_id, user_id, lock=False):
    query = CommunityTournamentRegistration.query.filter(
        CommunityTournamentRegistration.tournament_id == tournament_id,
        CommunityTournamentRegistration.user_id == int(user_id),
        CommunityTournamentRegistration.status.in_({
            CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
            CommunityTournamentRegistrationStatus.CONFIRMED,
        }),
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def _team_payload(team, include_members=True):
    payload = team.to_dict()
    if include_members:
        members = CommunityTournamentTeamMember.query.filter_by(team_id=team.id).order_by(
            CommunityTournamentTeamMember.role.asc(),
            CommunityTournamentTeamMember.joined_at.asc(),
        ).all()
        gamers = _gamer_summaries(member.user_id for member in members)
        payload["members"] = [
            {**member.to_dict(), "gamer": gamers.get(int(member.user_id))}
            for member in members
        ]
    return payload


def _validate_roster(tournament, captain_user_id, members):
    if not isinstance(members, list):
        raise CommunityValidationError("members must be a list")
    maximum = int(tournament.team_size or 1) + int(tournament.substitute_limit or 0)
    if len(members) > maximum:
        raise CommunityValidationError(f"roster cannot exceed {maximum} members including substitutes")
    normalized = []
    seen_users = set()
    for raw in members:
        try:
            user_id = int(raw["user_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CommunityValidationError("each roster member requires a valid user_id") from exc
        game_id = str(raw.get("game_id") or "").strip()
        role = str(raw.get("role") or "player").strip().lower()
        if role not in {"captain", "player", "substitute"}:
            raise CommunityValidationError("member role must be captain, player, or substitute")
        if not game_id:
            raise CommunityValidationError("each roster member requires a game_id")
        if user_id in seen_users:
            raise CommunityValidationError("a user can appear only once in a roster")
        seen_users.add(user_id)
        normalized.append({"user_id": user_id, "game_id": game_id, "role": role})
    if int(captain_user_id) not in seen_users:
        user = User.query.filter_by(id=int(captain_user_id)).first()
        normalized.insert(0, {
            "user_id": int(captain_user_id),
            "game_id": str(getattr(user, "game_username", "") or captain_user_id),
            "role": "captain",
        })
        seen_users.add(int(captain_user_id))
    for member in normalized:
        member["role"] = "captain" if member["user_id"] == int(captain_user_id) else member["role"]
    if len(normalized) > maximum:
        raise CommunityValidationError(f"roster cannot exceed {maximum} members including substitutes")
    existing_users = {int(row.id) for row in User.query.with_entities(User.id).filter(User.id.in_(seen_users)).all()}
    if existing_users != seen_users:
        raise CommunityValidationError("one or more roster users do not exist")
    return normalized


def _automatic_team_ready(tournament, registration, members):
    active_players = [member for member in members if member.role != "substitute"]
    return (
        tournament.registration_policy in {"automatic", "payment"}
        and registration.status == CommunityTournamentRegistrationStatus.CONFIRMED
        and len(active_players) == int(tournament.team_size or 1)
        and all(member.verification_status in {"accepted", "verified"} for member in members)
    )


def create_team(user_id, tournament_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).with_for_update().first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    registration = _registration_for_user(tournament.id, user_id, lock=True)
    if not registration:
        raise CommunityForbiddenError("an active tournament registration is required")
    if CommunityTournamentTeam.query.filter_by(registration_id=registration.id).first():
        raise CommunityConflictError("this registration already has a team")
    accepted_team = CommunityTournamentTeamMember.query.filter(
        CommunityTournamentTeamMember.tournament_id == tournament.id,
        CommunityTournamentTeamMember.user_id == int(user_id),
        CommunityTournamentTeamMember.verification_status.in_({"accepted", "verified"}),
    ).first()
    if accepted_team:
        raise CommunityConflictError("you already belong to another accepted team in this tournament")
    if tournament.roster_lock_at and _now() >= tournament.roster_lock_at:
        raise CommunityConflictError("rosters are locked")

    name = str(payload.get("name") or payload.get("team_name") or "").strip()
    if tournament.team_mode == "solo" and not name:
        gamer = User.query.filter_by(id=int(user_id)).first()
        name = str(getattr(gamer, "game_username", None) or getattr(gamer, "name", None) or f"Player {user_id}")
    if not 2 <= len(name) <= 120:
        raise CommunityValidationError("team name must be 2-120 characters")
    roster = _validate_roster(tournament, user_id, payload.get("members") or [])
    team = CommunityTournamentTeam(
        tournament_id=tournament.id,
        registration_id=registration.id,
        captain_user_id=int(user_id),
        name=name,
        status=CommunityTeamStatus.PENDING,
    )
    db.session.add(team)
    db.session.flush()
    for member in roster:
        row = CommunityTournamentTeamMember(
            tournament_id=tournament.id,
            team_id=team.id,
            verification_status="verified" if member["user_id"] == int(user_id) else "invited",
            **member,
        )
        db.session.add(row)
        if member["user_id"] != int(user_id):
            _notify(
                member["user_id"],
                "community_team_invitation",
                "Tournament team invitation",
                f"You were invited to join {name}.",
                tournament.id,
            )
    db.session.flush()
    created_members = CommunityTournamentTeamMember.query.filter_by(team_id=team.id).all()
    if _automatic_team_ready(tournament, registration, created_members):
        team.status = CommunityTeamStatus.APPROVED
    _audit("community_team_created", "community_tournament_team", team.id, user_id)
    db.session.commit()
    return _team_payload(team)


def replace_team_roster(user_id, tournament_id, team_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    team = CommunityTournamentTeam.query.filter_by(id=team_id, tournament_id=tournament_id).with_for_update().first()
    if not tournament or not team:
        raise CommunityValidationError("team not found")
    if int(team.captain_user_id) != int(user_id):
        raise CommunityForbiddenError("only the team captain can edit the roster")
    if team.roster_locked_at or (tournament.roster_lock_at and _now() >= tournament.roster_lock_at):
        raise CommunityConflictError("roster is locked")
    roster = _validate_roster(tournament, team.captain_user_id, payload.get("members"))
    CommunityTournamentTeamMember.query.filter_by(team_id=team.id).delete(synchronize_session=False)
    for member in roster:
        db.session.add(CommunityTournamentTeamMember(
            tournament_id=tournament.id,
            team_id=team.id,
            verification_status="verified" if member["user_id"] == int(team.captain_user_id) else "invited",
            **member,
        ))
        if member["user_id"] != int(team.captain_user_id):
            _notify(
                member["user_id"],
                "community_team_invitation",
                "Tournament team invitation",
                f"You were invited to join {team.name}.",
                tournament.id,
            )
    if payload.get("name") is not None:
        name = str(payload["name"] or "").strip()
        if not 2 <= len(name) <= 120:
            raise CommunityValidationError("team name must be 2-120 characters")
        team.name = name
    team.status = CommunityTeamStatus.PENDING
    db.session.flush()
    registration = CommunityTournamentRegistration.query.filter_by(id=team.registration_id).first()
    current_members = CommunityTournamentTeamMember.query.filter_by(team_id=team.id).all()
    if registration and _automatic_team_ready(tournament, registration, current_members):
        team.status = CommunityTeamStatus.APPROVED
    _audit("community_team_roster_updated", "community_tournament_team", team.id, user_id)
    db.session.commit()
    return _team_payload(team)


def respond_team_invitation(user_id, tournament_id, team_id, payload):
    member = CommunityTournamentTeamMember.query.filter_by(
        tournament_id=tournament_id,
        team_id=team_id,
        user_id=int(user_id),
    ).with_for_update().first()
    if not member:
        raise CommunityValidationError("team invitation not found")
    if member.role == "captain":
        raise CommunityConflictError("the captain cannot decline their own team")
    action = str(payload.get("action") or "").strip().lower()
    if action == "accept":
        accepted_elsewhere = CommunityTournamentTeamMember.query.filter(
            CommunityTournamentTeamMember.tournament_id == tournament_id,
            CommunityTournamentTeamMember.user_id == int(user_id),
            CommunityTournamentTeamMember.team_id != team_id,
            CommunityTournamentTeamMember.verification_status.in_({"accepted", "verified"}),
        ).first()
        if accepted_elsewhere:
            raise CommunityConflictError("you already belong to another accepted team in this tournament")
        member.verification_status = "accepted"
    elif action == "decline":
        db.session.delete(member)
    else:
        raise CommunityValidationError("action must be accept or decline")
    team = CommunityTournamentTeam.query.filter_by(id=team_id).first()
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    registration = CommunityTournamentRegistration.query.filter_by(id=team.registration_id).first()
    if action == "decline":
        team.status = CommunityTeamStatus.PENDING
    else:
        db.session.flush()
        members = CommunityTournamentTeamMember.query.filter_by(team_id=team.id).all()
        if _automatic_team_ready(tournament, registration, members):
            team.status = CommunityTeamStatus.APPROVED
    _audit(f"community_team_invitation_{action}", "community_tournament_team", team_id, user_id)
    db.session.commit()
    return _team_payload(team)


def list_teams(tournament_id, filters, requester_user_id=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    page, per_page = _pagination(filters)
    query = CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id)
    if requester_user_id is None:
        _require_private_access(tournament, filters.get("invite_code"))
        query = query.filter_by(status=CommunityTeamStatus.APPROVED)
        is_host = False
    else:
        is_host = int(requester_user_id) == int(tournament.host_user_id)
        registration = _registration_for_user(tournament.id, requester_user_id)
        membership = CommunityTournamentTeamMember.query.filter_by(
            tournament_id=tournament.id,
            user_id=int(requester_user_id),
        ).first()
        if tournament.is_private and not is_host and not registration and not membership:
            _require_private_access(tournament, filters.get("invite_code"))
        if not is_host:
            query = query.filter(or_(
                CommunityTournamentTeam.status == CommunityTeamStatus.APPROVED,
                CommunityTournamentTeam.captain_user_id == int(requester_user_id),
            ))
    status = str(filters.get("status") or "").strip().lower()
    if status and requester_user_id is not None:
        if status not in {
            CommunityTeamStatus.PENDING,
            CommunityTeamStatus.APPROVED,
            CommunityTeamStatus.REJECTED,
            CommunityTeamStatus.DISQUALIFIED,
        }:
            raise CommunityValidationError("invalid team status")
        query = query.filter_by(status=status)
    total = query.count()
    teams = query.order_by(
        CommunityTournamentTeam.seed_number.asc().nullslast(),
        CommunityTournamentTeam.created_at.asc(),
    ).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [
            _team_payload(
                team,
                include_members=bool(
                    requester_user_id
                    and (is_host or int(team.captain_user_id) == int(requester_user_id))
                ),
            )
            for team in teams
        ],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def manage_team(host_user_id, tournament_id, team_id, payload):
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    team = CommunityTournamentTeam.query.filter_by(id=team_id, tournament_id=tournament.id).with_for_update().first()
    if not team:
        raise CommunityValidationError("team not found")
    action = str(payload.get("action") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip() or None
    members = CommunityTournamentTeamMember.query.filter_by(team_id=team.id).all()
    player_count = sum(1 for member in members if member.role != "substitute")

    if action == "approve":
        if player_count != int(tournament.team_size or 1):
            raise CommunityConflictError("team must have the required number of active players before approval")
        if any(member.verification_status not in {"accepted", "verified"} for member in members):
            raise CommunityConflictError("all players and substitutes must accept their roster invitations before approval")
        registration = CommunityTournamentRegistration.query.filter_by(id=team.registration_id).first()
        if not registration or registration.status != CommunityTournamentRegistrationStatus.CONFIRMED:
            raise CommunityConflictError("team payment/registration is not confirmed")
        team.status = CommunityTeamStatus.APPROVED
        for member in members:
            member.verification_status = "verified"
    elif action == "reject":
        if not reason:
            raise CommunityValidationError("reason is required")
        team.status = CommunityTeamStatus.REJECTED
        team.rejection_reason = reason
    elif action == "request_information":
        if not reason:
            raise CommunityValidationError("reason is required")
        team.status = CommunityTeamStatus.PENDING
        team.rejection_reason = reason
    elif action == "lock_roster":
        team.roster_locked_at = _now()
    elif action == "check_in":
        now = _now()
        if tournament.check_in_start_at and now < tournament.check_in_start_at:
            raise CommunityConflictError("check-in has not opened")
        if tournament.check_in_end_at and now > tournament.check_in_end_at:
            raise CommunityConflictError("check-in has closed")
        if team.status != CommunityTeamStatus.APPROVED:
            raise CommunityConflictError("only approved teams can check in")
        team.checked_in_at = now
    elif action == "undo_check_in":
        team.checked_in_at = None
    elif action == "seed":
        team.seed_number = int(payload.get("seed_number") or 0)
        if team.seed_number <= 0:
            raise CommunityValidationError("seed_number must be positive")
    elif action == "warn":
        if not reason:
            raise CommunityValidationError("reason is required")
        team.warning_count = int(team.warning_count or 0) + 1
    elif action == "disqualify":
        if not reason:
            raise CommunityValidationError("reason is required")
        team.status = CommunityTeamStatus.DISQUALIFIED
        team.disqualification_reason = reason
    elif action == "refund":
        registration = CommunityTournamentRegistration.query.filter_by(id=team.registration_id).with_for_update().first()
        if not registration:
            raise CommunityValidationError("team registration not found")
        _refund_or_cancel_registration(registration, tournament)
        team.status = CommunityTeamStatus.REJECTED
        team.rejection_reason = reason or "Refunded by host"
    else:
        raise CommunityValidationError("unsupported team action")

    _audit(
        f"community_team_{action}",
        "community_tournament_team",
        team.id,
        host_user_id,
        metadata={"reason": reason, "seed_number": team.seed_number},
    )
    _notify(team.captain_user_id, "community_team_updated", "Team registration updated", f"{team.name}: {action.replace('_', ' ')}.", tournament.id)
    db.session.commit()
    return _team_payload(team)


def _ensure_solo_teams(tournament):
    registrations = CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament.id,
        status=CommunityTournamentRegistrationStatus.CONFIRMED,
    ).all()
    existing_registration_ids = {
        team.registration_id
        for team in CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id).all()
    }
    gamers = _gamer_summaries(reg.user_id for reg in registrations)
    for registration in registrations:
        if registration.id in existing_registration_ids:
            continue
        gamer = gamers.get(int(registration.user_id)) or {}
        team = CommunityTournamentTeam(
            id=uuid.uuid4(),
            tournament_id=tournament.id,
            registration_id=registration.id,
            captain_user_id=registration.user_id,
            name=gamer.get("game_username") or gamer.get("display_name") or f"Player {registration.user_id}",
            status=CommunityTeamStatus.APPROVED,
        )
        db.session.add(team)
        db.session.flush()
        db.session.add(CommunityTournamentTeamMember(
            tournament_id=tournament.id,
            team_id=team.id,
            user_id=registration.user_id,
            role="captain",
            game_id=gamer.get("game_username") or str(registration.user_id),
            verification_status="verified",
        ))


def _next_power_of_two(value):
    return 1 if value <= 1 else 2 ** math.ceil(math.log2(value))


def _seed_pairs(teams, bracket_size):
    bye_count = bracket_size - len(teams)
    pairs = []
    team_index = 0
    for _ in range(bye_count):
        pairs.append((teams[team_index], None))
        team_index += 1
    while team_index < len(teams):
        pairs.append((teams[team_index], teams[team_index + 1]))
        team_index += 2
    return pairs


def _schedule_time(tournament, index):
    spacing = int(tournament.match_duration_minutes or 45) + int(tournament.break_duration_minutes or 15)
    concurrent = max(int((tournament.schedule_config or {}).get("concurrent_matches") or 1), 1)
    return tournament.tournament_start_at + timedelta(minutes=(index // concurrent) * spacing)


def _schedule_bracket_rounds(tournament, rounds):
    """Schedule playable matches by round; automatic byes take no time slot."""
    spacing = int(tournament.match_duration_minutes or 45) + int(tournament.break_duration_minutes or 15)
    concurrent = max(int((tournament.schedule_config or {}).get("concurrent_matches") or 1), 1)
    round_start = tournament.tournament_start_at

    for round_number in sorted(rounds):
        playable_matches = [
            match for match in rounds[round_number]
            if match.status != CommunityMatchStatus.COMPLETED
        ]
        for index, match in enumerate(playable_matches):
            match.scheduled_at = round_start + timedelta(minutes=(index // concurrent) * spacing)
        if playable_matches:
            slots = math.ceil(len(playable_matches) / concurrent)
            round_start += timedelta(minutes=slots * spacing)


def _auto_check_in_teams(teams, now=None):
    """Mark bracket entrants checked in and keep registration reporting aligned."""
    check_in_time = now or _now()
    registration_ids = [team.registration_id for team in teams]
    registrations = CommunityTournamentRegistration.query.filter(
        CommunityTournamentRegistration.id.in_(registration_ids)
    ).all()
    registrations_by_id = {registration.id: registration for registration in registrations}
    auto_checked_in = 0
    for team in teams:
        if team.checked_in_at is not None:
            continue
        team.checked_in_at = check_in_time
        registration = registrations_by_id.get(team.registration_id)
        if registration and registration.checked_in_at is None:
            registration.checked_in_at = check_in_time
        auto_checked_in += 1
    return auto_checked_in


def start_tournament(host_user_id, tournament_id):
    """Start a bracket-ready tournament before its scheduled start time."""
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    now = _now()
    sync_tournament_status(tournament, now)
    if tournament.status == CommunityTournamentStatus.LIVE:
        return tournament
    if tournament.status != CommunityTournamentStatus.REGISTRATION_CLOSED:
        raise CommunityConflictError("registration must be closed before the tournament can start")
    if not CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).first():
        raise CommunityConflictError("generate or create matches before starting the tournament")
    if tournament.tournament_end_at and now >= tournament.tournament_end_at:
        raise CommunityConflictError("the scheduled tournament end time has already passed")

    # Move the scheduled start to now so future time-based syncs preserve live status.
    tournament.tournament_start_at = now
    tournament.status = CommunityTournamentStatus.LIVE
    _audit("community_tournament_started_manually", "community_tournament", tournament.id, host_user_id)
    _notify(
        tournament.host_user_id,
        "community_tournament_started",
        "Tournament is live",
        f"{tournament.title} has started.",
        tournament.id,
    )
    db.session.commit()
    return tournament


def generate_matches(host_user_id, tournament_id):
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    sync_tournament_status(tournament)
    if tournament.status not in {CommunityTournamentStatus.REGISTRATION_CLOSED, CommunityTournamentStatus.LIVE}:
        raise CommunityConflictError("matches can be generated only after registration closes")
    if CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).first():
        raise CommunityConflictError("matches have already been generated")
    if tournament.team_mode == "solo":
        _ensure_solo_teams(tournament)
        db.session.flush()
    teams = CommunityTournamentTeam.query.filter_by(
        tournament_id=tournament.id,
        status=CommunityTeamStatus.APPROVED,
    ).order_by(
        CommunityTournamentTeam.seed_number.asc().nullslast(),
        CommunityTournamentTeam.created_at.asc(),
    ).all()
    if len(teams) < max(int(tournament.min_entries or 2), 2):
        raise CommunityConflictError("not enough approved entries to generate matches")
    auto_checked_in = _auto_check_in_teams(teams)

    if tournament.tournament_type in {"round_robin", "league"}:
        pairs = [(teams[left], teams[right]) for left in range(len(teams)) for right in range(left + 1, len(teams))]
        for index, (team_a, team_b) in enumerate(pairs):
            db.session.add(CommunityTournamentMatch(
                tournament_id=tournament.id,
                stage="league",
                round_number=1,
                match_number=index + 1,
                status=CommunityMatchStatus.READY,
                team_a_id=team_a.id,
                team_b_id=team_b.id,
                scheduled_at=_schedule_time(tournament, index),
            ))
    elif tournament.tournament_type == "single_elimination":
        bracket_size = _next_power_of_two(len(teams))
        round_count = int(math.log2(bracket_size))
        rounds = {}
        for round_number in range(1, round_count + 1):
            match_count = bracket_size // (2 ** round_number)
            rounds[round_number] = []
            for match_number in range(1, match_count + 1):
                match = CommunityTournamentMatch(
                    id=uuid.uuid4(),
                    tournament_id=tournament.id,
                    stage="bracket",
                    round_number=round_number,
                    match_number=match_number,
                    status=CommunityMatchStatus.SCHEDULED,
                )
                rounds[round_number].append(match)
                db.session.add(match)
        seeded_pairs = _seed_pairs(teams, bracket_size)
        for index, match in enumerate(rounds[1]):
            team_a, team_b = seeded_pairs[index]
            match.team_a_id = team_a.id if team_a else None
            match.team_b_id = team_b.id if team_b else None
            if match.team_a_id and match.team_b_id:
                match.status = CommunityMatchStatus.READY
            elif match.team_a_id or match.team_b_id:
                match.status = CommunityMatchStatus.COMPLETED
                match.winner_team_id = match.team_a_id or match.team_b_id
                match.completed_at = _now()
        for round_number in range(1, round_count):
            for index, match in enumerate(rounds[round_number]):
                next_match = rounds[round_number + 1][index // 2]
                match.next_match_id = next_match.id
                match.next_match_slot = "A" if index % 2 == 0 else "B"
                if match.winner_team_id:
                    if match.next_match_slot == "A":
                        next_match.team_a_id = match.winner_team_id
                    else:
                        next_match.team_b_id = match.winner_team_id
        for matches in rounds.values():
            for match in matches:
                if match.team_a_id and match.team_b_id and match.status == CommunityMatchStatus.SCHEDULED:
                    match.status = CommunityMatchStatus.READY
        _schedule_bracket_rounds(tournament, rounds)
    else:
        raise CommunityConflictError("automatic generation currently supports single_elimination, round_robin, and league")

    for team in teams:
        team.roster_locked_at = team.roster_locked_at or _now()
    db.session.flush()
    latest_match = CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).order_by(
        CommunityTournamentMatch.scheduled_at.desc().nullslast(),
    ).first()
    if (
        latest_match
        and latest_match.scheduled_at
        and tournament.tournament_end_at
        and latest_match.scheduled_at + timedelta(minutes=int(tournament.match_duration_minutes or 45)) > tournament.tournament_end_at
    ):
        db.session.rollback()
        raise CommunityConflictError("generated schedule exceeds tournament_end_at; adjust duration, concurrency, or end time")
    _audit(
        "community_matches_generated",
        "community_tournament",
        tournament.id,
        host_user_id,
        metadata={"format": tournament.tournament_type, "auto_checked_in": auto_checked_in},
    )
    db.session.commit()
    return list_matches(tournament.id, {}, include_lobby=True)


def create_manual_match(host_user_id, tournament_id, payload):
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    sync_tournament_status(tournament)
    if tournament.status not in {CommunityTournamentStatus.REGISTRATION_CLOSED, CommunityTournamentStatus.LIVE}:
        raise CommunityConflictError("matches can be created only after registration closes")
    try:
        round_number = int(payload.get("round_number") or 1)
        match_number = int(payload["match_number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CommunityValidationError("round_number and match_number must be positive integers") from exc
    if min(round_number, match_number) <= 0:
        raise CommunityValidationError("round_number and match_number must be positive")
    stage = str(payload.get("stage") or "manual").strip().lower()[:32]
    try:
        team_ids = [
            uuid.UUID(str(payload[field]))
            for field in ("team_a_id", "team_b_id")
            if payload.get(field)
        ]
        participant_ids = [uuid.UUID(str(value)) for value in (payload.get("participant_team_ids") or [])]
    except (TypeError, ValueError) as exc:
        raise CommunityValidationError("match team IDs must be valid UUIDs") from exc
    all_team_ids = set(team_ids + participant_ids)
    if len(all_team_ids) < 2:
        raise CommunityValidationError("at least two tournament teams are required")
    valid_team_ids = {
        team.id
        for team in CommunityTournamentTeam.query.filter(
            CommunityTournamentTeam.tournament_id == tournament.id,
            CommunityTournamentTeam.id.in_(all_team_ids),
            CommunityTournamentTeam.status == CommunityTeamStatus.APPROVED,
        ).all()
    }
    if valid_team_ids != all_team_ids:
        raise CommunityValidationError("all match teams must be approved teams in this tournament")
    if CommunityTournamentMatch.query.filter_by(
        tournament_id=tournament.id,
        stage=stage,
        round_number=round_number,
        match_number=match_number,
    ).first():
        raise CommunityConflictError("this match slot already exists")
    lobby_details = payload.get("lobby_details") or {}
    if not isinstance(lobby_details, dict):
        raise CommunityValidationError("lobby_details must be an object")
    from services.community_tournament_service import _parse_datetime
    scheduled_at = (
        _parse_datetime(payload["scheduled_at"], "scheduled_at")
        if payload.get("scheduled_at") else None
    )
    match = CommunityTournamentMatch(
        tournament_id=tournament.id,
        stage=stage,
        round_number=round_number,
        match_number=match_number,
        status=CommunityMatchStatus.READY if len(team_ids) == 2 else CommunityMatchStatus.SCHEDULED,
        team_a_id=team_ids[0] if team_ids else None,
        team_b_id=team_ids[1] if len(team_ids) > 1 else None,
        participant_team_ids=[str(team_id) for team_id in dict.fromkeys(participant_ids)],
        scheduled_at=scheduled_at,
        lobby_details=lobby_details,
    )
    db.session.add(match)
    db.session.flush()
    _audit("community_match_created", "community_tournament_match", match.id, host_user_id, metadata={"stage": stage})
    db.session.commit()
    return _match_payload(match)


def _match_payload(match, include_lobby=True):
    payload = match.to_dict()
    if not include_lobby:
        payload["lobby_details"] = {}
    team_ids = [team_id for team_id in (match.team_a_id, match.team_b_id, match.winner_team_id) if team_id]
    names = {
        str(team.id): team.name
        for team in CommunityTournamentTeam.query.filter(CommunityTournamentTeam.id.in_(team_ids)).all()
    } if team_ids else {}
    payload.update({
        "team_a_name": names.get(str(match.team_a_id)) if match.team_a_id else None,
        "team_b_name": names.get(str(match.team_b_id)) if match.team_b_id else None,
        "winner_team_name": names.get(str(match.winner_team_id)) if match.winner_team_id else None,
    })
    return payload


def list_matches(tournament_id, filters, include_lobby=False):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    if not include_lobby:
        _require_private_access(tournament, filters.get("invite_code"))
    query = CommunityTournamentMatch.query.filter_by(tournament_id=tournament_id)
    if filters.get("status"):
        query = query.filter_by(status=str(filters["status"]).strip().lower())
    matches = query.order_by(
        CommunityTournamentMatch.round_number.asc(),
        CommunityTournamentMatch.match_number.asc(),
    ).all()
    return {"items": [_match_payload(match, include_lobby=include_lobby) for match in matches]}


def list_private_matches(user_id, tournament_id, filters):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    registration = _registration_for_user(tournament.id, user_id)
    if int(tournament.host_user_id) != int(user_id) and not registration:
        raise CommunityForbiddenError("only the host or active participants can view lobby details")
    return list_matches(tournament_id, filters, include_lobby=True)


def leaderboard(tournament_id, invite_code=None):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    _require_private_access(tournament, invite_code)
    teams = CommunityTournamentTeam.query.filter_by(tournament_id=tournament_id).all()
    standings = {
        team.id: {
            "team_id": str(team.id),
            "team_name": team.name,
            "played": 0,
            "wins": 0,
            "losses": 0,
            "points": 0,
            "score_for": 0,
            "score_against": 0,
        }
        for team in teams
    }
    matches = CommunityTournamentMatch.query.filter_by(
        tournament_id=tournament_id,
        status=CommunityMatchStatus.COMPLETED,
    ).all()
    for match in matches:
        if match.standings:
            for entry in match.standings:
                try:
                    team_id = uuid.UUID(str(entry["team_id"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if team_id not in standings:
                    continue
                standings[team_id]["played"] += 1
                standings[team_id]["points"] += int(entry.get("points") or 0)
                if int(entry.get("placement") or 0) == 1:
                    standings[team_id]["wins"] += 1
            continue
        if not match.team_a_id or not match.team_b_id:
            continue
        for team_id in (match.team_a_id, match.team_b_id):
            if team_id in standings:
                standings[team_id]["played"] += 1
        if match.winner_team_id in standings:
            standings[match.winner_team_id]["wins"] += 1
            standings[match.winner_team_id]["points"] += 3
        loser_id = match.team_b_id if match.winner_team_id == match.team_a_id else match.team_a_id
        if loser_id in standings:
            standings[loser_id]["losses"] += 1
        if match.team_a_score is not None and match.team_b_score is not None:
            standings[match.team_a_id]["score_for"] += match.team_a_score
            standings[match.team_a_id]["score_against"] += match.team_b_score
            standings[match.team_b_id]["score_for"] += match.team_b_score
            standings[match.team_b_id]["score_against"] += match.team_a_score
    items = sorted(
        standings.values(),
        key=lambda row: (-row["points"], -(row["score_for"] - row["score_against"]), row["team_name"].lower()),
    )
    for index, item in enumerate(items, start=1):
        item["position"] = index
    return {"items": items}


def _advance_match_winner(match, winner_team_id):
    match.winner_team_id = winner_team_id
    match.status = CommunityMatchStatus.COMPLETED
    match.completed_at = _now()
    if not match.next_match_id:
        return
    next_match = CommunityTournamentMatch.query.filter_by(id=match.next_match_id).with_for_update().first()
    if not next_match:
        return
    if match.next_match_slot == "A":
        next_match.team_a_id = winner_team_id
    else:
        next_match.team_b_id = winner_team_id
    if next_match.team_a_id and next_match.team_b_id:
        next_match.status = CommunityMatchStatus.READY


def _retract_advanced_winner(match):
    if not match.next_match_id or not match.winner_team_id:
        return
    next_match = CommunityTournamentMatch.query.filter_by(id=match.next_match_id).with_for_update().first()
    if not next_match:
        return
    if next_match.status not in {CommunityMatchStatus.SCHEDULED, CommunityMatchStatus.READY}:
        raise CommunityConflictError("the downstream match has already started; this result cannot be restarted")
    if match.next_match_slot == "A" and next_match.team_a_id == match.winner_team_id:
        next_match.team_a_id = None
    elif match.next_match_slot == "B" and next_match.team_b_id == match.winner_team_id:
        next_match.team_b_id = None
    next_match.status = CommunityMatchStatus.SCHEDULED


def _proposal_evidence_urls(values):
    if not isinstance(values, list) or len(values) > 10:
        raise CommunityValidationError("evidence_urls must contain at most 10 URLs")
    urls = []
    for value in values:
        url = str(value or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise CommunityValidationError("each evidence URL must be an absolute https URL")
        urls.append(url)
    return urls


def _match_captain_team(user_id, tournament_id, match):
    membership = CommunityTournamentTeamMember.query.filter(
        CommunityTournamentTeamMember.tournament_id == tournament_id,
        CommunityTournamentTeamMember.user_id == int(user_id),
        CommunityTournamentTeamMember.team_id.in_([match.team_a_id, match.team_b_id]),
        CommunityTournamentTeamMember.role == "captain",
        CommunityTournamentTeamMember.verification_status.in_({"accepted", "verified"}),
    ).first()
    if not membership:
        raise CommunityForbiddenError("only a match team captain can respond to this proposal")
    return membership.team_id


def _finalize_result_proposal(proposal, match):
    match.team_a_score = proposal.team_a_score
    match.team_b_score = proposal.team_b_score
    _advance_match_winner(match, proposal.winner_team_id)
    proposal.status = "finalized"
    proposal.finalized_at = _now()


def create_result_proposal(host_user_id, tournament_id, match_id, payload):
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    match = CommunityTournamentMatch.query.filter_by(id=match_id, tournament_id=tournament.id).with_for_update().first()
    if not match:
        raise CommunityValidationError("match not found")
    if match.status not in {CommunityMatchStatus.IN_PROGRESS, CommunityMatchStatus.AWAITING_RESULTS, CommunityMatchStatus.DISPUTED}:
        raise CommunityConflictError("result proposals are available only for active, awaiting, or disputed matches")
    if not match.team_a_id or not match.team_b_id:
        raise CommunityConflictError("result proposals require two assigned teams")
    if CommunityMatchResultProposal.query.filter_by(match_id=match.id, status="pending").first():
        raise CommunityConflictError("a result proposal is already pending")
    try:
        winner_team_id = uuid.UUID(str(payload["winner_team_id"]))
        team_a_score = int(payload["team_a_score"])
        team_b_score = int(payload["team_b_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CommunityValidationError("winner_team_id and both non-negative scores are required") from exc
    if winner_team_id not in {match.team_a_id, match.team_b_id} or min(team_a_score, team_b_score) < 0:
        raise CommunityValidationError("invalid result proposal")
    evidence = _validated_evidence_asset_ids(payload.get("evidence_asset_ids") or [], tournament.id, host_user_id, {"result_evidence"})
    evidence_urls = _proposal_evidence_urls(payload.get("evidence_urls") or [])
    if not evidence and not evidence_urls:
        raise CommunityValidationError("at least one evidence asset or screenshot URL is required")
    ocr_data = payload.get("ocr_data") or {}
    if not isinstance(ocr_data, dict):
        raise CommunityValidationError("ocr_data must be an object")
    proposal = CommunityMatchResultProposal(
        tournament_id=tournament.id, match_id=match.id, proposed_by_user_id=int(host_user_id),
        winner_team_id=winner_team_id, team_a_score=team_a_score, team_b_score=team_b_score,
        evidence_asset_ids=evidence, evidence_urls=evidence_urls, ocr_data=ocr_data,
        expires_at=_now() + timedelta(minutes=15),
    )
    db.session.add(proposal)
    db.session.flush()
    match.status = CommunityMatchStatus.RESULT_PENDING
    _audit("community_result_proposed", "community_match_result_proposal", proposal.id, host_user_id)
    db.session.commit()
    return proposal


def accept_result_proposal(user_id, tournament_id, match_id, proposal_id):
    match = CommunityTournamentMatch.query.filter_by(id=match_id, tournament_id=tournament_id).with_for_update().first()
    proposal = CommunityMatchResultProposal.query.filter_by(id=proposal_id, match_id=match_id, tournament_id=tournament_id).with_for_update().first()
    if not match or not proposal:
        raise CommunityValidationError("result proposal not found")
    if proposal.status != "pending" or proposal.expires_at <= _now():
        raise CommunityConflictError("result proposal is no longer pending")
    team_id = _match_captain_team(user_id, tournament_id, match)
    accepted = {str(value) for value in (proposal.accepted_team_ids or [])}
    accepted.add(str(team_id))
    proposal.accepted_team_ids = sorted(accepted)
    if {str(match.team_a_id), str(match.team_b_id)}.issubset(accepted):
        _finalize_result_proposal(proposal, match)
    _audit("community_result_proposal_accepted", "community_match_result_proposal", proposal.id, user_id)
    db.session.commit()
    return proposal


def dispute_result_proposal(user_id, tournament_id, match_id, proposal_id, payload):
    match = CommunityTournamentMatch.query.filter_by(id=match_id, tournament_id=tournament_id).with_for_update().first()
    proposal = CommunityMatchResultProposal.query.filter_by(id=proposal_id, match_id=match_id, tournament_id=tournament_id).with_for_update().first()
    if not match or not proposal:
        raise CommunityValidationError("result proposal not found")
    if proposal.status != "pending" or proposal.expires_at <= _now():
        raise CommunityConflictError("result proposal is no longer pending")
    _match_captain_team(user_id, tournament_id, match)
    proposal.status = "disputed"
    proposal.disputed_at = _now()
    match.status = CommunityMatchStatus.DISPUTED
    dispute = CommunityTournamentDispute(
        tournament_id=tournament_id, match_id=match_id, reported_by_user_id=int(user_id),
        reason="Host result proposal disputed", description=str(payload.get("description") or "Result proposal disputed by a match captain.").strip(),
        evidence_asset_ids=_validated_evidence_asset_ids(payload.get("evidence_asset_ids") or [], tournament_id, user_id, {"dispute_evidence", "result_evidence"}),
        response_deadline_at=_now() + timedelta(minutes=15),
    )
    db.session.add(dispute)
    _audit("community_result_proposal_disputed", "community_match_result_proposal", proposal.id, user_id)
    db.session.commit()
    return proposal


def manage_match(host_user_id, tournament_id, match_id, payload):
    tournament = _owned_tournament(host_user_id, tournament_id, lock=True)
    match = CommunityTournamentMatch.query.filter_by(id=match_id, tournament_id=tournament.id).with_for_update().first()
    if not match:
        raise CommunityValidationError("match not found")
    action = str(payload.get("action") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    if action == "start":
        if match.status not in {CommunityMatchStatus.SCHEDULED, CommunityMatchStatus.READY}:
            raise CommunityConflictError("match cannot be started from its current status")
        if not match.team_a_id or not match.team_b_id:
            raise CommunityConflictError("both opponents must be assigned")
        match.status = CommunityMatchStatus.IN_PROGRESS
        match.started_at = _now()
        match.result_due_at = _now() + timedelta(minutes=int(tournament.result_submission_window_minutes or 15))
    elif action == "reschedule":
        if match.status in {CommunityMatchStatus.COMPLETED, CommunityMatchStatus.CANCELLED}:
            raise CommunityConflictError("closed matches cannot be rescheduled")
        from services.community_tournament_service import _parse_datetime
        match.scheduled_at = _parse_datetime(payload.get("scheduled_at"), "scheduled_at")
    elif action == "set_lobby":
        if not isinstance(payload.get("lobby_details"), dict):
            raise CommunityValidationError("lobby_details must be an object")
        match.lobby_details = payload["lobby_details"]
    elif action == "override_result":
        raise CommunityConflictError(
            "host result overrides require a result proposal; use the result-proposals endpoint"
        )
    elif action == "record_standings":
        raw_standings = payload.get("standings")
        if not isinstance(raw_standings, list) or len(raw_standings) < 2:
            raise CommunityValidationError("standings must contain at least two teams")
        allowed_ids = {
            uuid.UUID(str(value))
            for value in (match.participant_team_ids or [])
        }
        if not allowed_ids:
            raise CommunityConflictError("this match is not configured for multi-team standings")
        placement_points = (tournament.schedule_config or {}).get("placement_points") or {}
        normalized = []
        seen_teams = set()
        seen_placements = set()
        for raw in raw_standings:
            try:
                team_id = uuid.UUID(str(raw["team_id"]))
                placement = int(raw["placement"])
                kills = int(raw.get("kills") or 0)
                penalty = int(raw.get("penalty_points") or 0)
            except (KeyError, TypeError, ValueError) as exc:
                raise CommunityValidationError("each standing requires team_id, placement, and valid points") from exc
            if team_id not in allowed_ids or team_id in seen_teams or placement <= 0 or placement in seen_placements or kills < 0 or penalty < 0:
                raise CommunityValidationError("standings contain invalid or duplicate teams/placements")
            points = int(raw.get("points")) if raw.get("points") is not None else int(placement_points.get(str(placement), 0)) + kills - penalty
            normalized.append({
                "team_id": str(team_id),
                "placement": placement,
                "kills": kills,
                "penalty_points": penalty,
                "points": points,
            })
            seen_teams.add(team_id)
            seen_placements.add(placement)
        if seen_teams != allowed_ids:
            raise CommunityValidationError("standings must include every match participant")
        normalized.sort(key=lambda row: row["placement"])
        match.standings = normalized
        match.winner_team_id = uuid.UUID(normalized[0]["team_id"])
        match.status = CommunityMatchStatus.COMPLETED
        match.completed_at = _now()
    elif action == "restart":
        if not reason:
            raise CommunityValidationError("reason is required to restart a match")
        _retract_advanced_winner(match)
        CommunityMatchResultSubmission.query.filter_by(match_id=match.id).delete(synchronize_session=False)
        match.status = CommunityMatchStatus.READY
        match.winner_team_id = None
        match.team_a_score = None
        match.team_b_score = None
        match.completed_at = None
        match.admin_notes = reason
    elif action == "cancel":
        if not reason:
            raise CommunityValidationError("reason is required")
        if match.status == CommunityMatchStatus.COMPLETED:
            raise CommunityConflictError("completed matches cannot be cancelled")
        match.status = CommunityMatchStatus.CANCELLED
        match.admin_notes = reason
    else:
        raise CommunityValidationError("unsupported match action")
    _audit(f"community_match_{action}", "community_tournament_match", match.id, host_user_id, metadata={"reason": reason})
    db.session.commit()
    return _match_payload(match)


def submit_captain_result(user_id, tournament_id, match_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    match = CommunityTournamentMatch.query.filter_by(id=match_id, tournament_id=tournament_id).with_for_update().first()
    if not tournament or not match:
        raise CommunityValidationError("match not found")
    membership = (
        CommunityTournamentTeamMember.query
        .filter(
            CommunityTournamentTeamMember.user_id == int(user_id),
            CommunityTournamentTeamMember.team_id.in_([match.team_a_id, match.team_b_id]),
            CommunityTournamentTeamMember.role == "captain",
        )
        .first()
    )
    if not membership:
        raise CommunityForbiddenError("only a match team captain can submit this result")
    if match.status not in {CommunityMatchStatus.IN_PROGRESS, CommunityMatchStatus.AWAITING_RESULTS}:
        raise CommunityConflictError("results can be submitted only after the match starts")
    try:
        winner_team_id = uuid.UUID(str(payload["winner_team_id"]))
        team_a_score = int(payload["team_a_score"])
        team_b_score = int(payload["team_b_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CommunityValidationError("winner_team_id and both non-negative scores are required") from exc
    if winner_team_id not in {match.team_a_id, match.team_b_id} or min(team_a_score, team_b_score) < 0:
        raise CommunityValidationError("invalid match result")
    evidence = payload.get("evidence_asset_ids") or []
    if not evidence:
        raise CommunityValidationError("at least one evidence asset is required")
    evidence = _validated_evidence_asset_ids(
        evidence,
        tournament.id,
        user_id,
        {"result_evidence"},
    )
    if CommunityMatchResultSubmission.query.filter_by(match_id=match.id, team_id=membership.team_id).first():
        raise CommunityConflictError("this team has already submitted a result")
    submission = CommunityMatchResultSubmission(
        match_id=match.id,
        team_id=membership.team_id,
        submitted_by_user_id=int(user_id),
        winner_team_id=winner_team_id,
        team_a_score=team_a_score,
        team_b_score=team_b_score,
        evidence_asset_ids=evidence,
        notes=str(payload.get("notes") or "").strip() or None,
    )
    db.session.add(submission)
    prior = CommunityMatchResultSubmission.query.filter(
        CommunityMatchResultSubmission.match_id == match.id,
        CommunityMatchResultSubmission.team_id != membership.team_id,
    ).first()
    if prior:
        agrees = (
            prior.winner_team_id == winner_team_id
            and prior.team_a_score == team_a_score
            and prior.team_b_score == team_b_score
        )
        if agrees:
            prior.status = "accepted"
            submission.status = "accepted"
            match.team_a_score = team_a_score
            match.team_b_score = team_b_score
            _advance_match_winner(match, winner_team_id)
        else:
            prior.status = "conflict"
            submission.status = "conflict"
            match.status = CommunityMatchStatus.DISPUTED
            dispute = CommunityTournamentDispute(
                tournament_id=tournament.id,
                match_id=match.id,
                reported_by_user_id=int(user_id),
                reason="Conflicting captain result submissions",
                description="The two team captains submitted different winners or scores.",
                evidence_asset_ids=list({str(asset) for asset in (prior.evidence_asset_ids or []) + evidence}),
                response_deadline_at=_now() + timedelta(minutes=int(tournament.dispute_window_minutes or 30)),
            )
            db.session.add(dispute)
            _notify(tournament.host_user_id, "community_result_conflict", "Result conflict requires review", f"Match {match.match_number} has conflicting captain submissions.", tournament.id)
    else:
        match.status = CommunityMatchStatus.AWAITING_RESULTS
        match.result_due_at = _now() + timedelta(minutes=int(tournament.result_submission_window_minutes or 15))
    _audit("community_captain_result_submitted", "community_tournament_match", match.id, user_id, metadata={"team_id": str(membership.team_id)})
    db.session.commit()
    return {"match": _match_payload(match), "submission": submission.to_dict()}


def create_announcement(host_user_id, tournament_id, payload):
    tournament = _owned_tournament(host_user_id, tournament_id)
    title = str(payload.get("title") or "").strip()
    message = str(payload.get("message") or "").strip()
    audience = str(payload.get("audience") or "all_participants").strip().lower()
    if not title or not message:
        raise CommunityValidationError("title and message are required")
    if audience not in {"all_participants", "captains", "unchecked_in", "specific_teams"}:
        raise CommunityValidationError("invalid announcement audience")
    target_team_ids = [str(uuid.UUID(str(value))) for value in (payload.get("target_team_ids") or [])]
    if audience == "specific_teams" and not target_team_ids:
        raise CommunityValidationError("target_team_ids are required for specific_teams")
    announcement = CommunityTournamentAnnouncement(
        tournament_id=tournament.id,
        created_by_user_id=int(host_user_id),
        title=title[:160],
        message=message,
        audience=audience,
        target_team_ids=target_team_ids,
    )
    db.session.add(announcement)
    db.session.flush()
    teams = CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id).all()
    recipients = set()
    for team in teams:
        if audience == "unchecked_in" and team.checked_in_at:
            continue
        if audience == "specific_teams" and str(team.id) not in target_team_ids:
            continue
        if audience == "captains":
            recipients.add(int(team.captain_user_id))
            continue
        members = CommunityTournamentTeamMember.query.filter_by(team_id=team.id).all()
        recipients.update(int(member.user_id) for member in members)
    for recipient in recipients:
        _notify(recipient, "community_announcement", title[:160], message, tournament.id)
    _audit("community_announcement_published", "community_tournament_announcement", announcement.id, host_user_id, metadata={"audience": audience})
    db.session.commit()
    return announcement


def list_announcements(tournament_id, requester_user_id):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    rows = CommunityTournamentAnnouncement.query.filter_by(tournament_id=tournament_id).order_by(
        CommunityTournamentAnnouncement.published_at.desc(),
    ).all()
    if int(requester_user_id) == int(tournament.host_user_id):
        return {"items": [row.to_dict() for row in rows]}
    registration = _registration_for_user(tournament.id, requester_user_id)
    membership = CommunityTournamentTeamMember.query.filter_by(
        tournament_id=tournament.id,
        user_id=int(requester_user_id),
    ).first()
    if not registration and not membership:
        raise CommunityForbiddenError("only tournament participants can read announcements")
    team = CommunityTournamentTeam.query.filter_by(id=membership.team_id).first() if membership else None
    visible = []
    for row in rows:
        if row.audience == "all_participants":
            visible.append(row)
        elif row.audience == "captains" and membership and membership.role == "captain":
            visible.append(row)
        elif row.audience == "unchecked_in" and team and not team.checked_in_at:
            visible.append(row)
        elif row.audience == "specific_teams" and team and str(team.id) in (row.target_team_ids or []):
            visible.append(row)
    return {"items": [row.to_dict() for row in visible]}


def host_dashboard(host_user_id):
    tournaments = CommunityTournament.query.filter_by(host_user_id=int(host_user_id)).all()
    tournament_ids = [tournament.id for tournament in tournaments]
    if not tournament_ids:
        return {"summary": {"active_tournaments": 0, "total_registrations": 0, "entry_fees_collected": 0, "prize_pool": 0, "pending_team_approvals": 0, "matches_requiring_verification": 0, "open_disputes": 0}, "tournaments": []}
    for tournament in tournaments:
        sync_tournament_status(tournament)
    registrations = CommunityTournamentRegistration.query.filter(
        CommunityTournamentRegistration.tournament_id.in_(tournament_ids),
        CommunityTournamentRegistration.status == CommunityTournamentRegistrationStatus.CONFIRMED,
    ).count()
    pending_teams = CommunityTournamentTeam.query.filter(
        CommunityTournamentTeam.tournament_id.in_(tournament_ids),
        CommunityTournamentTeam.status == CommunityTeamStatus.PENDING,
    ).count()
    attention_matches = CommunityTournamentMatch.query.filter(
        CommunityTournamentMatch.tournament_id.in_(tournament_ids),
        CommunityTournamentMatch.status.in_({CommunityMatchStatus.AWAITING_RESULTS, CommunityMatchStatus.DISPUTED}),
    ).count()
    open_disputes = CommunityTournamentDispute.query.filter(
        CommunityTournamentDispute.tournament_id.in_(tournament_ids),
        CommunityTournamentDispute.status.in_({CommunityDisputeStatus.OPEN, CommunityDisputeStatus.UNDER_REVIEW}),
    ).count()
    items = []
    for tournament in tournaments:
        item = tournament.to_dict(include_room_details=True)
        item["attention"] = {
            "pending_team_approvals": CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id, status=CommunityTeamStatus.PENDING).count(),
            "unchecked_in_teams": CommunityTournamentTeam.query.filter(
                CommunityTournamentTeam.tournament_id == tournament.id,
                CommunityTournamentTeam.status == CommunityTeamStatus.APPROVED,
                CommunityTournamentTeam.checked_in_at.is_(None),
            ).count(),
            "matches_requiring_verification": CommunityTournamentMatch.query.filter(
                CommunityTournamentMatch.tournament_id == tournament.id,
                CommunityTournamentMatch.status.in_({CommunityMatchStatus.AWAITING_RESULTS, CommunityMatchStatus.DISPUTED}),
            ).count(),
            "open_disputes": CommunityTournamentDispute.query.filter(
                CommunityTournamentDispute.tournament_id == tournament.id,
                CommunityTournamentDispute.status.in_({CommunityDisputeStatus.OPEN, CommunityDisputeStatus.UNDER_REVIEW}),
            ).count(),
        }
        items.append(item)
    db.session.commit()
    return {
        "summary": {
            "active_tournaments": sum(1 for tournament in tournaments if tournament.status not in {CommunityTournamentStatus.DRAFT, CommunityTournamentStatus.COMPLETED, CommunityTournamentStatus.CANCELLED}),
            "total_registrations": registrations,
            "entry_fees_collected": float(sum(Decimal(str(tournament.total_collection or 0)) for tournament in tournaments)),
            "prize_pool": float(sum(Decimal(str(tournament.prize_pool or 0)) for tournament in tournaments)),
            "pending_team_approvals": pending_teams,
            "matches_requiring_verification": attention_matches,
            "open_disputes": open_disputes,
        },
        "tournaments": items,
    }


def control_room(host_user_id, tournament_id):
    tournament = _owned_tournament(host_user_id, tournament_id)
    teams = CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id).all()
    matches = CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).all()
    disputes = CommunityTournamentDispute.query.filter_by(tournament_id=tournament.id).all()
    refunds = db.session.query(func.coalesce(func.sum(CommunityTournamentRegistration.refund_amount), 0)).filter_by(tournament_id=tournament.id).scalar()
    payouts = CommunityTournamentPayout.query.filter_by(tournament_id=tournament.id).all()
    return {
        "tournament": tournament.to_dict(include_room_details=True),
        "health": {
            "teams_total": len(teams),
            "teams_approved": sum(team.status == CommunityTeamStatus.APPROVED for team in teams),
            "teams_checked_in": sum(team.checked_in_at is not None for team in teams),
            "matches_total": len(matches),
            "matches_completed": sum(match.status == CommunityMatchStatus.COMPLETED for match in matches),
            "matches_delayed": sum(bool(match.scheduled_at and match.scheduled_at < _now() and match.status in {CommunityMatchStatus.SCHEDULED, CommunityMatchStatus.READY}) for match in matches),
            "results_awaiting": sum(match.status == CommunityMatchStatus.AWAITING_RESULTS for match in matches),
            "open_disputes": sum(dispute.status in {CommunityDisputeStatus.OPEN, CommunityDisputeStatus.UNDER_REVIEW} for dispute in disputes),
        },
        "finance": {
            "entry_fees_collected": float(tournament.total_collection or 0),
            "refunds": float(refunds or 0),
            "net_collection": float(Decimal(str(tournament.total_collection or 0)) - Decimal(str(refunds or 0))),
            "organizer_commission": float(tournament.organizer_commission_amount or 0),
            "prize_pool": float(tournament.prize_pool or 0),
            "payouts": [payout.to_dict() for payout in payouts],
        },
    }


def list_audit_log(host_user_id, tournament_id, filters):
    tournament = _owned_tournament(host_user_id, tournament_id)
    page, per_page = _pagination(filters)
    entity_ids = {str(tournament.id)}
    entity_ids.update(str(team.id) for team in CommunityTournamentTeam.query.filter_by(tournament_id=tournament.id).all())
    entity_ids.update(str(match.id) for match in CommunityTournamentMatch.query.filter_by(tournament_id=tournament.id).all())
    query = CommunityAuditLog.query.filter(CommunityAuditLog.entity_id.in_(entity_ids))
    total = query.count()
    rows = query.order_by(CommunityAuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [row.to_dict() for row in rows],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


def process_operational_deadlines(limit=50):
    limit = min(max(int(limit or 50), 1), 100)
    summary = {"processed": 0, "escalated": 0, "lifecycle_updated": 0, "items": [], "lifecycle": []}

    lifecycle_tournaments = (
        CommunityTournament.query
        .filter(CommunityTournament.status.in_({
            CommunityTournamentStatus.PUBLISHED,
            CommunityTournamentStatus.REGISTRATION_OPEN,
            CommunityTournamentStatus.REGISTRATION_CLOSED,
            CommunityTournamentStatus.LIVE,
        }))
        .order_by(CommunityTournament.tournament_start_at.asc())
        .limit(limit)
        .all()
    )
    for tournament in lifecycle_tournaments:
        previous_status = tournament.status
        if not sync_tournament_status(tournament):
            continue
        _audit(
            "community_tournament_lifecycle_updated",
            "community_tournament",
            tournament.id,
            actor_type="system",
            metadata={"from_status": previous_status, "to_status": tournament.status},
        )
        _notify(
            tournament.host_user_id,
            "community_tournament_status_changed",
            "Tournament status updated",
            f"{tournament.title} is now {tournament.status.replace('_', ' ')}.",
            tournament.id,
        )
        summary["lifecycle_updated"] += 1
        summary["lifecycle"].append({
            "tournament_id": str(tournament.id),
            "from_status": previous_status,
            "to_status": tournament.status,
        })
    if summary["lifecycle_updated"]:
        db.session.commit()

    matches = (
        CommunityTournamentMatch.query
        .filter(
            CommunityTournamentMatch.status == CommunityMatchStatus.AWAITING_RESULTS,
            CommunityTournamentMatch.result_due_at.isnot(None),
            CommunityTournamentMatch.result_due_at <= _now(),
        )
        .order_by(CommunityTournamentMatch.result_due_at.asc())
        .limit(limit)
        .all()
    )
    for match in matches:
        summary["processed"] += 1
        existing = CommunityTournamentDispute.query.filter(
            CommunityTournamentDispute.tournament_id == match.tournament_id,
            CommunityTournamentDispute.match_id == match.id,
            CommunityTournamentDispute.status.in_({
                CommunityDisputeStatus.OPEN,
                CommunityDisputeStatus.UNDER_REVIEW,
            }),
        ).first()
        if not existing:
            submission = CommunityMatchResultSubmission.query.filter_by(match_id=match.id).first()
            dispute = CommunityTournamentDispute(
                tournament_id=match.tournament_id,
                match_id=match.id,
                reported_by_user_id=submission.submitted_by_user_id if submission else None,
                reason="Opponent result response expired",
                description="Only one captain submitted a result before the confirmation deadline.",
                evidence_asset_ids=submission.evidence_asset_ids if submission else [],
                response_deadline_at=_now(),
            )
            db.session.add(dispute)
        match.status = CommunityMatchStatus.DISPUTED
        tournament = CommunityTournament.query.filter_by(id=match.tournament_id).first()
        if tournament:
            _notify(
                tournament.host_user_id,
                "community_result_response_expired",
                "Result confirmation expired",
                f"Match {match.match_number} requires organizer review.",
                tournament.id,
            )
        _audit(
            "community_match_result_deadline_expired",
            "community_tournament_match",
            match.id,
            actor_type="system",
        )
        db.session.commit()
        summary["escalated"] += 1
        summary["items"].append({"match_id": str(match.id), "status": match.status})
    proposals = (
        CommunityMatchResultProposal.query
        .filter_by(status="pending")
        .filter(CommunityMatchResultProposal.expires_at <= _now())
        .order_by(CommunityMatchResultProposal.expires_at.asc())
        .limit(limit)
        .all()
    )
    for proposal in proposals:
        match = CommunityTournamentMatch.query.filter_by(id=proposal.match_id).with_for_update().first()
        if not match or match.status != CommunityMatchStatus.RESULT_PENDING:
            continue
        _finalize_result_proposal(proposal, match)
        _audit("community_result_proposal_expired_finalized", "community_match_result_proposal", proposal.id, actor_type="system")
        db.session.commit()
        summary.setdefault("proposals_finalized", 0)
        summary["proposals_finalized"] += 1
    return summary


MANDATORY_HASH_RULES = [
    "Identity and registered game IDs must match the approved roster.",
    "Match result evidence must be retained until payouts are settled.",
    "Cheating, account sharing, and unauthorized software are prohibited.",
    "Prize-affecting disputes may be escalated to Hash moderation.",
    "Entry fees and prizes are controlled by Hash settlement, not the organizer.",
]

GAME_RULE_TEMPLATES = {
    "valorant": {
        "match_format": "Best of 3",
        "allowed_servers": ["Mumbai", "Singapore"],
        "late_arrival_limit_minutes": 10,
        "evidence_required": ["final_scoreboard_screenshot"],
    },
    "bgmi": {
        "scoring": {"placement_points": True, "kill_points": 1},
        "emulators_allowed": False,
        "evidence_required": ["result_screen_screenshot"],
    },
    "free fire": {
        "scoring": {"placement_points": True, "kill_points": 1},
        "evidence_required": ["result_screen_screenshot"],
    },
}


def rule_template(game=None):
    normalized = str(game or "").strip().lower()
    return {
        "game": game,
        "template": GAME_RULE_TEMPLATES.get(normalized, {
            "match_format": "Organizer configured",
            "late_arrival_limit_minutes": 10,
            "evidence_required": ["result_screenshot"],
        }),
        "mandatory_hash_rules": MANDATORY_HASH_RULES,
    }


def tournament_readiness(host_user_id, tournament_id):
    tournament = _owned_tournament(host_user_id, tournament_id)
    blockers = []
    warnings = []
    if not tournament.rules and not tournament.rules_config:
        blockers.append("Tournament rules are required.")
    distribution_percent = sum(
        Decimal(str(item.get("percent") or 0))
        for item in (tournament.prize_distribution or [])
        if isinstance(item, dict)
    )
    if tournament.entry_fee > 0 and distribution_percent <= 0:
        blockers.append("Paid tournaments require a prize distribution.")
    if distribution_percent > 100:
        blockers.append("Prize distribution cannot exceed 100 percent.")
    if tournament.is_private and not tournament.invite_code_hash:
        blockers.append("Private tournaments require an invite code.")
    if tournament.team_mode != "solo" and int(tournament.team_size or 1) < 2:
        blockers.append("Team tournaments require team_size of at least 2.")
    if not tournament.check_in_start_at or not tournament.check_in_end_at:
        warnings.append("Check-in window is not configured.")
    if not tournament.roster_lock_at and tournament.team_mode != "solo":
        warnings.append("Roster lock time is not configured.")
    if tournament.tournament_type not in {"single_elimination", "round_robin", "league"}:
        warnings.append("This format currently requires manually operated matches.")
    return {
        "ready_to_publish": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "mandatory_hash_rules": MANDATORY_HASH_RULES,
    }


def create_tournament_review(user_id, tournament_id, payload):
    tournament = CommunityTournament.query.filter_by(id=tournament_id).first()
    if not tournament:
        raise CommunityValidationError("tournament not found")
    if tournament.status != CommunityTournamentStatus.COMPLETED:
        raise CommunityConflictError("reviews open only after tournament completion")
    registration = CommunityTournamentRegistration.query.filter_by(
        tournament_id=tournament.id,
        user_id=int(user_id),
        status=CommunityTournamentRegistrationStatus.CONFIRMED,
    ).first()
    if not registration:
        raise CommunityForbiddenError("only confirmed participants can review this tournament")
    if CommunityTournamentReview.query.filter_by(tournament_id=tournament.id, reviewer_user_id=int(user_id)).first():
        raise CommunityConflictError("you have already reviewed this tournament")
    fields = (
        "management_rating",
        "communication_rating",
        "fairness_rating",
        "scheduling_rating",
        "dispute_handling_rating",
    )
    ratings = {}
    for field in fields:
        try:
            ratings[field] = int(payload[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise CommunityValidationError(f"{field} must be an integer from 1 to 5") from exc
        if ratings[field] < 1 or ratings[field] > 5:
            raise CommunityValidationError(f"{field} must be between 1 and 5")
    overall = (sum(Decimal(value) for value in ratings.values()) / Decimal(len(ratings))).quantize(Decimal("0.01"))
    review = CommunityTournamentReview(
        tournament_id=tournament.id,
        host_user_id=tournament.host_user_id,
        reviewer_user_id=int(user_id),
        overall_rating=overall,
        comment=str(payload.get("comment") or "").strip()[:2000] or None,
        **ratings,
    )
    db.session.add(review)
    db.session.flush()
    _audit("community_tournament_review_created", "community_tournament_review", review.id, user_id)
    db.session.commit()
    return review


def public_host_profile(host_user_id):
    host = User.query.filter_by(id=int(host_user_id)).first()
    if not host:
        raise CommunityValidationError("host not found")
    tournaments = CommunityTournament.query.filter_by(host_user_id=int(host_user_id)).all()
    completed = sum(tournament.status == CommunityTournamentStatus.COMPLETED for tournament in tournaments)
    cancelled = sum(tournament.status == CommunityTournamentStatus.CANCELLED for tournament in tournaments)
    paid_prizes = db.session.query(func.coalesce(func.sum(CommunityTournamentPayout.amount), 0)).filter(
        CommunityTournamentPayout.user_id != int(host_user_id),
        CommunityTournamentPayout.tournament_id.in_([tournament.id for tournament in tournaments] or [uuid.uuid4()]),
        CommunityTournamentPayout.status == "paid",
        CommunityTournamentPayout.payout_type == "player_prize",
    ).scalar()
    reviews = CommunityTournamentReview.query.filter_by(host_user_id=int(host_user_id)).order_by(
        CommunityTournamentReview.created_at.desc(),
    ).all()
    average_rating = (
        sum(Decimal(str(review.overall_rating or 0)) for review in reviews) / Decimal(len(reviews))
        if reviews else Decimal("0")
    )
    decided = completed + cancelled
    return {
        "host_user_id": int(host_user_id),
        "display_name": getattr(host, "name", None),
        "game_username": getattr(host, "game_username", None),
        "avatar_url": getattr(host, "avatar_path", None),
        "verified_organizer": bool(
            CommunityHostVerification.query.filter_by(
                user_id=int(host_user_id),
                verification_status=CommunityHostStatus.VERIFIED,
            ).first()
        ),
        "tournaments_hosted": len(tournaments),
        "completed_tournaments": completed,
        "cancelled_tournaments": cancelled,
        "completion_rate": float(Decimal(completed) * 100 / Decimal(decided)) if decided else 0.0,
        "average_rating": float(average_rating.quantize(Decimal("0.01"))),
        "review_count": len(reviews),
        "prizes_distributed": float(paid_prizes or 0),
        "recent_reviews": [review.to_dict() for review in reviews[:10]],
    }
