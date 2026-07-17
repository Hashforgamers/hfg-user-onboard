from flask import Blueprint, current_app, request, jsonify
from sqlalchemy import func, text
from datetime import datetime
from zoneinfo import ZoneInfo
from db.extensions import db
from models.event import Event
from models.team import Team
from services.security import decode_user, extract_bearer_token
import jwt
import time


event_public_bp = Blueprint("event_public", __name__, url_prefix="/api")

IST = ZoneInfo("Asia/Kolkata")
_EVENT_PUBLIC_CACHE = {}
_EVENT_PUBLIC_CACHE_MAX_SIZE = 5000


def _optional_request_user_id():
    """Return the authenticated app user when a valid Bearer token is supplied."""
    token = extract_bearer_token()
    if not token:
        return None

    try:
        claims = jwt.decode(
            token,
            current_app.config["JWT_SECRET_KEY"],
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "uuid"]},
        )
        user_id = decode_user(claims["uuid"], current_app.config["ENCRYPT_PRIVATE_KEY"])
        return int(user_id)
    except (KeyError, TypeError, ValueError, jwt.InvalidTokenError):
        return None
    except Exception:
        current_app.logger.warning("Could not resolve optional public-event authentication")
        return None


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

    viewer_user_id = _optional_request_user_id()
    cache_ttl_sec = 60
    cache_key = f"public:{vendor_id}:{flag_filter}:{limit}:viewer:{viewer_user_id or 'anonymous'}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    cafe_sql = """
        SELECT
            'cafe' AS source,
            e.id,
            e.vendor_id,
            NULL::bigint AS host_user_id,
            e.title,
            e.description,
            e.start_at,
            e.end_at,
            e.registration_fee,
            e.currency,
            e.game,
            e.format,
            e.prize_pool,
            e.team_size,
            e.match_rules,
            e.region,
            e.server,
            e.map_pool,
            e.veto_mode,
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
        cafe_sql += """
          AND (
            CASE
                WHEN now() < e.start_at THEN 'upcoming'
                WHEN now() BETWEEN e.start_at AND e.end_at THEN 'live'
                ELSE 'completed'
            END = :flag_filter
          )
        """

    community_sql = """
        SELECT
            'community' AS source,
            ct.id,
            NULL::bigint AS vendor_id,
            ct.host_user_id,
            ct.title,
            ct.description,
            ct.tournament_start_at AS start_at,
            COALESCE(ct.tournament_end_at, ct.tournament_start_at) AS end_at,
            ct.entry_fee AS registration_fee,
            ct.currency,
            ct.game,
            ct.tournament_type AS format,
            ct.prize_pool,
            CASE
                WHEN ct.team_mode = 'solo' THEN 1
                ELSE NULL
            END AS team_size,
            ct.rules AS match_rules,
            NULL::varchar AS region,
            NULL::varchar AS server,
            '[]'::jsonb AS map_pool,
            'none'::varchar AS veto_mode,
            COALESCE(cfa.file_url, ct.banner_url) AS banner_image_url,
            CASE
                WHEN ct.status = 'completed' THEN 'completed'
                WHEN now() < ct.tournament_start_at THEN 'upcoming'
                WHEN now() BETWEEN ct.tournament_start_at AND COALESCE(ct.tournament_end_at, ct.tournament_start_at) THEN 'live'
                ELSE 'completed'
            END AS flag
        FROM community_tournaments ct
        LEFT JOIN community_file_assets cfa ON cfa.id = ct.banner_asset_id
        WHERE ct.visibility = true
          AND ct.status IN ('published', 'registration_open', 'registration_closed', 'live', 'completed')
          AND :vendor_id IS NULL
    """
    if flag_filter:
        community_sql += """
          AND (
            CASE
                WHEN ct.status = 'completed' THEN 'completed'
                WHEN now() < ct.tournament_start_at THEN 'upcoming'
                WHEN now() BETWEEN ct.tournament_start_at AND COALESCE(ct.tournament_end_at, ct.tournament_start_at) THEN 'live'
                ELSE 'completed'
            END = :flag_filter
          )
        """

    sql = f"""
        SELECT *
        FROM (
            {cafe_sql}
            UNION ALL
            {community_sql}
        ) public_events
        ORDER BY start_at ASC
        LIMIT :limit
    """

    rows = db.session.execute(
        text(sql),
        {"vendor_id": vendor_id, "flag_filter": flag_filter or None, "limit": limit}
    ).mappings().all()

    payload = [
        {
            "id": str(r["id"]),
            "source": r["source"],
            "vendor_id": r["vendor_id"],
            "host_user_id": r["host_user_id"],
            "can_manage": bool(
                viewer_user_id
                and r["source"] == "community"
                and r["host_user_id"] is not None
                and int(r["host_user_id"]) == viewer_user_id
            ),
            "title": r["title"],
            "description": r["description"],
            "start_at": r["start_at"].isoformat() if r["start_at"] else None,
            "end_at": r["end_at"].isoformat() if r["end_at"] else None,
            "registration_fee": float(r["registration_fee"] or 0),
            "currency": r["currency"],
            "game": r["game"],
            "format": r["format"],
            "prize_pool": float(r["prize_pool"] or 0),
            "team_size": r["team_size"],
            "match_rules": r["match_rules"],
            "region": r["region"],
            "server": r["server"],
            "map_pool": r["map_pool"] or [],
            "veto_mode": r["veto_mode"],
            "banner_image_url": r["banner_image_url"],
            "flag": r["flag"],
        }
        for r in rows
    ]

    if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
        _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
    _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}

    return jsonify(payload), 200


@event_public_bp.get("/gamers/<int:user_id>/profile")
def get_public_gamer_profile(user_id):
    """Public, display-safe gamer profile for tournament screens."""
    row = db.session.execute(text("""
        SELECT
            u.id,
            u.name AS display_name,
            u.game_username,
            u.avatar_path AS avatar_url,
            u.created_at AS member_since,
            COALESCE(registrations.tournaments_joined, 0)::int AS tournaments_joined,
            COALESCE(hosted.tournaments_hosted, 0)::int AS tournaments_hosted,
            COALESCE(hosted.tournaments_completed, 0)::int AS tournaments_completed,
            COALESCE(results.wins, 0)::int AS wins,
            COALESCE(results.podium_finishes, 0)::int AS podium_finishes,
            CASE WHEN hv.verification_status = 'verified' THEN true ELSE false END AS is_verified_host,
            CASE WHEN hv.verification_status = 'verified' THEN hv.host_tier ELSE NULL END AS host_tier,
            CASE WHEN hv.verification_status = 'verified' THEN hv.average_rating ELSE NULL END AS average_rating,
            CASE WHEN hv.verification_status = 'verified' THEN hv.completion_rate ELSE NULL END AS completion_rate,
            CASE WHEN hv.verification_status = 'verified' THEN hv.on_time_payout_rate ELSE NULL END AS on_time_payout_rate
        FROM users u
        LEFT JOIN community_host_verifications hv ON hv.user_id = u.id
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS tournaments_joined
            FROM community_tournament_registrations ctr
            WHERE ctr.user_id = u.id
              AND ctr.status = 'confirmed'
        ) registrations ON true
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) AS tournaments_hosted,
                COUNT(*) FILTER (WHERE ct.status = 'completed') AS tournaments_completed
            FROM community_tournaments ct
            WHERE ct.host_user_id = u.id
        ) hosted ON true
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE ctp.rank = 1) AS wins,
                COUNT(*) FILTER (WHERE ctp.rank BETWEEN 1 AND 3) AS podium_finishes
            FROM community_tournament_payouts ctp
            WHERE ctp.user_id = u.id
              AND ctp.status NOT IN ('cancelled', 'failed')
        ) results ON true
        WHERE u.id = :user_id
          AND u.parent_type = 'user'
        LIMIT 1
    """), {"user_id": user_id}).mappings().first()

    if not row:
        return jsonify({"message": "Gamer not found"}), 404

    return jsonify({
        "id": int(row["id"]),
        "display_name": row["display_name"] or "",
        "game_username": row["game_username"] or "",
        "avatar_url": row["avatar_url"] or None,
        "member_since": row["member_since"].isoformat() if row["member_since"] else None,
        "tournament_stats": {
            "tournaments_joined": int(row["tournaments_joined"]),
            "tournaments_hosted": int(row["tournaments_hosted"]),
            "tournaments_completed": int(row["tournaments_completed"]),
            "wins": int(row["wins"]),
            "podium_finishes": int(row["podium_finishes"]),
        },
        "host": {
            "is_verified": bool(row["is_verified_host"]),
            "tier": row["host_tier"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else None,
            "completion_rate": float(row["completion_rate"]) if row["completion_rate"] is not None else None,
            "on_time_payout_rate": float(row["on_time_payout_rate"]) if row["on_time_payout_rate"] is not None else None,
        },
    }), 200


@event_public_bp.get("/events/<uuid:event_id>")
def get_event(event_id):
    """
    Single event detail — no auth required.
    Returns full event info including team count and flag.
    """
    viewer_user_id = _optional_request_user_id()
    cache_ttl_sec = 60
    cache_key = f"event:{event_id}:viewer:{viewer_user_id or 'anonymous'}"
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
            e.game,
            e.format,
            e.prize_pool,
            e.team_size,
            e.match_rules,
            e.region,
            e.server,
            e.check_in_starts_at,
            e.check_in_ends_at,
            e.map_pool,
            e.veto_mode,
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
        community_row = db.session.execute(text("""
            SELECT
                ct.id,
                NULL::bigint AS vendor_id,
                ct.host_user_id,
                ct.title,
                ct.description,
                ct.tournament_start_at AS start_at,
                COALESCE(ct.tournament_end_at, ct.tournament_start_at) AS end_at,
                ct.entry_fee AS registration_fee,
                ct.currency,
                ct.game,
                ct.tournament_type AS format,
                ct.prize_pool,
                CASE
                    WHEN ct.team_mode = 'solo' THEN 1
                    ELSE NULL
                END AS team_size,
                ct.rules AS match_rules,
                NULL::varchar AS region,
                NULL::varchar AS server,
                NULL::timestamptz AS check_in_starts_at,
                NULL::timestamptz AS check_in_ends_at,
                '[]'::jsonb AS map_pool,
                'none'::varchar AS veto_mode,
                NULL::integer AS capacity_team,
                ct.max_players AS capacity_player,
                1 AS min_team_size,
                CASE
                    WHEN ct.team_mode = 'solo' THEN 1
                    ELSE NULL
                END AS max_team_size,
                ct.team_mode = 'solo' AS allow_solo,
                ct.team_mode = 'solo' AS allow_individual,
                ct.registration_end_at AS registration_deadline,
                COALESCE(cfa.file_url, ct.banner_url) AS banner_image_url,
                ct.registered_players_count AS team_count,
                CASE
                    WHEN ct.status = 'completed' THEN 'completed'
                    WHEN now() < ct.tournament_start_at THEN 'upcoming'
                    WHEN now() BETWEEN ct.tournament_start_at AND COALESCE(ct.tournament_end_at, ct.tournament_start_at) THEN 'live'
                    ELSE 'completed'
                END AS flag
            FROM community_tournaments ct
            LEFT JOIN community_file_assets cfa ON cfa.id = ct.banner_asset_id
            WHERE ct.id = :event_id
              AND ct.visibility = true
              AND ct.status IN ('published', 'registration_open', 'registration_closed', 'live', 'completed')
            LIMIT 1
        """), {"event_id": str(event_id)}).mappings().first()
        if not community_row:
            return jsonify({"message": "Not Found"}), 404
        row = community_row
        source = "community"
    else:
        source = "cafe"

    payload = {
        "id": str(row["id"]),
        "source": source,
        "vendor_id": row["vendor_id"],
        "host_user_id": row.get("host_user_id"),
        "can_manage": bool(
            viewer_user_id
            and source == "community"
            and row.get("host_user_id") is not None
            and int(row["host_user_id"]) == viewer_user_id
        ),
        "title": row["title"],
        "description": row["description"],
        "start_at": row["start_at"].isoformat() if row["start_at"] else None,
        "end_at": row["end_at"].isoformat() if row["end_at"] else None,
        "registration_fee": float(row["registration_fee"] or 0),
        "currency": row["currency"],
        "game": row["game"],
        "format": row["format"],
        "prize_pool": float(row["prize_pool"] or 0),
        "team_size": row["team_size"],
        "match_rules": row["match_rules"],
        "region": row["region"],
        "server": row["server"],
        "check_in_starts_at": row["check_in_starts_at"].isoformat() if row["check_in_starts_at"] else None,
        "check_in_ends_at": row["check_in_ends_at"].isoformat() if row["check_in_ends_at"] else None,
        "map_pool": row["map_pool"] or [],
        "veto_mode": row["veto_mode"],
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

    cache_ttl_sec = 60
    cache_key = f"leaderboard:{event_id}:{stage}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    e = Event.query.filter_by(id=event_id, visibility=True).first()
    if not e:
        community_tournament = db.session.execute(
            text("""
                SELECT id, title
                FROM community_tournaments
                WHERE id = :event_id
                  AND visibility = true
                  AND status IN ('published', 'registration_open', 'registration_closed', 'live', 'completed')
                LIMIT 1
            """),
            {"event_id": str(event_id)},
        ).mappings().first()
        if not community_tournament:
            payload = {
                "event_id": str(event_id),
                "event_title": None,
                "source": None,
                "stage": "provisional" if stage == "auto" else stage,
                "availability": "not_available_yet",
                "leaderboard": [],
            }
            if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
                _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
            _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
            return jsonify(payload), 200

        def _fetch_community_winners():
            return db.session.execute(
                text("""
                    SELECT
                        p.user_id,
                        u.name AS user_name,
                        u.game_username,
                        p.rank,
                        p.amount,
                        p.currency,
                        p.status,
                        p.created_at
                    FROM community_tournament_payouts p
                    LEFT JOIN users u ON u.id = p.user_id
                    WHERE p.tournament_id = :event_id
                      AND p.status NOT IN ('cancelled', 'failed')
                    ORDER BY p.rank ASC NULLS LAST, p.amount DESC, u.name ASC
                """),
                {"event_id": str(event_id)},
            ).mappings().all()

        def _fetch_community_provisional():
            return db.session.execute(
                text("""
                    SELECT DISTINCT ON (COALESCE(r.rank, 2147483647), r.winner_user_id, r.id)
                        r.id AS result_id,
                        r.winner_user_id AS user_id,
                        u.name AS user_name,
                        u.game_username,
                        r.rank,
                        r.score,
                        r.status,
                        r.verified_at,
                        r.created_at
                    FROM community_match_results r
                    LEFT JOIN users u ON u.id = r.winner_user_id
                    WHERE r.tournament_id = :event_id
                      AND r.status IN ('verified', 'admin_overridden')
                      AND (r.rank IS NOT NULL OR r.winner_user_id IS NOT NULL)
                    ORDER BY COALESCE(r.rank, 2147483647), r.winner_user_id, r.id, r.verified_at DESC NULLS LAST
                """),
                {"event_id": str(event_id)},
            ).mappings().all()

        selected_stage = stage
        rows = []
        if stage == "auto":
            rows = _fetch_community_winners()
            if rows:
                selected_stage = "winners"
            else:
                rows = _fetch_community_provisional()
                selected_stage = "provisional"
        elif stage == "winners":
            rows = _fetch_community_winners()
        else:
            rows = _fetch_community_provisional()

        if selected_stage == "winners":
            leaderboard = [
                {
                    "team_id": None,
                    "team_name": r["game_username"] or r["user_name"] or f"User {r['user_id']}",
                    "user_id": int(r["user_id"]),
                    "user_name": r["user_name"],
                    "game_username": r["game_username"],
                    "rank": int(r["rank"]) if r["rank"] is not None else None,
                    "amount": float(r["amount"] or 0),
                    "currency": r["currency"],
                    "payout_status": r["status"],
                }
                for r in rows
            ]
        else:
            leaderboard = [
                {
                    "team_id": None,
                    "team_name": r["game_username"] or r["user_name"] or (f"User {r['user_id']}" if r["user_id"] else "Unassigned"),
                    "user_id": int(r["user_id"]) if r["user_id"] else None,
                    "user_name": r["user_name"],
                    "game_username": r["game_username"],
                    "rank": int(r["rank"]) if r["rank"] is not None else None,
                    "score": r["score"],
                    "result_id": str(r["result_id"]),
                    "result_status": r["status"],
                }
                for r in rows
            ]

        payload = {
            "event_id": str(community_tournament["id"]),
            "event_title": community_tournament["title"],
            "source": "community",
            "stage": selected_stage,
            "availability": "available" if leaderboard else "not_available_yet",
            "leaderboard": leaderboard,
        }
        if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
            _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
        _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
        return jsonify(payload), 200

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
        "source": "cafe",
        "stage": selected_stage,
        "availability": "available" if rows else "not_available_yet",
        "leaderboard": [
            {
                "team_id": str(r["team_id"]),
                "team_name": r["team_name"],
                "user_id": None,
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
    cache_ttl_sec = 60
    cache_key = f"provisional:{event_id}"
    now_ts = time.time()
    cached = _EVENT_PUBLIC_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    e = Event.query.filter_by(id=event_id, visibility=True).first()
    if not e:
        community_tournament = db.session.execute(
            text("""
                SELECT id, title
                FROM community_tournaments
                WHERE id = :event_id
                  AND visibility = true
                  AND status IN ('published', 'registration_open', 'registration_closed', 'live', 'completed')
                LIMIT 1
            """),
            {"event_id": str(event_id)},
        ).mappings().first()
        if not community_tournament:
            return jsonify({"message": "Not Found"}), 404

        rows = db.session.execute(
            text("""
                SELECT
                    r.id,
                    r.tournament_id AS event_id,
                    r.winner_user_id AS user_id,
                    u.name AS user_name,
                    u.game_username,
                    r.rank AS proposed_rank,
                    r.submitted_by_user_id,
                    r.score,
                    r.status,
                    COALESCE(r.verified_at, r.created_at) AS published_at
                FROM community_match_results r
                LEFT JOIN users u ON u.id = r.winner_user_id
                WHERE r.tournament_id = :event_id
                  AND r.status IN ('verified', 'admin_overridden')
                  AND (r.rank IS NOT NULL OR r.winner_user_id IS NOT NULL)
                ORDER BY COALESCE(r.rank, 2147483647), u.name ASC, r.created_at ASC
            """),
            {"event_id": str(event_id)}
        ).mappings().all()

        payload = {
            "event_id": str(community_tournament["id"]),
            "event_title": community_tournament["title"],
            "source": "community",
            "result_type": "provisional",
            "results": [
                {
                    "id": str(r["id"]),
                    "event_id": str(r["event_id"]),
                    "team_id": None,
                    "team_name": r["game_username"] or r["user_name"] or (f"User {r['user_id']}" if r["user_id"] else "Unassigned"),
                    "user_id": int(r["user_id"]) if r["user_id"] else None,
                    "user_name": r["user_name"],
                    "game_username": r["game_username"],
                    "proposed_rank": int(r["proposed_rank"]) if r["proposed_rank"] is not None else None,
                    "submitted_by_vendor": None,
                    "submitted_by_user_id": int(r["submitted_by_user_id"]) if r["submitted_by_user_id"] else None,
                    "score": r["score"],
                    "status": r["status"],
                    "published_at": r["published_at"].isoformat() if r["published_at"] else None
                }
                for r in rows
            ]
        }
        if len(_EVENT_PUBLIC_CACHE) >= _EVENT_PUBLIC_CACHE_MAX_SIZE:
            _EVENT_PUBLIC_CACHE.pop(next(iter(_EVENT_PUBLIC_CACHE)))
        _EVENT_PUBLIC_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
        return jsonify(payload), 200

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
        "source": "cafe",
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
