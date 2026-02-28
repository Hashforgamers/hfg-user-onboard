from flask import Blueprint, request, jsonify
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import os
import time
from db.extensions import db
from models.event import Event
from models.team import Team
from models.teamMember import TeamMember
from models.teamInvite import TeamInvite
from models.registration import Registration
from models.notification import Notification
from models.fcmToken import FCMToken
from models.user import User
from services.payment_service import create_payment_intent, verify_webhook
from services.firebase_service import send_notification


event_participation_bp = Blueprint("event_participation", __name__, url_prefix="/api")
IST = ZoneInfo("Asia/Kolkata")
_PUSH_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("FCM_PUSH_WORKERS", "16")))
_EVENT_PARTICIPATION_CACHE = {}
_EVENT_PARTICIPATION_CACHE_MAX_SIZE = 5000


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


def _send_notifications_batch(tokens, title, message, data):
    for token in tokens:
        send_notification(
            token=token,
            title=title,
            body=message,
            data=data,
        )


def _dispatch_push_async(tokens, title, message, data):
    if not tokens:
        return
    try:
        _PUSH_EXECUTOR.submit(_send_notifications_batch, tokens, title, message, data)
    except Exception:
        # Never fail request path if async dispatch cannot be queued.
        pass


def _invalidate_participation_cache(event_id=None, team_id=None):
    if event_id is None and team_id is None:
        _EVENT_PARTICIPATION_CACHE.clear()
        return
    prefixes = []
    if event_id and team_id:
        prefixes.append(f"members:{event_id}:{team_id}")
    for key in list(_EVENT_PARTICIPATION_CACHE.keys()):
        if any(key.startswith(prefix) for prefix in prefixes):
            _EVENT_PARTICIPATION_CACHE.pop(key, None)


def _push_notification_for_user(user_id, title, message, data):
    tokens = [r[0] for r in db.session.query(FCMToken.token).filter(FCMToken.user_id == int(user_id)).all() if r and r[0]]
    _dispatch_push_async(tokens, title, message, data)

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
    _invalidate_participation_cache(event_id=e.id, team_id=t.id)
    return jsonify({"team_id": str(t.id), "name": t.team_name}), 201

@event_participation_bp.post("/events/<uuid:event_id>/teams/<uuid:team_id>/join")
def join_team(event_id, team_id):
    body = _body()
    uid = body.get("user_id")
    if uid is None:
        return jsonify({"error": "user_id required"}), 400

    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    # Row lock serializes join attempts per team, reducing race under concurrency.
    t = Team.query.filter_by(id=team_id, event_id=e.id).with_for_update().first_or_404()

    size = db.session.query(func.count(TeamMember.user_id)).filter_by(team_id=team_id).scalar() or 0
    if t.is_individual or e.max_team_size == 1:
        return jsonify({"error": "individual team cannot accept members"}), 400
    if e.max_team_size and size >= e.max_team_size:
        return jsonify({"error": f"max team size {e.max_team_size} reached"}), 400

    db.session.add(TeamMember(team_id=team_id, user_id=int(uid), role="member"))

    # Persist notification in backend first (source of truth), then send FCM.
    notification = None
    recipient_user_id = int(t.created_by_user) if t.created_by_user is not None else None
    if recipient_user_id and recipient_user_id != int(uid):
        joiner_name = db.session.query(User.name).filter(User.id == int(uid)).scalar() or "A user"
        notification = Notification(
            user_id=recipient_user_id,
            type="team_invite",
            reference_id=str(t.id),
            title="Team Invite Update",
            message=f"{joiner_name} joined your team {t.team_name}",
            is_read=False,
        )
        db.session.add(notification)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "already joined"}), 409
    _invalidate_participation_cache(event_id=e.id, team_id=t.id)

    if notification is not None:
        tokens = [r[0] for r in db.session.query(FCMToken.token).filter(FCMToken.user_id == notification.user_id).all() if r and r[0]]
        payload = {
            "type": "new_notification",
            "notification_id": str(notification.id),
            "reference_id": str(t.id),
            "event_id": str(e.id),
        }
        _dispatch_push_async(tokens, notification.title, notification.message, payload)

    return jsonify({
        "ok": True,
        "team_id": str(t.id),
        "team_name": t.team_name
    }), 201


@event_participation_bp.post("/events/<uuid:event_id>/teams/<uuid:team_id>/invite")
def invite_user_to_team(event_id, team_id):
    body = _body()
    inviter_user_id = body.get("inviter_user_id")
    invited_user_id = body.get("invited_user_id")

    if inviter_user_id is None or invited_user_id is None:
        return jsonify({"error": "inviter_user_id and invited_user_id required"}), 400
    inviter_user_id = int(inviter_user_id)
    invited_user_id = int(invited_user_id)
    if inviter_user_id == invited_user_id:
        return jsonify({"error": "cannot invite yourself"}), 400

    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    t = Team.query.filter_by(id=team_id, event_id=e.id).with_for_update().first_or_404()

    if t.is_individual or e.max_team_size == 1:
        return jsonify({"error": "individual team cannot accept invitations"}), 400

    inviter_member = TeamMember.query.filter_by(team_id=team_id, user_id=inviter_user_id).first()
    if not inviter_member:
        return jsonify({"error": "only team members can invite"}), 403

    invited_user_exists = db.session.query(User.id).filter(User.id == invited_user_id).scalar() is not None
    if not invited_user_exists:
        return jsonify({"error": "invited user not found"}), 404

    already_member = TeamMember.query.filter_by(team_id=team_id, user_id=invited_user_id).first() is not None
    if already_member:
        return jsonify({"error": "user is already a team member"}), 409

    pending_invite = TeamInvite.query.filter_by(
        event_id=e.id,
        team_id=t.id,
        invited_user_id=invited_user_id,
        status="pending",
    ).first()
    if pending_invite:
        return jsonify({"error": "pending invite already exists", "invite_id": str(pending_invite.id)}), 409

    inviter_name = db.session.query(User.name).filter(User.id == inviter_user_id).scalar() or "A teammate"
    invite = TeamInvite(
        event_id=e.id,
        team_id=t.id,
        inviter_user_id=inviter_user_id,
        invited_user_id=invited_user_id,
        status="pending",
    )
    db.session.add(invite)
    db.session.flush()

    notification = Notification(
        user_id=invited_user_id,
        type="team_invite",
        reference_id=str(t.id),
        title="Team Invite",
        message=f"{inviter_name} invited you to join {t.team_name}",
        is_read=False,
    )
    db.session.add(notification)
    db.session.commit()

    _push_notification_for_user(
        user_id=invited_user_id,
        title=notification.title,
        message=notification.message,
        data={
            "type": "new_notification",
            "notification_id": str(notification.id),
            "reference_id": str(t.id),
            "event_id": str(e.id),
            "invite_id": str(invite.id),
            "invite_status": "pending",
        },
    )

    return jsonify({
        "ok": True,
        "invite": invite.to_dict(),
    }), 201


@event_participation_bp.post("/events/<uuid:event_id>/teams/<uuid:team_id>/invites/<uuid:invite_id>/respond")
def respond_team_invite(event_id, team_id, invite_id):
    body = _body()
    user_id = body.get("user_id")
    action = (body.get("action") or "").strip().lower()

    if user_id is None or action not in {"accept", "reject"}:
        return jsonify({"error": "user_id and valid action(accept|reject) required"}), 400
    user_id = int(user_id)

    e = Event.query.filter_by(id=event_id, visibility=True).first_or_404()
    t = Team.query.filter_by(id=team_id, event_id=e.id).with_for_update().first_or_404()

    invite = TeamInvite.query.filter_by(
        id=invite_id,
        event_id=e.id,
        team_id=t.id,
    ).with_for_update().first_or_404()

    if invite.invited_user_id != user_id:
        return jsonify({"error": "only invited user can respond"}), 403
    if invite.status != "pending":
        return jsonify({"error": f"invite already {invite.status}"}), 409

    invite.responded_at = datetime.now(IST)
    invitee_name = db.session.query(User.name).filter(User.id == invite.invited_user_id).scalar() or "User"

    if action == "accept":
        size = db.session.query(func.count(TeamMember.user_id)).filter_by(team_id=team_id).scalar() or 0
        if t.is_individual or e.max_team_size == 1:
            return jsonify({"error": "individual team cannot accept members"}), 400
        if e.max_team_size and size >= e.max_team_size:
            return jsonify({"error": f"max team size {e.max_team_size} reached"}), 400

        already_member = TeamMember.query.filter_by(team_id=team_id, user_id=user_id).first()
        if not already_member:
            db.session.add(TeamMember(team_id=team_id, user_id=user_id, role="member"))
        invite.status = "accepted"

        inviter_notification = Notification(
            user_id=invite.inviter_user_id,
            type="team_invite_accepted",
            reference_id=str(t.id),
            title="Invite Accepted",
            message=f"{invitee_name} accepted your invite to {t.team_name}",
            is_read=False,
        )
        db.session.add(inviter_notification)
        db.session.commit()
        _invalidate_participation_cache(event_id=e.id, team_id=t.id)

        _push_notification_for_user(
            user_id=invite.inviter_user_id,
            title=inviter_notification.title,
            message=inviter_notification.message,
            data={
                "type": "new_notification",
                "notification_id": str(inviter_notification.id),
                "reference_id": str(t.id),
                "event_id": str(e.id),
                "invite_id": str(invite.id),
                "invite_status": "accepted",
            },
        )

        return jsonify({
            "ok": True,
            "invite": invite.to_dict(),
            "team_id": str(t.id),
            "team_name": t.team_name,
            "joined": True,
        }), 200

    invite.status = "rejected"
    inviter_notification = Notification(
        user_id=invite.inviter_user_id,
        type="team_invite_rejected",
        reference_id=str(t.id),
        title="Invite Rejected",
        message=f"{invitee_name} rejected your invite to {t.team_name}",
        is_read=False,
    )
    db.session.add(inviter_notification)
    db.session.commit()
    _invalidate_participation_cache(event_id=e.id, team_id=t.id)

    _push_notification_for_user(
        user_id=invite.inviter_user_id,
        title=inviter_notification.title,
        message=inviter_notification.message,
        data={
            "type": "new_notification",
            "notification_id": str(inviter_notification.id),
            "reference_id": str(t.id),
            "event_id": str(e.id),
            "invite_id": str(invite.id),
            "invite_status": "rejected",
        },
    )

    return jsonify({
        "ok": True,
        "invite": invite.to_dict(),
        "joined": False,
    }), 200


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
    _invalidate_participation_cache(event_id=event_id, team_id=team_id)

    return jsonify({"ok": True}), 200


@event_participation_bp.post("/events/<uuid:event_id>/register")
def register_team(event_id):
    body = _body()
    uid = body.get("user_id")
    team_id = body.get("team_id")
    if uid is None or not team_id:
        return jsonify({"error": "user_id and team_id required"}), 400

    e = Event.query.filter_by(id=event_id, visibility=True, status="published").first_or_404()
    t = Team.query.filter_by(id=team_id, event_id=e.id).with_for_update().first_or_404()

    is_member = TeamMember.query.filter_by(team_id=team_id, user_id=int(uid)).first() is not None
    if not is_member:
        return jsonify({"error": "only team member can register"}), 403

    counts = db.session.execute(text("""
        SELECT
            (SELECT COUNT(*)::int FROM teams WHERE event_id = :event_id) AS team_count,
            (SELECT COUNT(*)::int FROM team_members tm
                JOIN teams t ON t.id = tm.team_id
                WHERE t.event_id = :event_id) AS player_count
    """), {"event_id": str(e.id)}).mappings().first()
    team_count = int((counts or {}).get("team_count") or 0)
    player_count = int((counts or {}).get("player_count") or 0)
    if e.capacity_team and team_count >= e.capacity_team:
        return jsonify({"error": "team capacity reached"}), 409

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
    cache_ttl_sec = 20
    cache_key = f"members:{event_id}:{team_id}"
    now_ts = time.time()
    cached = _EVENT_PARTICIPATION_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return jsonify(cached["payload"]), 200

    row = db.session.execute(text("""
        SELECT
            t.id,
            t.team_name,
            t.is_individual,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', tm.user_id,
                        'user_id', tm.user_id,
                        'name', COALESCE(u.name, ''),
                        'gameUserName', COALESCE(u.game_username, ''),
                        'role', tm.role,
                        'joined_at', tm.joined_at
                    )
                    ORDER BY tm.joined_at ASC
                ) FILTER (WHERE tm.user_id IS NOT NULL),
                '[]'::json
            ) AS members
        FROM teams t
        JOIN events e ON e.id = t.event_id
        LEFT JOIN team_members tm ON tm.team_id = t.id
        LEFT JOIN users u ON u.id = tm.user_id
        WHERE e.id = :event_id
          AND e.visibility = true
          AND t.id = :team_id
        GROUP BY t.id, t.team_name, t.is_individual
        LIMIT 1
    """), {"event_id": str(event_id), "team_id": str(team_id)}).mappings().first()
    if not row:
        return jsonify({"message": "Not Found"}), 404

    payload = {
        "team_id": str(row["id"]),
        "team_name": row["team_name"],
        "is_individual": row["is_individual"],
        "members": [
            {
                **m,
                "joined_at": m.get("joined_at").isoformat() if m.get("joined_at") else None
            }
            for m in (row["members"] or [])
        ],
    }
    if len(_EVENT_PARTICIPATION_CACHE) >= _EVENT_PARTICIPATION_CACHE_MAX_SIZE:
        _EVENT_PARTICIPATION_CACHE.pop(next(iter(_EVENT_PARTICIPATION_CACHE)))
    _EVENT_PARTICIPATION_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + cache_ttl_sec}
    return jsonify(payload), 200


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
