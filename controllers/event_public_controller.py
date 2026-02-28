from flask import Blueprint, request, jsonify
from sqlalchemy import func, text
from datetime import datetime
from zoneinfo import ZoneInfo
from db.extensions import db
from models.event import Event
from models.team import Team
import time


event_public_bp = Blueprint("event_public", __name__, url_prefix="/api")

IST = ZoneInfo("Asia/Kolkata")
_EVENT_PUBLIC_CACHE = {}
_EVENT_PUBLIC_CACHE_MAX_SIZE = 5000


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
    vendor_id = request.args.get("vendor_id", type=int)
    flag_filter = (request.args.get("flag") or "").strip().lower()
    limit = request.args.get("limit", default=30, type=int)
    if limit <= 0 or limit > 100:
        return jsonify({"error": "limit must be between 1 and 100"}), 400
    if flag_filter and flag_filter not in {"live", "upcoming", "completed"}:
        return jsonify({"error": "invalid flag. use live|upcoming|completed"}), 400

    cache_ttl_sec = 10
    cache_key = f"public:{vendor_id}:{flag_filter}:{limit}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    sql = """
        SELECT
            e.id,
            e.vendor_id,
            e.title,
            e.description,
            e.start_at,
            e.end_at,
            e.registration_fee,
            e.currency,
            e.banner_image_url,
            CASE
                WHEN now() < e.start_at THEN 'upcoming'
                WHEN now() BETWEEN e.start_at AND e.end_at THEN 'live'
                ELSE 'completed'
            END AS flag
        FROM events e
        WHERE e.visibility = true
          AND e.status IN ('published', 'ongoing')
          AND (:vendor_id IS NULL OR e.vendor_id = :vendor_id)
    """
    if flag_filter:
        sql += """
          AND (
            CASE
                WHEN now() < e.start_at THEN 'upcoming'
                WHEN now() BETWEEN e.start_at AND e.end_at THEN 'live'
                ELSE 'completed'
            END = :flag_filter
          )
        """
    sql += " ORDER BY e.start_at ASC LIMIT :limit"

    rows = db.session.execute(
        text(sql),
        {"vendor_id": vendor_id, "flag_filter": flag_filter or None, "limit": limit}
    ).mappings().all()

    payload = [
        {
            "id": str(r["id"]),
            "vendor_id": r["vendor_id"],
            "title": r["title"],
            "description": r["description"],
            "start_at": r["start_at"].isoformat() if r["start_at"] else None,
            "end_at": r["end_at"].isoformat() if r["end_at"] else None,
            "registration_fee": float(r["registration_fee"] or 0),
            "currency": r["currency"],
            "banner_image_url": r["banner_image_url"],
            "flag": r["flag"],
        }
        for r in rows
    ]

    if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
        _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
    _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}

    return jsonify(payload), 200


@event_public_bp.get("/events/<uuid:event_id>")
def get_event(event_id):
    """
    Single event detail — no auth required.
    Returns full event info including team count and flag.
    """
    cache_ttl_sec = 10
    cache_key = f"event:{event_id}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    row = db.session.execute(text("""
        SELECT
            e.id,
            e.vendor_id,
            e.title,
            e.description,
            e.start_at,
            e.end_at,
            e.registration_fee,
            e.currency,
            e.capacity_team,
            e.capacity_player,
            e.min_team_size,
            e.max_team_size,
            e.allow_solo,
            e.allow_individual,
            e.registration_deadline,
            e.banner_image_url,
            COALESCE(tc.team_count, 0) AS team_count,
            CASE
                WHEN now() < e.start_at THEN 'upcoming'
                WHEN now() BETWEEN e.start_at AND e.end_at THEN 'live'
                ELSE 'completed'
            END AS flag
        FROM events e
        LEFT JOIN (
            SELECT event_id, COUNT(*)::int AS team_count
            FROM teams
            GROUP BY event_id
        ) tc ON tc.event_id = e.id
        WHERE e.id = :event_id AND e.visibility = true
        LIMIT 1
    """), {"event_id": str(event_id)}).mappings().first()
    if not row:
        return jsonify({"message": "Not Found"}), 404

    payload = {
        "id": str(row["id"]),
        "vendor_id": row["vendor_id"],
        "title": row["title"],
        "description": row["description"],
        "start_at": row["start_at"].isoformat() if row["start_at"] else None,
        "end_at": row["end_at"].isoformat() if row["end_at"] else None,
        "registration_fee": float(row["registration_fee"] or 0),
        "currency": row["currency"],
        "capacity_team": row["capacity_team"],
        "capacity_player": row["capacity_player"],
        "min_team_size": row["min_team_size"],
        "max_team_size": row["max_team_size"],
        "allow_solo": row["allow_solo"],
        "allow_individual": row["allow_individual"],
        "registration_deadline": row["registration_deadline"].isoformat() if row["registration_deadline"] else None,
        "team_count": int(row["team_count"] or 0),
        "banner_image_url": row["banner_image_url"],
        "flag": row["flag"],
    }
    if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
        _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
    _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
    return jsonify(payload), 200


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

    cache_ttl_sec = 10
    cache_key = f"leaderboard:{event_id}:{stage}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

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

    payload = {
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
    }
    if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
        _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
    _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
    return jsonify(payload), 200


@event_public_bp.get("/events/<uuid:event_id>/results/provisional")
def get_event_provisional_results(event_id):
    """
    Specific event provisional results.
    Public endpoint.
    """
    cache_ttl_sec = 10
    cache_key = f"provisional:{event_id}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()

    rows = db.session.execute(
        text("""
            SELECT
                pr.id,
                pr.event_id,
                pr.team_id,
                t.team_name,
                pr.proposed_rank,
                pr.submitted_by_vendor,
                pr.published_at
            FROM provisional_results pr
            JOIN teams t ON t.id = pr.team_id
            WHERE pr.event_id = :event_id
            ORDER BY pr.proposed_rank ASC, t.team_name ASC
        """),
        {"event_id": str(e.id)}
    ).mappings().all()

    payload = {
        "event_id": str(e.id),
        "event_title": e.title,
        "result_type": "provisional",
        "results": [
            {
                "id": str(r["id"]),
                "event_id": str(r["event_id"]),
                "team_id": str(r["team_id"]),
                "team_name": r["team_name"],
                "proposed_rank": int(r["proposed_rank"]),
                "submitted_by_vendor": int(r["submitted_by_vendor"]),
                "published_at": r["published_at"].isoformat() if r["published_at"] else None
            }
            for r in rows
        ]
    }
    if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
        _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
    _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
    return jsonify(payload), 200
