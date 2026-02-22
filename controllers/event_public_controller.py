from flask import Blueprint, request, jsonify
from sqlalchemy import func, text
from datetime import datetime
from zoneinfo import ZoneInfo
from db.extensions import db
from models.event import Event
from models.team import Team


event_public_bp = Blueprint("event_public", __name__, url_prefix="/api")

IST = ZoneInfo("Asia/Kolkata")


def _event_flag(start_at, end_at):
    """
    Compute display flag in IST — not UTC, not server time.
      now < start              → 'upcoming'
      start <= now <= end      → 'live'
      now > end                → 'completed'
    """
    now = datetime.now(IST)

    # Normalize — if DB stored naive datetime, treat it as IST
    start = start_at.astimezone(IST) if start_at.tzinfo else start_at.replace(tzinfo=IST)
    end   = end_at.astimezone(IST)   if end_at.tzinfo   else end_at.replace(tzinfo=IST)

    if now < start:
        return "upcoming"
    elif start <= now <= end:
        return "live"
    else:
        return "completed"


@event_public_bp.get("/events/public")
def list_public_events():
    """
    Public event listing — no auth required.
    Query params:
      ?vendor_id=14   (optional — filter by vendor)
      ?flag=live      (optional — filter by flag: live | upcoming | completed)
    """
    vendor_id  = request.args.get("vendor_id", type=int)
    flag_filter = request.args.get("flag")

    q = Event.query.filter(
        Event.visibility == True,
        Event.status.in_(["published", "ongoing"])
    )

    if vendor_id:
        q = q.filter(Event.vendor_id == vendor_id)

    items = q.order_by(Event.start_at.asc()).all()

    result = []
    for e in items:
        flag = _event_flag(e.start_at, e.end_at)

        # apply optional flag filter
        if flag_filter and flag != flag_filter:
            continue

        result.append({
            "id":               str(e.id),
            "vendor_id":        e.vendor_id,
            "title":            e.title,
            "description":      e.description,
            "start_at":         e.start_at.isoformat(),
            "end_at":           e.end_at.isoformat(),
            "registration_fee": float(e.registration_fee or 0),
            "currency":         e.currency,
            "banner_image_url": e.banner_image_url,
            "flag":             flag,
        })

    return jsonify(result), 200


@event_public_bp.get("/events/<uuid:event_id>")
def get_event(event_id):
    """
    Single event detail — no auth required.
    Returns full event info including team count and flag.
    """
    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()

    team_count = db.session.query(func.count(Team.id)).filter(
        Team.event_id == e.id
    ).scalar()

    return jsonify({
        "id":               str(e.id),
        "vendor_id":        e.vendor_id,
        "title":            e.title,
        "description":      e.description,
        "start_at":         e.start_at.isoformat(),
        "end_at":           e.end_at.isoformat(),
        "registration_fee": float(e.registration_fee or 0),
        "currency":         e.currency,
        "capacity_team":    e.capacity_team,
        "capacity_player":  getattr(e, "capacity_player", None),
        "min_team_size":    e.min_team_size,
        "max_team_size":    e.max_team_size,
        "allow_solo":       e.allow_solo,
        "allow_individual": e.allow_individual,
        "registration_deadline": e.registration_deadline.isoformat() if e.registration_deadline else None,
        "team_count":       int(team_count),
        "banner_image_url": e.banner_image_url,
        "flag":             _event_flag(e.start_at, e.end_at),
    }), 200


@event_public_bp.get("/events/<uuid:event_id>/leaderboard")
def get_event_leaderboard(event_id):
    """
    Specific event leaderboard.
    Query params:
      ?stage=auto|winners|provisional
        auto        -> winners if available, else provisional
        winners     -> final published winners leaderboard
        provisional -> provisional leaderboard
    """
    stage = (request.args.get("stage") or "auto").strip().lower()
    if stage not in {"auto", "winners", "provisional"}:
        return jsonify({"error": "invalid stage. use auto|winners|provisional"}), 400

    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()

    def _fetch_rows(table_name, rank_column):
        sql = text(f"""
            SELECT
                t.id AS team_id,
                t.team_name AS team_name,
                lb.{rank_column} AS rank
            FROM {table_name} lb
            JOIN teams t ON t.id = lb.team_id
            WHERE lb.event_id = :event_id
            ORDER BY lb.{rank_column} ASC, t.team_name ASC
        """)
        return db.session.execute(sql, {"event_id": str(e.id)}).mappings().all()

    selected_stage = stage
    rows = []

    if stage == "auto":
        rows = _fetch_rows("winners", "rank")
        if rows:
            selected_stage = "winners"
        else:
            rows = _fetch_rows("provisional_results", "proposed_rank")
            selected_stage = "provisional"
    elif stage == "winners":
        rows = _fetch_rows("winners", "rank")
    else:
        rows = _fetch_rows("provisional_results", "proposed_rank")

    return jsonify({
        "event_id": str(e.id),
        "event_title": e.title,
        "stage": selected_stage,
        "leaderboard": [
            {
                "team_id": str(r["team_id"]),
                "team_name": r["team_name"],
                "rank": int(r["rank"])
            }
            for r in rows
        ]
    }), 200
