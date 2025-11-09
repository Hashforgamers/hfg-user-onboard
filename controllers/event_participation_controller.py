from flask import Blueprint, request, jsonify
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from db.extensions import db
from models.event import Event
from models.team import Team
from models.teamMember import TeamMember
from models.registration import Registration
from services.payment_service import create_payment_intent, verify_webhook


event_participation_bp = Blueprint("event_participation", __name__, url_prefix="/api")

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
        eventid=e.id,
        teamname=body.get("name"),  # source of name from request
        createdbyuser=int(uid),
        isindividual=isindividual
    )
    db.session.add(t)
    db.session.flush()
    db.session.add(TeamMember(teamid=t.id, userid=int(uid), role="captain"))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "team name already exists"}), 409
    return jsonify({"team_id": str(t.id), "name": t.name}), 201

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
    return jsonify({"ok": True}), 201

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
    is_member = TeamMember.query.filter_by(team_id=team_id, user_id=int(uid)).first() is not None
    if not is_member:
        return jsonify({"error": "only team member can register"}), 403

    team_count = db.session.query(func.count(Team.id)).filter(Team.event_id == e.id).scalar()
    if e.capacity_team and team_count >= e.capacity_team:
        return jsonify({"error": "team capacity reached"}), 409

    player_count = db.session.query(func.count(TeamMember.user_id)).join(Team, Team.id == TeamMember.team_id).filter(Team.event_id == e.id).scalar()
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

    if (e.registration_fee or 0) > 0:
        intent = create_payment_intent(
            amount=float(e.registration_fee),
            currency=e.currency or "INR",
            metadata={"event_id": str(e.id), "registration_id": str(reg.id), "team_id": str(team_id), "user_id": int(uid)}
        )
        return jsonify({
            "registration_id": str(reg.id),
            "payment_required": True,
            "payment": intent
        }), 201

    return jsonify({"registration_id": str(reg.id), "payment_required": False}), 201

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
