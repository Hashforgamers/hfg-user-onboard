-- Hot-path indexes for community tournament API reads and the deadline cron.
-- These are safe to run repeatedly in Neon SQL Editor.

CREATE INDEX IF NOT EXISTS ix_community_matches_tournament_round_match
    ON community_tournament_matches(tournament_id, round_number, match_number);

CREATE INDEX IF NOT EXISTS ix_community_matches_result_deadline
    ON community_tournament_matches(result_due_at)
    WHERE status = 'awaiting_results' AND result_due_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_community_teams_tournament_status_order
    ON community_tournament_teams(tournament_id, status, seed_number, created_at);

CREATE INDEX IF NOT EXISTS ix_community_registrations_tournament_status_created
    ON community_tournament_registrations(tournament_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_community_team_members_tournament_user_role
    ON community_tournament_team_members(tournament_id, user_id, role, verification_status);

CREATE INDEX IF NOT EXISTS ix_community_audit_logs_entity_created
    ON community_audit_logs(entity_id, created_at DESC);
