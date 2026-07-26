CREATE TABLE IF NOT EXISTS community_match_result_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    match_id uuid NOT NULL REFERENCES community_tournament_matches(id) ON DELETE CASCADE,
    proposed_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    winner_team_id uuid NOT NULL REFERENCES community_tournament_teams(id) ON DELETE RESTRICT,
    team_a_score integer NOT NULL CHECK (team_a_score >= 0),
    team_b_score integer NOT NULL CHECK (team_b_score >= 0),
    evidence_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidence_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
    ocr_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    accepted_team_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    status varchar(24) NOT NULL DEFAULT 'pending',
    expires_at timestamptz NOT NULL,
    finalized_at timestamptz,
    disputed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_pending_result_proposal
    ON community_match_result_proposals(match_id) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS ix_community_result_proposals_due
    ON community_match_result_proposals(status, expires_at);
