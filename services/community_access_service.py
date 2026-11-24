"""Shared community eligibility. Pending payments never grant play access."""

from models.communityTournament import CommunityTournamentRegistration
from models.communityTournamentOperations import (
    CommunityTournamentTeam,
    CommunityTournamentTeamMember,
)


def match_team_ids(match):
    return {
        str(value)
        for value in [
            match.team_a_id,
            match.team_b_id,
            *(match.participant_team_ids or []),
        ]
        if value
    }


def eligible_memberships(tournament_id, user_id):
    return (
        CommunityTournamentTeamMember.query.join(
            CommunityTournamentTeam,
            CommunityTournamentTeam.id == CommunityTournamentTeamMember.team_id,
        )
        .join(
            CommunityTournamentRegistration,
            CommunityTournamentRegistration.id
            == CommunityTournamentTeam.registration_id,
        )
        .filter(
            CommunityTournamentTeamMember.tournament_id == tournament_id,
            CommunityTournamentTeamMember.user_id == int(user_id),
            CommunityTournamentTeamMember.verification_status.in_(
                {"accepted", "verified"}
            ),
            CommunityTournamentTeam.status == "approved",
            CommunityTournamentRegistration.status == "confirmed",
        )
        .all()
    )


def eligible_participant(tournament_id, user_id):
    # Once attached to a team, eligibility follows that team's approval status.
    memberships = (
        CommunityTournamentTeamMember.query.filter_by(
            tournament_id=tournament_id, user_id=int(user_id)
        )
        .filter(
            CommunityTournamentTeamMember.verification_status.in_(
                {"accepted", "verified"}
            )
        )
        .all()
    )
    if memberships:
        return bool(eligible_memberships(tournament_id, user_id))
    return (
        CommunityTournamentRegistration.query.filter_by(
            tournament_id=tournament_id, user_id=int(user_id), status="confirmed"
        ).first()
        is not None
    )


def require_participant(tournament, user_id):
    from services.community_tournament_service import CommunityForbiddenError

    if int(tournament.host_user_id) != int(user_id) and not eligible_participant(
        tournament.id, user_id
    ):
        raise CommunityForbiddenError(
            "confirmed entry or accepted membership in an approved, paid team is required"
        )


def match_membership(tournament_id, user_id, match):
    from services.community_tournament_service import CommunityForbiddenError

    ids = match_team_ids(match)
    membership = next(
        (
            m
            for m in eligible_memberships(tournament_id, user_id)
            if str(m.team_id) in ids
        ),
        None,
    )
    if membership is None:
        raise CommunityForbiddenError(
            "only eligible assigned match participants can access this match"
        )
    return membership
