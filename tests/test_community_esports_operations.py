import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from services.community_tournament_control_service import (
    _match_payload,
    _auto_check_in_teams,
    _finalize_result_proposal,
    _next_power_of_two,
    _proposal_evidence_urls,
    _schedule_bracket_rounds,
    _schedule_time,
    _seed_pairs,
    _validate_roster,
    manage_match,
    rule_template,
    start_tournament,
)
from services.community_tournament_service import (
    CommunityConflictError,
    CommunityForbiddenError,
    CommunityValidationError,
    _derive_status,
    _invite_code_hash,
    _recalculate_prize_pool,
    _validated_evidence_asset_ids,
    close_registration,
    get_tournament,
)
from models.communityTournament import CommunityTournamentStatus


class CommunityEsportsOperationTests(unittest.TestCase):
    def test_bracket_size_uses_next_power_of_two(self):
        self.assertEqual(_next_power_of_two(2), 2)
        self.assertEqual(_next_power_of_two(5), 8)
        self.assertEqual(_next_power_of_two(16), 16)

    def test_seed_pairs_distribute_byes_without_empty_match(self):
        teams = [SimpleNamespace(id=index) for index in range(1, 6)]

        pairs = _seed_pairs(teams, 8)

        self.assertEqual(len(pairs), 4)
        self.assertEqual(sum(team is None for pair in pairs for team in pair), 3)
        self.assertTrue(all(team_a is not None or team_b is not None for team_a, team_b in pairs))
        self.assertEqual(
            {team.id for pair in pairs for team in pair if team is not None},
            {1, 2, 3, 4, 5},
        )

    def test_schedule_respects_concurrency_and_break(self):
        start = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
        tournament = SimpleNamespace(
            tournament_start_at=start,
            match_duration_minutes=45,
            break_duration_minutes=15,
            schedule_config={"concurrent_matches": 2},
        )

        self.assertEqual(_schedule_time(tournament, 0), start)
        self.assertEqual(_schedule_time(tournament, 1), start)
        self.assertEqual(_schedule_time(tournament, 2).hour, 11)

    def test_bracket_schedule_skips_byes_and_waits_for_the_prior_round(self):
        start = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
        tournament = SimpleNamespace(
            tournament_start_at=start,
            match_duration_minutes=45,
            break_duration_minutes=15,
            schedule_config={"concurrent_matches": 2},
        )
        bye = SimpleNamespace(status="completed", scheduled_at=None)
        first_a = SimpleNamespace(status="ready", scheduled_at=None)
        first_b = SimpleNamespace(status="ready", scheduled_at=None)
        final = SimpleNamespace(status="scheduled", scheduled_at=None)

        _schedule_bracket_rounds(tournament, {1: [bye, first_a, first_b], 2: [final]})

        self.assertIsNone(bye.scheduled_at)
        self.assertEqual(first_a.scheduled_at, start)
        self.assertEqual(first_b.scheduled_at, start)
        self.assertEqual(final.scheduled_at, start + timedelta(minutes=60))

    @patch("services.community_tournament_control_service.CommunityTournamentRegistration")
    def test_bracket_generation_auto_checks_in_approved_teams(self, registration_model):
        now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
        first_registration_id = uuid.uuid4()
        second_registration_id = uuid.uuid4()
        first_registration = SimpleNamespace(id=first_registration_id, checked_in_at=None)
        second_registration = SimpleNamespace(id=second_registration_id, checked_in_at=now)
        registration_model.query.filter.return_value.all.return_value = [
            first_registration,
            second_registration,
        ]
        first_team = SimpleNamespace(registration_id=first_registration_id, checked_in_at=None)
        second_team = SimpleNamespace(registration_id=second_registration_id, checked_in_at=now)

        auto_checked_in = _auto_check_in_teams([first_team, second_team], now)

        self.assertEqual(auto_checked_in, 1)
        self.assertEqual(first_team.checked_in_at, now)
        self.assertEqual(first_registration.checked_in_at, now)
        self.assertEqual(second_team.checked_in_at, now)

    @patch("services.community_tournament_control_service.CommunityTournamentTeam")
    def test_public_match_payload_redacts_lobby_credentials(self, team_model):
        team_model.query.filter.return_value.all.return_value = []
        match = SimpleNamespace(
            team_a_id=None,
            team_b_id=None,
            winner_team_id=None,
            to_dict=lambda: {
                "id": str(uuid.uuid4()),
                "lobby_details": {"access_code": "secret"},
            },
        )

        payload = _match_payload(match, include_lobby=False)

        self.assertEqual(payload["lobby_details"], {})

    def test_result_proposal_evidence_urls_require_https(self):
        urls = _proposal_evidence_urls(["https://firebasestorage.googleapis.com/evidence.png"])

        self.assertEqual(urls, ["https://firebasestorage.googleapis.com/evidence.png"])
        with self.assertRaisesRegex(CommunityValidationError, "https"):
            _proposal_evidence_urls(["http://example.test/evidence.png"])

    @patch("services.community_tournament_control_service._now")
    @patch("services.community_tournament_control_service._advance_match_winner")
    def test_finalizing_result_proposal_advances_the_match(self, advance_winner, mocked_now):
        now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        winning_team_id = uuid.uuid4()
        proposal = SimpleNamespace(
            team_a_score=2,
            team_b_score=1,
            winner_team_id=winning_team_id,
            status="pending",
            finalized_at=None,
        )
        match = SimpleNamespace(team_a_score=None, team_b_score=None)
        mocked_now.return_value = now

        _finalize_result_proposal(proposal, match)

        self.assertEqual(match.team_a_score, 2)
        self.assertEqual(match.team_b_score, 1)
        self.assertEqual(proposal.status, "finalized")
        self.assertEqual(proposal.finalized_at, now)
        advance_winner.assert_called_once_with(match, winning_team_id)

    @patch("services.community_tournament_control_service.CommunityTournamentMatch")
    @patch("services.community_tournament_control_service._owned_tournament")
    def test_host_cannot_bypass_result_proposal_with_legacy_override(self, owned_tournament, match_model):
        tournament = SimpleNamespace(id=uuid.uuid4())
        owned_tournament.return_value = tournament
        match_model.query.filter_by.return_value.with_for_update.return_value.first.return_value = SimpleNamespace(
            id=uuid.uuid4()
        )

        with self.assertRaisesRegex(CommunityConflictError, "result proposal"):
            manage_match(7, tournament.id, uuid.uuid4(), {"action": "override_result"})

    @patch("services.community_tournament_service.db")
    @patch("services.community_tournament_service.sync_tournament_status", return_value=False)
    @patch("services.community_tournament_service.CommunityTournament")
    def test_unchanged_tournament_read_does_not_commit(self, tournament_model, _sync_status, mocked_db):
        tournament = SimpleNamespace(
            id=uuid.uuid4(),
            is_private=False,
            host_user_id=7,
            to_dict=lambda include_room_details=False: {"id": "tournament", "room": include_room_details},
        )
        tournament_model.query.filter_by.return_value.first.return_value = tournament

        payload = get_tournament(tournament.id)

        self.assertEqual(payload["id"], "tournament")
        mocked_db.session.commit.assert_not_called()

    def test_community_public_cache_serves_repeated_anonymous_requests(self):
        from controllers.community_tournament_controller import (
            _COMMUNITY_PUBLIC_CACHE,
            _community_public_cache_response,
        )

        app = Flask(__name__)
        app.config["COMMUNITY_PUBLIC_CACHE_TTL_SEC"] = 5
        app.config["API_MICROCACHE_MAX_ITEMS"] = 10
        _COMMUNITY_PUBLIC_CACHE.clear()
        calls = []
        with app.test_request_context("/api/v1/community/tournaments?page=1"):
            first = _community_public_cache_response("tournaments", lambda: calls.append(1) or {"items": []})
            second = _community_public_cache_response("tournaments", lambda: calls.append(1) or {"items": ["new"]})

        self.assertEqual(first.get_json(), {"items": []})
        self.assertEqual(second.get_json(), {"items": []})
        self.assertEqual(calls, [1])

    @patch("services.community_tournament_control_service.User")
    def test_roster_requires_game_ids_and_adds_captain(self, user_model):
        user_model.query.with_entities.return_value.filter.return_value.all.return_value = [
            SimpleNamespace(id=7),
            SimpleNamespace(id=8),
        ]
        user_model.query.filter_by.return_value.first.return_value = SimpleNamespace(game_username="Captain7")
        tournament = SimpleNamespace(team_size=2, substitute_limit=0)

        roster = _validate_roster(
            tournament,
            7,
            [{"user_id": 8, "game_id": "Player8", "role": "player"}],
        )

        self.assertEqual(len(roster), 2)
        self.assertEqual(roster[0]["user_id"], 7)
        self.assertEqual(roster[0]["role"], "captain")

    @patch("services.community_tournament_control_service.User")
    def test_roster_rejects_missing_game_id(self, user_model):
        tournament = SimpleNamespace(team_size=2, substitute_limit=0)

        with self.assertRaisesRegex(CommunityValidationError, "game_id"):
            _validate_roster(
                tournament,
                7,
                [{"user_id": 8, "game_id": "", "role": "player"}],
            )

        user_model.query.with_entities.assert_not_called()

    def test_invite_codes_are_stored_as_hashes(self):
        digest = _invite_code_hash("private-code")

        self.assertEqual(len(digest), 64)
        self.assertNotIn("private-code", digest)
        self.assertEqual(digest, _invite_code_hash("private-code"))

    def test_rule_template_always_contains_hash_safety_rules(self):
        payload = rule_template("Valorant")

        self.assertEqual(payload["template"]["match_format"], "Best of 3")
        self.assertGreaterEqual(len(payload["mandatory_hash_rules"]), 5)

    def test_prize_pool_deducts_platform_and_organizer_fees_separately(self):
        tournament = SimpleNamespace(
            entry_fee=100,
            registered_players_count=10,
            organizer_commission_rate=8,
            platform_fee_rate=10,
            host_tier="bronze",
        )

        _recalculate_prize_pool(tournament)

        self.assertEqual(float(tournament.total_collection), 1000.0)
        self.assertEqual(float(tournament.platform_fee_amount), 100.0)
        self.assertEqual(float(tournament.organizer_commission_amount), 80.0)
        self.assertEqual(float(tournament.prize_pool), 820.0)

    def test_scheduled_end_does_not_complete_tournament_with_unresolved_operations(self):
        now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        tournament = SimpleNamespace(
            status=CommunityTournamentStatus.PUBLISHED,
            registration_start_at=now - timedelta(hours=3),
            registration_end_at=now - timedelta(hours=2),
            tournament_start_at=now - timedelta(hours=1),
            tournament_end_at=now - timedelta(minutes=1),
            registered_players_count=4,
            max_players=16,
        )

        self.assertEqual(_derive_status(tournament, now), CommunityTournamentStatus.LIVE)

    def test_new_tournament_status_treats_unset_registration_count_as_zero(self):
        now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        tournament = SimpleNamespace(
            status=CommunityTournamentStatus.PUBLISHED,
            registration_start_at=now - timedelta(minutes=5),
            registration_end_at=now + timedelta(hours=1),
            tournament_start_at=now + timedelta(hours=2),
            registered_players_count=None,
            max_players=16,
        )

        self.assertEqual(_derive_status(tournament, now), CommunityTournamentStatus.REGISTRATION_OPEN)

    @patch("services.community_tournament_service.db")
    @patch("services.community_tournament_service._notify")
    @patch("services.community_tournament_service._audit")
    @patch("services.community_tournament_service._now")
    @patch("services.community_tournament_service._owned_tournament")
    def test_host_can_close_an_open_registration_window_early(
        self,
        owned_tournament,
        mocked_now,
        _audit,
        _notify,
        mocked_db,
    ):
        now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        tournament = SimpleNamespace(
            id=uuid.uuid4(),
            title="Community Cup",
            host_user_id=7,
            status=CommunityTournamentStatus.REGISTRATION_OPEN,
            registration_start_at=now - timedelta(hours=1),
            registration_end_at=now + timedelta(hours=1),
            tournament_start_at=now + timedelta(hours=2),
            registered_players_count=4,
            max_players=16,
        )
        owned_tournament.return_value = tournament
        mocked_now.return_value = now

        result = close_registration(7, tournament.id)

        self.assertIs(result, tournament)
        self.assertEqual(tournament.status, CommunityTournamentStatus.REGISTRATION_CLOSED)
        self.assertLess(tournament.registration_end_at, now)
        mocked_db.session.commit.assert_called_once()

    @patch("services.community_tournament_control_service.db")
    @patch("services.community_tournament_control_service._notify")
    @patch("services.community_tournament_control_service._audit")
    @patch("services.community_tournament_control_service._now")
    @patch("services.community_tournament_control_service.CommunityTournamentMatch")
    @patch("services.community_tournament_control_service._owned_tournament")
    def test_host_can_start_a_bracket_ready_tournament_early(
        self,
        owned_tournament,
        match_model,
        mocked_now,
        _audit,
        _notify,
        mocked_db,
    ):
        now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        tournament = SimpleNamespace(
            id=uuid.uuid4(),
            title="Community Cup",
            host_user_id=7,
            status=CommunityTournamentStatus.REGISTRATION_CLOSED,
            registration_start_at=now - timedelta(hours=2),
            registration_end_at=now + timedelta(hours=1),
            tournament_start_at=now + timedelta(hours=1),
            tournament_end_at=now + timedelta(hours=3),
            registered_players_count=4,
            max_players=16,
        )
        owned_tournament.return_value = tournament
        match_model.query.filter_by.return_value.first.return_value = SimpleNamespace(id=uuid.uuid4())
        mocked_now.return_value = now

        result = start_tournament(7, tournament.id)

        self.assertIs(result, tournament)
        self.assertEqual(tournament.status, CommunityTournamentStatus.LIVE)
        self.assertEqual(tournament.tournament_start_at, now)
        self.assertEqual(tournament.registration_end_at, now)
        mocked_db.session.commit.assert_called_once()

    @patch("services.community_tournament_service.CommunityFileAsset")
    def test_evidence_assets_must_belong_to_caller_and_tournament(self, asset_model):
        asset_id = uuid.uuid4()
        tournament_id = uuid.uuid4()
        asset_model.query.filter.return_value.all.return_value = [
            SimpleNamespace(
                id=asset_id,
                owner_user_id=99,
                tournament_id=tournament_id,
                purpose="result_evidence",
            )
        ]

        with self.assertRaises(CommunityForbiddenError):
            _validated_evidence_asset_ids(
                [str(asset_id)],
                tournament_id,
                7,
                {"result_evidence"},
            )


if __name__ == "__main__":
    unittest.main()
