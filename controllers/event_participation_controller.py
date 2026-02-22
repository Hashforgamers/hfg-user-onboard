from flask import Blueprint, request, jsonify
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from zoneinfo import ZoneInfo
from db.extensions import db
from models.event import Event
from models.team import Team
from models.teamMember import TeamMember
from models.registration import Registration
from services.payment_service import create_payment_intent, verify_webhook


event_participation_bp = Blueprint("event_participation", __name__, url_prefix="/api")
IST = ZoneInfo("Asia/Kolkata")


def _event_flag(start_at, end_at):
    now = datetime.now(IST)
    start = start_at.astimezone(IST) if start_at.tzinfo else start_at.replace(tzinfo=IST)
    end = end_at.astimezone(IST) if end_at.tzinfo else end_at.replace(tzinfo=IST)

    if now < start:
        return "upcoming"
    if start <= now <= end:
        return "live"
    return "completed"

# Helpers: no JWT, read user_id from body
def _body():
    return request.get_json(silent=True) or {}

@event_participation_bp.post("/events/<uuid:event_id>/teams")
def create_team(event_id):
    body = _body()
    uid = body.get("user_id")
    if uid is None:
        return jsonify({"error": "user_id required"}), 400
    e = Event.query.filter_by(id=event_id, visibility=True, status="published").first_or_404()
    name = body.get("name")
    is_individual = bool(body.get("is_individual", False))
    if not name:
        return jsonify({"error": "name required"}), 400
    if is_individual and e.max_team_size != 1:
        return jsonify({"error": "event is not solo format"}), 400

    # Use teamname everywhere instead of name if this matches the DB schema
    t = Team(
        event_id=e.id,
        team_name=name,
        created_by_user=int(uid),
        is_individual=is_individual
    )
    db.session.add(t)
    db.session.flush()
    db.session.add(TeamMember(team_id=t.id, user_id=int(uid), role="captain"))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "team name already exists"}), 409
    return jsonify({"team_id": str(t.id), "name": t.team_name}), 201

@event_participation_bp.post("/events/<uuid:event_id>/teams/<uuid:team_id>/join")
def join_team(event_id, team_id):
    body = _body()
    uid = body.get("user_id")
    if uid is None:
        return jsonify({"error": "user_id required"}), 400

    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    t = Team.query.filter_by(id=team_id, event_id=e.id).first_or_404()

    size = TeamMember.query.filter_by(team_id=team_id).count()
    if t.is_individual or e.max_team_size == 1:
        return jsonify({"error": "individual team cannot accept members"}), 400
    if e.max_team_size and size >= e.max_team_size:
        return jsonify({"error": f"max team size {e.max_team_size} reached"}), 400

    db.session.add(TeamMember(team_id=team_id, user_id=int(uid), role="member"))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "already joined"}), 409

    return jsonify({
        "ok": True,
        "team_id": str(t.id),
        "team_name": t.team_name
    }), 201


@event_participation_bp.delete("/events/<uuid:event_id>/teams/<uuid:team_id>/leave")
def leave_team(event_id, team_id):
    body = _body()
    uid = body.get("user_id")
    if uid is None:
        return jsonify({"error": "user_id required"}), 400

    Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    tm = TeamMember.query.filter_by(team_id=team_id, user_id=int(uid)).first()
    if not tm:
        return jsonify({"error": "not a member"}), 404

    db.session.delete(tm)
    db.session.commit()

    return jsonify({"ok": True}), 200


@event_participation_bp.post("/events/<uuid:event_id>/register")
def register_team(event_id):
    body = _body()
    uid = body.get("user_id")
    team_id = body.get("team_id")
    if uid is None or not team_id:
        return jsonify({"error": "user_id and team_id required"}), 400

    e = Event.query.filter_by(id=event_id, visibility=True, status="published").first_or_404()
    t = Team.query.filter_by(id=team_id, event_id=e.id).first_or_404()

    is_member = TeamMember.query.filter_by(team_id=team_id, user_id=int(uid)).first() is not None
    if not is_member:
        return jsonify({"error": "only team member can register"}), 403

    team_count = db.session.query(func.count(Team.id)).filter(Team.event_id == e.id).scalar()
    if e.capacity_team and team_count >= e.capacity_team:
        return jsonify({"error": "team capacity reached"}), 409

    player_count = (
        db.session.query(func.count(TeamMember.user_id))
        .join(Team, Team.id == TeamMember.team_id)
        .filter(Team.event_id == e.id)
        .scalar()
    )

    cap_player = getattr(e, "capacity_player", None)
    if cap_player and player_count >= cap_player:
        return jsonify({"error": "player capacity reached"}), 409

    reg = Registration(
        event_id=e.id,
        team_id=team_id,
        contact_name=body.get("contact_name"),
        contact_phone=body.get("contact_phone"),
        contact_email=body.get("contact_email"),
        waiver_signed=bool(body.get("waiver_signed", False)),
        payment_status="pending" if (e.registration_fee or 0) > 0 else "paid",
        status="pending" if (e.registration_fee or 0) > 0 else "confirmed"
    )

    db.session.add(reg)
    db.session.commit()

    # Include team name in registration response
    if (e.registration_fee or 0) > 0:
        intent = create_payment_intent(
            amount=float(e.registration_fee),
            currency=e.currency or "INR",
            metadata={
                "event_id": str(e.id),
                "registration_id": str(reg.id),
                "team_id": str(team_id),
                "user_id": int(uid)
            }
        )
        return jsonify({
            "registration_id": str(reg.id),
            "team_name": t.team_name,
            "payment_required": True,
            "payment": intent
        }), 201

    return jsonify({
        "registration_id": str(reg.id),
        "team_name": t.team_name,
        "payment_required": False
    }), 201


@event_participation_bp.post("/payments/intent")
def make_payment_intent():
    body = _body()
    amount = body.get("amount")
    if amount is None:
        return jsonify({"error": "amount required"}), 400

    currency = body.get("currency", "INR")
    metadata = body.get("metadata", {})

    return jsonify(create_payment_intent(amount=float(amount), currency=currency, metadata=metadata)), 201


@event_participation_bp.post("/payments/webhook")
def payment_webhook():
    payload = request.get_data()
    sig = request.headers.get("X-Signature", "")
    ok, reg_id, status = verify_webhook(payload, sig)

    if not ok:
        return jsonify({"error": "invalid signature"}), 400

    reg = Registration.query.filter_by(id=reg_id).first()
    if not reg:
        return jsonify({"error": "registration not found"}), 404

    reg.payment_status = "paid" if status == "succeeded" else "failed"
    reg.status = "confirmed" if status == "succeeded" else "pending"

    db.session.commit()

    return jsonify({"ok": True}), 200

@event_participation_bp.get("/events/<uuid:event_id>/teams/<uuid:team_id>/members")
def get_team_members(event_id, team_id):
    # Ensure event exists and is visible
    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    
    # Ensure team exists for the event
    t = Team.query.filter_by(id=team_id, event_id=e.id).first_or_404()

    # Fetch members joined with user details (optional)
    members = (
        db.session.query(TeamMember)
        .filter(TeamMember.team_id == team_id)
        .all()
    )

    # Return a structured response
    return jsonify({
        "team_id": str(t.id),
        "team_name": t.team_name,
        "is_individual": t.is_individual,
        "members": [
            {
                "user_id": m.user_id,
                "role": m.role,
                "joined_at": m.created_at.isoformat() if hasattr(m, "created_at") and m.created_at else None
            }
            for m in members
        ]
    }), 200


@event_participation_bp.get("/users/<int:user_id>/teams")
def get_user_teams(user_id):
    """
    Get all teams a user belongs to, across all events.
    Optional query param:
      ?event_id=<uuid>   — filter to a specific event
    """
    event_id = request.args.get("event_id")

    q = (
        db.session.query(Team, TeamMember)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user_id)
    )

    if event_id:
        q = q.filter(Team.event_id == event_id)

    rows = q.all()

    if not rows:
        return jsonify([]), 200

    result = []
    for team, member in rows:
        # member count for this team
        member_count = TeamMember.query.filter_by(team_id=team.id).count()

        result.append({
            "team_id":        str(team.id),
            "team_name":      team.team_name,
            "event_id":       str(team.event_id),
            "is_individual":  team.is_individual,
            "role":           member.role,           # captain / member
            "joined_at":      member.joined_at.isoformat() if member.joined_at else None,
            "member_count":   member_count,
        })

    return jsonify(result), 200


@event_participation_bp.get("/users/<int:user_id>/tournaments/joined")
def get_user_joined_tournaments(user_id):
    rows = (
        db.session.query(TeamMember, Team, Event)
        .join(Team, Team.id == TeamMember.team_id)
        .join(Event, Event.id == Team.event_id)
        .filter(
            TeamMember.user_id == user_id,
            Event.visibility == True
        )
        .order_by(Event.start_at.asc(), TeamMember.joined_at.asc())
        .all()
    )

    grouped = {"live": [], "upcoming": [], "completed": []}
    if not rows:
        return jsonify(grouped), 200

    team_ids = [team.id for _, team, _ in rows]
    reg_rows = (
        Registration.query
        .filter(Registration.team_id.in_(team_ids))
        .order_by(Registration.created_at.desc())
        .all()
    )

    latest_reg_by_team = {}
    for reg in reg_rows:
        if reg.team_id not in latest_reg_by_team:
            latest_reg_by_team[reg.team_id] = reg

    grouped_map = {"live": {}, "upcoming": {}, "completed": {}}
    for tm, team, event in rows:
        flag = _event_flag(event.start_at, event.end_at)
        reg = latest_reg_by_team.get(team.id)

        event_key = str(event.id)
        if event_key not in grouped_map[flag]:
            grouped_map[flag][event_key] = {
                "id": str(event.id),
                "vendor_id": event.vendor_id,
                "title": event.title,
                "description": event.description,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat(),
                "registration_fee": float(event.registration_fee or 0),
                "currency": event.currency,
                "banner_image_url": event.banner_image_url,
                "flag": flag,
                "teams": []
            }

        grouped_map[flag][event_key]["teams"].append({
            "team_id": str(team.id),
            "team_name": team.team_name,
            "is_individual": team.is_individual,
            "role": tm.role,
            "joined_at": tm.joined_at.isoformat() if tm.joined_at else None,
            "registration_id": str(reg.id) if reg else None,
            "registration_status": reg.status if reg else None,
            "payment_status": reg.payment_status if reg else None,
            "registered_at": reg.created_at.isoformat() if reg and reg.created_at else None
        })

    grouped["live"] = list(grouped_map["live"].values())
    grouped["upcoming"] = list(grouped_map["upcoming"].values())
    grouped["completed"] = list(grouped_map["completed"].values())

    return jsonify(grouped), 200
