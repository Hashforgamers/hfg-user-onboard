"""Trusted Firebase chat provisioning for community tournament disputes."""

from firebase_admin import auth, firestore
from flask import current_app

from models.communityTournamentOperations import (
    CommunityTournamentMatch,
    CommunityTournamentTeam,
    CommunityTournamentTeamMember,
)


class CommunityDisputeChatError(RuntimeError):
    pass


def firebase_uid_for_user(user_id):
    return f"hfg-user-{int(user_id)}"


def mint_dispute_chat_token(user_id):
    if not current_app.config.get("COMMUNITY_DISPUTE_CHAT_ENABLED", False):
        raise CommunityDisputeChatError("community dispute chat is not enabled")
    custom_token = auth.create_custom_token(
        firebase_uid_for_user(user_id),
        developer_claims={
            "hash_user_id": str(int(user_id)),
            "community_dispute_chat": True,
        },
    )
    return {
        "firebase_uid": firebase_uid_for_user(user_id),
        "firebase_custom_token": (
            custom_token.decode("utf-8") if isinstance(custom_token, bytes) else str(custom_token)
        ),
    }


def _admin_user_ids():
    raw = str(current_app.config.get("COMMUNITY_DISPUTE_ADMIN_USER_IDS", "") or "")
    try:
        user_ids = sorted({int(value.strip()) for value in raw.split(",") if value.strip()})
    except ValueError as exc:
        raise CommunityDisputeChatError("COMMUNITY_DISPUTE_ADMIN_USER_IDS must be comma-separated user IDs") from exc
    return user_ids


def _match_participant_user_ids(match_id):
    if not match_id:
        return set()
    match = CommunityTournamentMatch.query.filter_by(id=match_id).first()
    if not match:
        return set()
    team_ids = [team_id for team_id in (match.team_a_id, match.team_b_id) if team_id]
    if not team_ids:
        return set()
    return {
        int(row.user_id)
        for row in CommunityTournamentTeamMember.query.filter(
            CommunityTournamentTeamMember.team_id.in_(team_ids),
            CommunityTournamentTeamMember.verification_status.in_({"accepted", "verified"}),
        ).all()
    }


def _match_details(match_id):
    if not match_id:
        return None
    match = CommunityTournamentMatch.query.filter_by(id=match_id).first()
    if not match:
        return None
    team_ids = [team_id for team_id in (match.team_a_id, match.team_b_id) if team_id]
    names = {
        team.id: team.name
        for team in CommunityTournamentTeam.query.filter(CommunityTournamentTeam.id.in_(team_ids)).all()
    } if team_ids else {}
    return {
        "match_id": str(match.id),
        "stage": match.stage,
        "round_number": match.round_number,
        "match_number": match.match_number,
        "team_a": {"id": str(match.team_a_id), "name": names.get(match.team_a_id)} if match.team_a_id else None,
        "team_b": {"id": str(match.team_b_id), "name": names.get(match.team_b_id)} if match.team_b_id else None,
    }


def provision_dispute_chat_room(dispute, tournament):
    """Create one backend-owned Firestore room and its immutable opening message."""
    if not current_app.config.get("COMMUNITY_DISPUTE_CHAT_ENABLED", False):
        dispute.chat_room_status = "disabled"
        return None

    admin_ids = _admin_user_ids()
    participant_ids = _match_participant_user_ids(dispute.match_id)
    participant_ids.add(int(tournament.host_user_id))
    if dispute.reported_by_user_id:
        participant_ids.add(int(dispute.reported_by_user_id))
    participant_ids.update(admin_ids)
    room_id = dispute.chat_room_id or f"community-dispute-{dispute.id}"
    participant_ids = sorted(participant_ids)
    participant_uids = [firebase_uid_for_user(user_id) for user_id in participant_ids]
    match_details = _match_details(dispute.match_id)

    try:
        room = firestore.client().collection("communityDisputeRooms").document(room_id)
        room.set({
            "room_type": "community_tournament_dispute",
            "dispute_id": str(dispute.id),
            "tournament_id": str(tournament.id),
            "match_id": str(dispute.match_id) if dispute.match_id else None,
            "match_details": match_details,
            "host_user_id": str(tournament.host_user_id),
            "participant_user_ids": [str(user_id) for user_id in participant_ids],
            "participant_firebase_uids": participant_uids,
            "admin_user_ids": [str(user_id) for user_id in admin_ids],
            "reason": dispute.reason,
            "description": dispute.description,
            "evidence_asset_ids": dispute.evidence_asset_ids or [],
            "status": dispute.status,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": "community_backend",
        }, merge=True)
        room.collection("messages").document("system-opened").set({
            "message_type": "system",
            "text": f"Dispute opened: {dispute.reason}\n{dispute.description}",
            "evidence_asset_ids": dispute.evidence_asset_ids or [],
            "match_id": str(dispute.match_id) if dispute.match_id else None,
            "match_details": match_details,
            "sender_user_id": None,
            "created_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
    except Exception as exc:
        raise CommunityDisputeChatError("unable to provision the dispute chat room") from exc
    dispute.chat_room_id = room_id
    dispute.chat_room_status = "ready"
    return room_id
