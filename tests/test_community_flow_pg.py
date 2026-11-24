"""Run against a disposable PostgreSQL URL; each test uses an isolated schema."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from flask import Flask, g, jsonify
from sqlalchemy import text, event
from db.extensions import db

# Register relationship targets without initializing the production application.
from models.physicalAddress import PhysicalAddress
from models.contactInfo import ContactInfo
from models.passwordManager import PasswordManager
from models.fcmToken import FCMToken
from models.voucher import Voucher
from models.user import User
from models.communityTournament import (
    CommunityTournament,
    CommunityTournamentRegistration,
)
from models.communityTournamentOperations import (
    CommunityTournamentTeam,
    CommunityTournamentTeamMember,
    CommunityTournamentMatch,
    CommunityTournamentDispute,
    CommunityTournamentPayout,
)
from services import community_tournament_service as service
from services import community_tournament_control_service as control
from services import community_player_flow_service as flow
from services.community_idempotency_service import (
    idempotent_community,
    commit_community,
)


@pytest.fixture
def app():
    url = os.getenv("COMMUNITY_FLOW_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set COMMUNITY_FLOW_TEST_DATABASE_URL to a disposable PostgreSQL instance"
        )
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        COMMUNITY_DISPUTE_CHAT_ENABLED=False,
    )
    db.init_app(app)
    schema = "community_flow_" + uuid.uuid4().hex
    with app.app_context():
        engine = db.engine
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))

        def checkout(conn, *_):
            with conn.cursor() as cursor:
                cursor.execute(f"SET search_path TO {schema}")
            conn.commit()

        event.listen(engine, "checkout", checkout)
        tables = [
            t
            for name, t in db.metadata.tables.items()
            if name.startswith("community_")
            or name
            in {"users", "notifications", "hash_wallets", "hash_wallet_transactions"}
        ]
        db.metadata.create_all(engine, tables=tables)
        migration = (
            (Path(__file__).parents[1] / "sql/20261030_community_api_idempotency.sql")
            .read_text()
            .replace("BEGIN;", "")
            .replace("COMMIT;", "")
        )
        db.session.execute(text(migration))
        db.session.execute(text(migration))
        for user_id in range(1, 9):
            db.session.add(
                User(
                    id=user_id,
                    fid=f"fid{user_id}",
                    name=f"User {user_id}",
                    game_username=f"gamer{user_id}",
                )
            )
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        event.remove(engine, "checkout", checkout)
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()


def seed():
    now = datetime.now(timezone.utc)
    tournament = CommunityTournament(
        host_user_id=1,
        title="Test Cup",
        game="Test",
        tournament_type="battle_royale",
        team_mode="team",
        team_size=2,
        entry_fee=0,
        max_players=8,
        status="live",
        rules="Rules",
        registration_start_at=now - timedelta(days=2),
        registration_end_at=now - timedelta(days=1),
        tournament_start_at=now - timedelta(hours=1),
        tournament_end_at=now + timedelta(hours=2),
        check_in_start_at=now - timedelta(hours=2),
        check_in_end_at=now + timedelta(hours=1),
        prize_pool=100,
        prize_distribution=[{"rank": 1, "percent": 100}],
    )
    db.session.add(tournament)
    db.session.flush()
    regs = []
    teams = []
    for uid in (2, 4, 6):
        reg = CommunityTournamentRegistration(
            tournament_id=tournament.id,
            user_id=uid,
            status="confirmed",
            payment_status="not_required",
        )
        db.session.add(reg)
        db.session.flush()
        regs.append(reg)
        team = CommunityTournamentTeam(
            tournament_id=tournament.id,
            registration_id=reg.id,
            captain_user_id=uid,
            name=f"Team {uid}",
            status="approved",
        )
        db.session.add(team)
        db.session.flush()
        teams.append(team)
        for member_id, role in [(uid, "captain"), (uid + 1, "player")]:
            db.session.add(
                CommunityTournamentTeamMember(
                    tournament_id=tournament.id,
                    team_id=team.id,
                    user_id=member_id,
                    role=role,
                    game_id=f"game{member_id}",
                    verification_status="accepted",
                )
            )
    tournament.registered_players_count = 3
    match = CommunityTournamentMatch(
        tournament_id=tournament.id,
        stage="manual",
        round_number=1,
        match_number=1,
        status="ready",
        participant_team_ids=[str(t.id) for t in teams],
        lobby_details={"password": "secret"},
    )
    db.session.add(match)
    db.session.commit()
    return tournament, regs, teams, match


def test_roster_member_can_access_lobby_and_evidence_but_unpaid_cannot(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        assert (
            control.list_private_matches(3, tournament.id, {})["items"][0][
                "lobby_details"
            ]["password"]
            == "secret"
        )
        assert (
            service._evidence_upload_access(3, tournament.id, "dispute_evidence")[0].id
            == tournament.id
        )
        assert control.match_result_state(3, tournament.id, match.id)["viewer"][
            "team_id"
        ] == str(teams[0].id)
        pending = CommunityTournamentRegistration(
            tournament_id=tournament.id,
            user_id=8,
            status="pending_payment",
            payment_status="unpaid",
        )
        db.session.add(pending)
        db.session.commit()
        with pytest.raises(service.CommunityForbiddenError):
            control.list_private_matches(8, tournament.id, {})
        with pytest.raises(service.CommunityForbiddenError):
            service._evidence_upload_access(8, tournament.id, "result_evidence")
        teams[0].status = "disqualified"
        db.session.commit()
        with pytest.raises(service.CommunityForbiddenError):
            control.list_private_matches(3, tournament.id, {})


def test_multiteam_dispute_and_referee_flow(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        control.manage_match(1, tournament.id, match.id, {"action": "start"})
        dispute = service.create_dispute(
            3,
            tournament.id,
            {
                "match_id": str(match.id),
                "reason": "Score",
                "description": "Wrong score",
            },
        )
        assert flow.dispute_detail(5, dispute.id)["status"] == "open"
        with pytest.raises(service.CommunityForbiddenError):
            flow.dispute_detail(8, dispute.id)
        standings = [
            {"team_id": str(team.id), "placement": i + 1, "kills": 2}
            for i, team in enumerate(teams)
        ]
        with pytest.raises(service.CommunityConflictError):
            control.manage_match(
                1,
                tournament.id,
                match.id,
                {"action": "record_standings", "standings": standings},
            )
        assert not flow.finalization_preview(1, tournament.id)["ready_to_finalize"]
        result = control.admin_resolve_match_result(
            8,
            tournament.id,
            match.id,
            {"reason": "Reviewed evidence", "standings": standings},
        )
        assert result["status"] == "completed"
        assert flow.dispute_detail(3, dispute.id)["status"] == "closed"
        preview = flow.finalization_preview(1, tournament.id)
        assert preview["ready_to_finalize"] and preview["payout_policy"] == "captain"
        payouts = service.submit_winners(
            1, tournament.id, [{"team_id": str(teams[0].id), "rank": 1, "amount": 100}]
        )
        assert payouts[0].user_id == 2
        assert flow.my_payouts(2, {})["items"][0]["destination"] == "hash_wallet"
        assert flow.my_payouts(3, {})["items"] == []
        with pytest.raises(service.CommunityConflictError):
            service.submit_winners(1, tournament.id, [{"user_id": 2, "amount": 100}])


def test_self_check_in_and_assigned_match_read(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        assert flow.my_matches(3, tournament.id, {})["items"][0]["id"] == str(match.id)
        assert flow.my_matches(8, tournament.id, {})["items"] == []
        response = flow.self_check_in(2, tournament.id)
        assert response["team"]["checked_in_at"]
        assert (
            flow.self_check_in(2, tournament.id)["team"]["checked_in_at"]
            == response["team"]["checked_in_at"]
        )
        with pytest.raises(service.CommunityConflictError):
            flow.self_check_in(3, tournament.id)
        mine = flow.my_tournament(3, tournament.id)
        assert mine["registration"] is None and mine["team"]["id"] == str(teams[0].id)
        assert mine["current_match"]["id"] == str(match.id)


def test_invitation_inbox_and_lock_guards(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        member = CommunityTournamentTeamMember.query.filter_by(user_id=3).one()
        member.verification_status = "invited"
        db.session.commit()
        assert flow.my_invitations(3, {})["items"][0]["can_respond"] is False
        with pytest.raises(service.CommunityConflictError):
            control.respond_team_invitation(
                3, tournament.id, teams[0].id, {"action": "accept"}
            )
        tournament.status = "registration_closed"
        tournament.tournament_start_at = datetime.now(timezone.utc) + timedelta(hours=1)
        teams[0].roster_locked_at = datetime.now(timezone.utc)
        db.session.commit()
        with pytest.raises(service.CommunityConflictError):
            control.respond_team_invitation(
                3, tournament.id, teams[0].id, {"action": "decline"}
            )
        teams[0].roster_locked_at = None
        db.session.commit()
        control.respond_team_invitation(
            3, tournament.id, teams[0].id, {"action": "accept"}
        )
        assert flow.my_invitations(3, {})["items"] == []
        with pytest.raises(service.CommunityConflictError):
            control.respond_team_invitation(
                3, tournament.id, teams[0].id, {"action": "decline"}
            )


def test_publish_and_proposal_flags_match_mutation_guards(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        tournament.status = "draft"
        tournament.rules = None
        tournament.rules_config = {}
        db.session.commit()
        assert not control.tournament_readiness(1, tournament.id)["ready_to_publish"]
        with pytest.raises(service.CommunityValidationError):
            service.update_tournament(1, tournament.id, {"status": "published"})
        db.session.rollback()
        assert db.session.get(CommunityTournament, tournament.id).status == "draft"
        tournament.status = "live"
        match.participant_team_ids = []
        match.team_a_id = teams[0].id
        match.team_b_id = teams[1].id
        match.status = "disputed"
        db.session.commit()
        assert not control.match_result_state(1, tournament.id, match.id)["viewer"][
            "can_create_proposal"
        ]
        with pytest.raises(service.CommunityConflictError):
            control.create_result_proposal(1, tournament.id, match.id, {})


def test_idempotent_concurrent_write_conflict_and_rollback(app):
    @app.post("/write")
    @idempotent_community
    def write():
        db.session.execute(
            text(
                "INSERT INTO notifications(id,user_id,type,title,message,is_read) VALUES (:id,2,'test','Test','Test',false)"
            ),
            {"id": uuid.uuid4()},
        )
        commit_community(db.session)
        return jsonify(ok=True), 201

    @app.post("/fail")
    @idempotent_community
    def fail():
        db.session.execute(
            text(
                "INSERT INTO notifications(id,user_id,type,title,message,is_read) VALUES (:id,2,'test','Test','Test',false)"
            ),
            {"id": uuid.uuid4()},
        )
        commit_community(db.session)
        return jsonify(error="conflict"), 409

    @app.before_request
    def identity():
        g.auth_user_id = 2

    def call(_):
        with app.test_client() as client:
            response = client.post(
                "/write", json={"value": 1}, headers={"Idempotency-Key": "same"}
            )
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(call, range(4))) == [(201, {"ok": True})] * 4
    with app.test_client() as client:
        assert (
            client.post(
                "/write", json={"value": 2}, headers={"Idempotency-Key": "same"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/fail", json={}, headers={"Idempotency-Key": "fail"}
            ).status_code
            == 409
        )
    with app.app_context():
        assert (
            db.session.execute(text("SELECT count(*) FROM notifications")).scalar() == 1
        )
        assert (
            db.session.execute(
                text("SELECT count(*) FROM community_api_idempotency")
            ).scalar()
            == 1
        )


def test_http_player_routes_authorization_and_real_write_replay(app):
    import time
    import jwt
    from controllers.community_tournament_controller import community_tournament_bp

    app.config.update(JWT_SECRET_KEY="test-key-" * 8, ENCRYPT_PRIVATE_KEY="test-only")
    app.register_blueprint(community_tournament_bp)
    with app.app_context():
        tournament, regs, teams, match = seed()
        tid, mid = str(tournament.id), str(match.id)
        control.manage_match(1, tournament.id, match.id, {"action": "start"})
        dispute = service.create_dispute(
            3,
            tournament.id,
            {"match_id": mid, "reason": "Score", "description": "Review please"},
        )
        did = str(dispute.id)

    def headers(uid, **extra):
        token = jwt.encode(
            {"uuid": str(uid), "iat": int(time.time()), "exp": int(time.time()) + 600},
            app.config["JWT_SECRET_KEY"],
            algorithm="HS256",
        )
        return {"Authorization": "Bearer " + token, **extra}

    prefix = "/api/v1/community"
    with patch(
        "services.security.decode_user", side_effect=lambda value, key: int(value)
    ), app.test_client() as client:
        player_paths = [
            f"/tournaments/{tid}/me",
            "/me/team-invitations",
            f"/tournaments/{tid}/matches/me",
            "/me/disputes",
            f"/disputes/{did}",
            "/me/payouts",
        ]
        for path in player_paths:
            assert client.get(prefix + path).status_code == 401
            response = client.get(prefix + path, headers=headers(3))
            assert response.status_code == 200, (path, response.get_json())
        assert (
            client.get(prefix + f"/disputes/{did}", headers=headers(8)).status_code
            == 403
        )
        assert (
            client.get(
                prefix + f"/tournaments/{tid}/finalization-preview", headers=headers(1)
            ).status_code
            == 200
        )
        assert (
            client.get(
                prefix + f"/tournaments/{tid}/finalization-preview", headers=headers(3)
            ).status_code
            == 403
        )
        assert (
            client.post(
                prefix + f"/tournaments/{tid}/check-in", json={}, headers=headers(2)
            ).status_code
            == 200
        )
        assert (
            client.get(prefix + "/me/payouts?page=abc", headers=headers(3)).status_code
            == 400
        )
        now = datetime.now(timezone.utc)
        body = {
            "title": "Replay Cup",
            "game": "Test",
            "max_players": 8,
            "status": "draft",
            "registration_start_at": (now + timedelta(days=1)).isoformat(),
            "registration_end_at": (now + timedelta(days=2)).isoformat(),
            "tournament_start_at": (now + timedelta(days=3)).isoformat(),
        }
        first = client.post(
            prefix + "/tournaments",
            json=body,
            headers=headers(1, **{"Idempotency-Key": "draft"}),
        )
        assert first.status_code == 201, first.get_json()
        second = client.post(
            prefix + "/tournaments",
            json=body,
            headers=headers(1, **{"Idempotency-Key": "draft"}),
        )
        assert second.status_code == 201 and second.get_json() == first.get_json()
        assert second.headers["Idempotency-Replayed"] == "true"
        assert (
            client.post(
                prefix + "/tournaments",
                json={**body, "title": "Changed"},
                headers=headers(1, **{"Idempotency-Key": "draft"}),
            ).status_code
            == 409
        )
        assert (
            client.post(
                prefix + "/tournaments",
                json={**body, "status": "published"},
                headers=headers(1),
            ).status_code
            == 400
        )
    with app.app_context():
        assert CommunityTournament.query.filter_by(title="Replay Cup").count() == 1


def test_unassigned_lobby_is_redacted_and_invalid_team_payee_rejected(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        match.participant_team_ids = []
        match.team_a_id = teams[1].id
        match.team_b_id = teams[2].id
        db.session.commit()
        assert (
            control.list_private_matches(3, tournament.id, {})["items"][0][
                "lobby_details"
            ]
            == {}
        )
        with pytest.raises(service.CommunityForbiddenError):
            control.match_result_state(3, tournament.id, match.id)
        with pytest.raises(service.CommunityValidationError):
            flow.resolve_winner_payee(
                tournament, {"team_id": str(teams[0].id), "user_id": 3}
            )
        with pytest.raises(service.CommunityValidationError):
            flow.resolve_winner_payee(tournament, {"user_id": 3})


def test_head_to_head_proposal_permission_tracks_pending_and_dispute(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        match.participant_team_ids = []
        match.team_a_id = teams[0].id
        match.team_b_id = teams[1].id
        match.status = "in_progress"
        db.session.commit()
        assert control.match_result_state(1, tournament.id, match.id)["viewer"][
            "can_create_proposal"
        ]
        proposal = control.create_result_proposal(
            1,
            tournament.id,
            match.id,
            {
                "winner_team_id": str(teams[0].id),
                "team_a_score": 2,
                "team_b_score": 1,
                "evidence_urls": ["https://example.com/score.png"],
            },
        )
        assert not control.match_result_state(1, tournament.id, match.id)["viewer"][
            "can_create_proposal"
        ]
        control.accept_result_proposal(2, tournament.id, match.id, proposal.id)
        control.accept_result_proposal(4, tournament.id, match.id, proposal.id)
        assert db.session.get(CommunityTournamentMatch, match.id).status == "completed"


def test_accepted_teammate_can_submit_legacy_result_and_review(app):
    with app.app_context():
        tournament, regs, teams, match = seed()
        result = service.submit_match_result(
            3, tournament.id, {"winner_user_id": 2, "rank": 1}
        )
        assert result.submitted_by_user_id == 3
        tournament.status = "completed"
        db.session.commit()
        ratings = {
            field: 5
            for field in [
                "management_rating",
                "communication_rating",
                "fairness_rating",
                "scheduling_rating",
                "dispute_handling_rating",
            ]
        }
        assert (
            control.create_tournament_review(3, tournament.id, ratings).reviewer_user_id
            == 3
        )
        with pytest.raises(service.CommunityConflictError):
            control.create_tournament_review(3, tournament.id, ratings)
        with pytest.raises(service.CommunityForbiddenError):
            control.create_tournament_review(1, tournament.id, ratings)
