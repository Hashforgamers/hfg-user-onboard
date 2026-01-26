from flask import Blueprint, request, jsonify
from sqlalchemy import func
from db.extensions import db
from models.event import Event
from models.team import Team

event_public_bp = Blueprint("event_public", __name__, url_prefix="/api")

@event_public_bp.get("/events/public")
def list_public_events():
    vendor_id = request.args.get("vendor_id", type=int)
    q = Event.query.filter(Event.visibility == True, Event.status.in_(["published", "ongoing"]))
    if vendor_id:
        q = q.filter(Event.vendor_id == vendor_id)
    items = q.order_by(Event.start_at.asc()).all()
    return jsonify([{
        "id": str(e.id),
        "vendor_id": e.vendor_id,
        "title": e.title,
        "description": e.description,
        "start_at": e.start_at.isoformat(),
        "end_at": e.end_at.isoformat(),
        "registration_fee": float(e.registration_fee or 0),
        "currency": e.currency
    } for e in items]), 200

@event_public_bp.get("/events/<uuid:event_id>")
def get_event(event_id):
    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    team_count = db.session.query(func.count(Team.id)).filter(Team.event_id == e.id).scalar()
    return jsonify({
        "id": str(e.id),
        "vendor_id": e.vendor_id,
        "title": e.title,
        "description": e.description,
        "start_at": e.start_at.isoformat(),
        "end_at": e.end_at.isoformat(),
        "registration_fee": float(e.registration_fee or 0),
        "currency": e.currency,
        "capacity_team": e.capacity_team,
        "capacity_player": getattr(e, "capacity_player", None),
        "team_count": int(team_count),
        "allow_solo": e.allow_solo,
        "min_team_size": e.min_team_size,
        "max_team_size": e.max_team_size
    }), 200
