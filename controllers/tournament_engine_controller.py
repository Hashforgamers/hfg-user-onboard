from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from db.extensions import db
from models.event import Event
from models.team import Team
from models.teamMember import TeamMember
from models.registration import Registration
from models.tournamentMatch import TournamentMatch, MatchStatus
from models.matchResultSubmission import MatchResultSubmission
from models.matchDispute import MatchDispute
from models.mapVetoAction import MapVetoAction


tournament_engine_bp = Blueprint("tournament_engine", __name__, url_prefix="/api")


DEFAULT_VALORANT_MAP_POOL = ["Bind", "Haven", "Split", "Ascent", "Icebox", "Lotus", "Sunset"]


def _body():
    return request.get_json(silent=True) or {}


def _now():
    return datetime.now(timezone.utc)


def _team_name_map(team_ids):
    if not team_ids:
        return {}
    teams = Team.query.filter(Team.id.in_(team_ids)).all()
    return {str(team.id): team.team_name for team in teams}


def _match_payload(match):
    team_ids = [tid for tid in [match.team_a_id, match.team_b_id, match.winner_team_id] if tid]
    names = _team_name_map(team_ids)
    return {
        "id": str(match.id),
        "event_id": str(match.event_id),
        "round_number": match.round_number,
        "match_number": match.match_number,
        "status": match.status,
        "team_a_id": str(match.team_a_id) if match.team_a_id else None,
        "team_b_id": str(match.team_b_id) if match.team_b_id else None,
        "team_a_name": names.get(str(match.team_a_id)) if match.team_a_id else None,
        "team_b_name": names.get(str(match.team_b_id)) if match.team_b_id else None,
        "winner_team_id": str(match.winner_team_id) if match.winner_team_id else None,
        "winner_team_name": names.get(str(match.winner_team_id)) if match.winner_team_id else None,
        "scheduled_at": match.scheduled_at.isoformat() if match.scheduled_at else None,
        "lobby_instructions": match.lobby_instructions,
        "map_name": match.map_name,
        "server_region": match.server_region,
        "admin_notes": match.admin_notes,
        "map_pool": match.map_pool or [],
        "veto_mode": match.veto_mode,
        "team_a_captain_confirmed_at": match.team_a_captain_confirmed_at.isoformat() if match.team_a_captain_confirmed_at else None,
        "team_b_captain_confirmed_at": match.team_b_captain_confirmed_at.isoformat() if match.team_b_captain_confirmed_at else None,
        "observer_user_id": match.observer_user_id,
        "stream_url": match.stream_url,
        "match_timer_started_at": match.match_timer_started_at.isoformat() if match.match_timer_started_at else None,
    }


def _ensure_team_member(team_id, user_id):
    return TeamMember.query.filter_by(team_id=team_id, user_id=int(user_id)).first() is not None


def _ensure_captain(team_id, user_id):
    return TeamMember.query.filter_by(team_id=team_id, user_id=int(user_id), role="captain").first() is not None


def _build_lobby_instructions(event, match):
    region = match.server_region or event.server or event.region or "Organizer selected"
    map_text = match.map_name or "Map veto/admin selection pending"
    return (
        f"Valorant custom lobby: Team A creates the lobby and invites Team B. "
        f"Server: {region}. Map: {map_text}. Captains must upload the final scoreboard screenshot."
    )


def _advance_winner(event, match, winner_team_id):
    match.winner_team_id = winner_team_id
    match.status = MatchStatus.COMPLETED
    next_match = TournamentMatch.query.filter_by(
        event_id=event.id,
        round_number=match.round_number + 1,
        match_number=(match.match_number + 1) // 2,
    ).first()
    if not next_match:
        return
    if match.match_number % 2 == 1:
        next_match.team_a_id = winner_team_id
    else:
        next_match.team_b_id = winner_team_id
    if next_match.team_a_id and next_match.team_b_id:
        next_match.status = MatchStatus.READY
    next_match.lobby_instructions = _build_lobby_instructions(event, next_match)


@tournament_engine_bp.get("/events/<uuid:event_id>/matches")
def list_event_matches(event_id):
    Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    matches = (
        TournamentMatch.query
        .filter_by(event_id=event_id)
        .order_by(TournamentMatch.round_number.asc(), TournamentMatch.match_number.asc())
        .all()
    )
    return jsonify([_match_payload(match) for match in matches]), 200


@tournament_engine_bp.post("/events/<uuid:event_id>/teams/<uuid:team_id>/check-in")
def check_in_team(event_id, team_id):
    body = _body()
    user_id = body.get("user_id")
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    if not _ensure_team_member(team_id, user_id):
        return jsonify({"error": "only team members can check in"}), 403
    reg = Registration.query.filter_by(event_id=event_id, team_id=team_id).first_or_404()
    reg.checked_in_at = _now()
    db.session.commit()
    return jsonify({"ok": True, "checked_in_at": reg.checked_in_at.isoformat()}), 200


@tournament_engine_bp.post("/events/<uuid:event_id>/matches/<uuid:match_id>/confirm")
def confirm_match(event_id, match_id):
    body = _body()
    user_id = body.get("user_id")
    team_id = body.get("team_id")
    if user_id is None or not team_id:
        return jsonify({"error": "user_id and team_id required"}), 400
    if not _ensure_captain(team_id, user_id):
        return jsonify({"error": "only team captains can confirm"}), 403
    match = TournamentMatch.query.filter_by(id=match_id, event_id=event_id).first_or_404()
    if str(team_id) == str(match.team_a_id):
        match.team_a_captain_confirmed_at = _now()
    elif str(team_id) == str(match.team_b_id):
        match.team_b_captain_confirmed_at = _now()
    else:
        return jsonify({"error": "team_id must be one of the match teams"}), 400
    if match.team_a_captain_confirmed_at and match.team_b_captain_confirmed_at and match.status == MatchStatus.READY:
        match.status = MatchStatus.LOBBY_CREATED
    db.session.commit()
    return jsonify(_match_payload(match)), 200


@tournament_engine_bp.post("/events/<uuid:event_id>/matches/<uuid:match_id>/result-submissions")
def submit_match_result(event_id, match_id):
    body = _body()
    user_id = body.get("user_id")
    team_id = body.get("team_id")
    winner_team_id = body.get("winner_team_id")
    if user_id is None or not team_id:
        return jsonify({"error": "user_id and team_id required"}), 400
    if not _ensure_captain(team_id, user_id):
        return jsonify({"error": "only team captains can submit results"}), 403
    event = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    match = TournamentMatch.query.filter_by(id=match_id, event_id=event_id).first_or_404()
    if str(team_id) not in {str(match.team_a_id), str(match.team_b_id)}:
        return jsonify({"error": "team_id must be one of the match teams"}), 400
    if winner_team_id and str(winner_team_id) not in {str(match.team_a_id), str(match.team_b_id)}:
        return jsonify({"error": "winner_team_id must be one of the match teams"}), 400

    submission = MatchResultSubmission(
        event_id=event.id,
        match_id=match.id,
        team_id=team_id,
        submitted_by_user=int(user_id),
        winner_team_id=winner_team_id,
        team_a_score=body.get("team_a_score"),
        team_b_score=body.get("team_b_score"),
        screenshot_url=body.get("screenshot_url"),
        notes=body.get("notes"),
    )
    db.session.add(submission)
    prior = (
        MatchResultSubmission.query
        .filter(MatchResultSubmission.match_id == match.id)
        .filter(MatchResultSubmission.team_id != team_id)
        .order_by(MatchResultSubmission.created_at.desc())
        .first()
    )
    if prior and prior.winner_team_id and winner_team_id and str(prior.winner_team_id) == str(winner_team_id):
        prior.status = "accepted"
        submission.status = "accepted"
        _advance_winner(event, match, winner_team_id)
    elif prior and prior.winner_team_id and winner_team_id and str(prior.winner_team_id) != str(winner_team_id):
        match.status = MatchStatus.DISPUTED
        db.session.add(MatchDispute(
            event_id=event.id,
            match_id=match.id,
            team_id=team_id,
            opened_by_user=int(user_id),
            reason="Captain result mismatch",
        ))
    else:
        match.status = MatchStatus.AWAITING_RESULTS
    db.session.commit()
    return jsonify(_match_payload(match)), 201


@tournament_engine_bp.post("/events/<uuid:event_id>/matches/<uuid:match_id>/disputes")
def open_match_dispute(event_id, match_id):
    body = _body()
    user_id = body.get("user_id")
    team_id = body.get("team_id")
    if user_id is None or not team_id:
        return jsonify({"error": "user_id and team_id required"}), 400
    if not _ensure_team_member(team_id, user_id):
        return jsonify({"error": "only match team members can dispute"}), 403
    match = TournamentMatch.query.filter_by(id=match_id, event_id=event_id).first_or_404()
    if str(team_id) not in {str(match.team_a_id), str(match.team_b_id)}:
        return jsonify({"error": "team_id must be one of the match teams"}), 400
    match.status = MatchStatus.DISPUTED
    db.session.add(MatchDispute(
        event_id=event_id,
        match_id=match.id,
        opened_by_user=int(user_id),
        team_id=team_id,
        reason=body.get("reason"),
    ))
    db.session.commit()
    return jsonify(_match_payload(match)), 201


@tournament_engine_bp.post("/events/<uuid:event_id>/matches/<uuid:match_id>/veto")
def add_map_veto(event_id, match_id):
    body = _body()
    user_id = body.get("user_id")
    team_id = body.get("team_id")
    map_name = body.get("map_name")
    action = body.get("action", "ban")
    if user_id is None or not team_id or not map_name:
        return jsonify({"error": "user_id, team_id and map_name required"}), 400
    if action not in {"ban", "pick"}:
        return jsonify({"error": "action must be ban or pick"}), 400
    if not _ensure_captain(team_id, user_id):
        return jsonify({"error": "only team captains can veto maps"}), 403
    event = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    match = TournamentMatch.query.filter_by(id=match_id, event_id=event_id).first_or_404()
    if str(team_id) not in {str(match.team_a_id), str(match.team_b_id)}:
        return jsonify({"error": "team_id must be one of the match teams"}), 400
    pool = match.map_pool or event.map_pool or DEFAULT_VALORANT_MAP_POOL
    if map_name not in pool:
        return jsonify({"error": "map_name is not in the match map pool"}), 400
    existing = MapVetoAction.query.filter_by(match_id=match.id).order_by(MapVetoAction.action_order.asc()).all()
    if any(v.map_name == map_name for v in existing):
        return jsonify({"error": "map already vetoed or picked"}), 409
    db.session.add(MapVetoAction(
        event_id=event.id,
        match_id=match.id,
        team_id=team_id,
        actor_user_id=int(user_id),
        action=action,
        map_name=map_name,
        action_order=len(existing) + 1,
    ))
    remaining = [m for m in pool if m not in {v.map_name for v in existing} and m != map_name]
    if len(remaining) == 1:
        match.map_name = remaining[0]
        match.lobby_instructions = _build_lobby_instructions(event, match)
    db.session.commit()
    return jsonify(_match_payload(match)), 201
