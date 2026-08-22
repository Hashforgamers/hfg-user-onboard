"""Trusted Firebase chat provisioning for community tournament disputes."""

from firebase_admin import auth, firestore
from flask import current_app

from models.communityTournamentOperations import (
    CommunityMatchResult,
    CommunityMatchResultProposal,
    CommunityMatchResultSubmission,
    CommunityTournamentMatch,
    CommunityTournamentTeam,
    CommunityTournamentTeamMember,
)
from models.communityTournament import CommunityFileAsset
from models.user import User
from google.api_core.exceptions import AlreadyExists


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
        "label": f"Round {match.round_number} • Match #{match.match_number}",
        "team_a": {"id": str(match.team_a_id), "name": names.get(match.team_a_id)} if match.team_a_id else None,
        "team_b": {"id": str(match.team_b_id), "name": names.get(match.team_b_id)} if match.team_b_id else None,
    }


def _dispute_initiator(dispute, tournament):
    """Identify the person who opened the dispute without trusting client input."""
    submitter = _submitter(dispute.reported_by_user_id, tournament.host_user_id)
    if submitter["role"] == "host":
        submitter["role"] = "tournament_host"
        return submitter
    membership = CommunityTournamentTeamMember.query.filter_by(
        tournament_id=tournament.id,
        user_id=dispute.reported_by_user_id,
    ).first() if dispute.reported_by_user_id else None
    if not membership:
        submitter["role"] = "player"
        return submitter
    team = CommunityTournamentTeam.query.filter_by(id=membership.team_id).first()
    submitter["role"] = "team_representative" if membership.role == "captain" else "player"
    submitter["team_id"] = str(membership.team_id)
    submitter["team_name"] = team.name if team else None
    return submitter


def _evidence_previews(asset_ids):
    """Resolve registered evidence once, before the backend writes the room."""
    if not asset_ids:
        return []
    assets = CommunityFileAsset.query.filter(
        CommunityFileAsset.id.in_(asset_ids)
    ).all()
    by_id = {str(asset.id): asset for asset in assets}
    return [
        {
            "asset_id": str(asset.id),
            "file_url": asset.file_url,
            "mime_type": asset.mime_type,
            "purpose": asset.purpose,
        }
        for asset_id in asset_ids
        for asset in [by_id.get(str(asset_id))]
        if asset
    ]


def _submitter(user_id, host_user_id):
    if not user_id:
        return {"user_id": None, "role": "unknown", "display_name": None}
    user = User.query.filter_by(id=int(user_id)).first()
    return {
        "user_id": int(user_id),
        "role": "host" if int(user_id) == int(host_user_id) else "participant",
        "display_name": (user.name or user.game_username) if user else None,
    }


def _team_name(team_id):
    if not team_id:
        return None
    team = CommunityTournamentTeam.query.filter_by(id=team_id).first()
    return team.name if team else None


def _result_summary(result_contexts):
    summaries = []
    for context in result_contexts:
        winner = context.get("winner_team_name") or context.get("winner_display_name")
        if context.get("team_a_score") is not None and context.get("team_b_score") is not None:
            score = f"{context['team_a_score']}-{context['team_b_score']}"
            summaries.append(f"{winner or 'Winner pending'} • {score}")
        elif context.get("score"):
            summaries.append(f"{winner or 'Reported result'} • {context['score']}")
        elif winner:
            summaries.append(f"{winner} • Winner")
    return " | ".join(summaries) or "No submitted result snapshot is available."


def _result_contexts(dispute, tournament):
    """Build immutable, UI-ready previews for the result that led to a dispute."""
    contexts = []
    if dispute.result_id:
        result = CommunityMatchResult.query.filter_by(
            id=dispute.result_id,
            tournament_id=tournament.id,
        ).first()
        if result:
            asset_ids = list(result.evidence_asset_ids or [])
            contexts.append({
                "source_type": "tournament_result",
                "source_id": str(result.id),
                "submitter": _submitter(result.submitted_by_user_id, tournament.host_user_id),
                "winner_user_id": int(result.winner_user_id) if result.winner_user_id else None,
                "winner_display_name": _submitter(result.winner_user_id, tournament.host_user_id).get("display_name"),
                "rank": result.rank,
                "score": result.score,
                "notes": result.notes,
                "evidence_asset_ids": asset_ids,
                "evidence": _evidence_previews(asset_ids),
            })

    if dispute.match_id:
        proposals = CommunityMatchResultProposal.query.filter_by(
            tournament_id=tournament.id,
            match_id=dispute.match_id,
        ).order_by(
            CommunityMatchResultProposal.disputed_at.desc().nullslast(),
            CommunityMatchResultProposal.created_at.desc(),
        ).all()
        disputed_proposal = next((proposal for proposal in proposals if proposal.status == "disputed"), None)
        if disputed_proposal:
            asset_ids = list(disputed_proposal.evidence_asset_ids or [])
            contexts.append({
                "source_type": "host_result_proposal",
                "source_id": str(disputed_proposal.id),
                "submitter": _submitter(disputed_proposal.proposed_by_user_id, tournament.host_user_id),
                "winner_team_id": str(disputed_proposal.winner_team_id),
                "winner_team_name": _team_name(disputed_proposal.winner_team_id),
                "team_a_score": disputed_proposal.team_a_score,
                "team_b_score": disputed_proposal.team_b_score,
                "evidence_asset_ids": asset_ids,
                "evidence": _evidence_previews(asset_ids),
                "evidence_urls": disputed_proposal.evidence_urls or [],
                "ocr_data": disputed_proposal.ocr_data or {},
            })

        submissions = CommunityMatchResultSubmission.query.filter_by(
            match_id=dispute.match_id,
        ).filter(CommunityMatchResultSubmission.status == "conflict").order_by(
            CommunityMatchResultSubmission.created_at.asc(),
        ).all()
        for submission in submissions:
            asset_ids = list(submission.evidence_asset_ids or [])
            contexts.append({
                "source_type": "captain_result_submission",
                "source_id": str(submission.id),
                "submitter": _submitter(submission.submitted_by_user_id, tournament.host_user_id),
                "team_id": str(submission.team_id),
                "winner_team_id": str(submission.winner_team_id) if submission.winner_team_id else None,
                "winner_team_name": _team_name(submission.winner_team_id),
                "team_a_score": submission.team_a_score,
                "team_b_score": submission.team_b_score,
                "notes": submission.notes,
                "evidence_asset_ids": asset_ids,
                "evidence": _evidence_previews(asset_ids),
            })
    return contexts


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
    result_contexts = _result_contexts(dispute, tournament)
    submitted_result_summary = _result_summary(result_contexts)
    initiator = _dispute_initiator(dispute, tournament)
    source_roles = sorted({context["submitter"]["role"] for context in result_contexts})
    submitted_by = " and ".join(source_roles) if source_roles else "participant"
    preview_image_url = next(
        (
            evidence["file_url"]
            for context in result_contexts
            for evidence in context.get("evidence", [])
        ),
        None,
    )

    try:
        room = firestore.client().collection("communityDisputeRooms").document(room_id)
        room.set({
            "room_type": "community_tournament_dispute",
            "dispute_id": str(dispute.id),
            "tournament_id": str(tournament.id),
            "match_id": str(dispute.match_id) if dispute.match_id else None,
            "match_details": match_details,
            "tournament_name": tournament.title,
            "host_user_id": str(tournament.host_user_id),
            "participant_user_ids": [str(user_id) for user_id in participant_ids],
            "participant_firebase_uids": participant_uids,
            "admin_user_ids": [str(user_id) for user_id in admin_ids],
            "reason": dispute.reason,
            "description": dispute.description,
            "evidence_asset_ids": dispute.evidence_asset_ids or [],
            "dispute_initiator": initiator,
            "result_contexts": result_contexts,
            "submitted_result_summary": submitted_result_summary,
            "preview_image_url": preview_image_url,
            "status": dispute.status,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": "community_backend",
        }, merge=True)
        opening_message = {
            "message_type": "system",
            "immutable": True,
            "text": (
                f"Dispute opened by: {initiator.get('display_name') or initiator['role']}\n"
                f"Result submitted by: {submitted_by}\n"
                f"Submitted Result: {submitted_result_summary}\n"
                f"Tournament: {tournament.title}\n"
                f"Match: {(match_details or {}).get('label') or 'Tournament result'}\n"
                f"Dispute status: {str(dispute.status).replace('_', ' ').title()}\n"
                f"Reason: {dispute.reason}\n{dispute.description}"
            ),
            "tournament_id": str(tournament.id),
            "tournament_name": tournament.title,
            "dispute_id": str(dispute.id),
            "dispute_initiator": initiator,
            "dispute_status": dispute.status,
            "raised_at": firestore.SERVER_TIMESTAMP,
            "evidence_asset_ids": dispute.evidence_asset_ids or [],
            "result_contexts": result_contexts,
            "submitted_result_summary": submitted_result_summary,
            "preview_image_url": preview_image_url,
            "match_id": str(dispute.match_id) if dispute.match_id else None,
            "match_details": match_details,
            "sender_user_id": None,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": "community_backend",
        }
        try:
            room.collection("messages").document("system-opened").create(opening_message)
        except AlreadyExists:
            # The original record is immutable: retries must not replace it.
            pass
    except Exception as exc:
        raise CommunityDisputeChatError("unable to provision the dispute chat room") from exc
    dispute.chat_room_id = room_id
    dispute.chat_room_status = "ready"
    return room_id
