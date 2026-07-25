-- Community esports configuration, teams, brackets, captain results, and announcements.

ALTER TABLE community_tournaments
    ADD COLUMN IF NOT EXISTS game_mode varchar(80),
    ADD COLUMN IF NOT EXISTS platform varchar(24) NOT NULL DEFAULT 'cross_platform',
    ADD COLUMN IF NOT EXISTS organization_name varchar(160),
    ADD COLUMN IF NOT EXISTS team_size integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS substitute_limit integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS minimum_age integer,
    ADD COLUMN IF NOT EXISTS region varchar(80),
    ADD COLUMN IF NOT EXISTS registration_policy varchar(32) NOT NULL DEFAULT 'automatic',
    ADD COLUMN IF NOT EXISTS is_private boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS invite_code_hash varchar(128),
    ADD COLUMN IF NOT EXISTS min_entries integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS roster_lock_at timestamptz,
    ADD COLUMN IF NOT EXISTS check_in_start_at timestamptz,
    ADD COLUMN IF NOT EXISTS check_in_end_at timestamptz,
    ADD COLUMN IF NOT EXISTS match_duration_minutes integer NOT NULL DEFAULT 45,
    ADD COLUMN IF NOT EXISTS break_duration_minutes integer NOT NULL DEFAULT 15,
    ADD COLUMN IF NOT EXISTS max_matches_per_team_per_day integer NOT NULL DEFAULT 6,
    ADD COLUMN IF NOT EXISTS result_submission_window_minutes integer NOT NULL DEFAULT 15,
    ADD COLUMN IF NOT EXISTS dispute_window_minutes integer NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS schedule_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS rules_config jsonb NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'community_tournaments'
          AND column_name = 'platform_fee_rate'
    ) THEN
        ALTER TABLE community_tournaments
            ADD COLUMN platform_fee_rate numeric(5, 2) NOT NULL DEFAULT 0;
        -- platform_fee_amount previously mirrored organizer commission. Existing
        -- tournaments keep the same prize pool with a zero Hash fee snapshot.
        UPDATE community_tournaments SET platform_fee_amount = 0;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_team_size_positive') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_team_size_positive CHECK (team_size > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_substitute_limit_non_negative') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_substitute_limit_non_negative CHECK (substitute_limit >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_min_entries') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_min_entries CHECK (min_entries > 0 AND min_entries <= max_players);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_match_duration_positive') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_match_duration_positive CHECK (match_duration_minutes > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_break_non_negative') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_break_non_negative CHECK (break_duration_minutes >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_result_window_positive') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_result_window_positive CHECK (result_submission_window_minutes > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_dispute_window_positive') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_dispute_window_positive CHECK (dispute_window_minutes > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_platform_fee_rate') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_platform_fee_rate CHECK (platform_fee_rate >= 0 AND platform_fee_rate <= 100);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_total_fee_rate') THEN
        ALTER TABLE community_tournaments ADD CONSTRAINT ck_community_tournament_total_fee_rate CHECK (platform_fee_rate + organizer_commission_rate <= 100);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS community_tournament_teams (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    registration_id uuid NOT NULL UNIQUE REFERENCES community_tournament_registrations(id) ON DELETE CASCADE,
    captain_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name varchar(120) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'pending',
    seed_number integer,
    roster_locked_at timestamptz,
    checked_in_at timestamptz,
    warning_count integer NOT NULL DEFAULT 0,
    rejection_reason text,
    disqualification_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_community_team_warning_count CHECK (warning_count >= 0),
    CONSTRAINT ck_community_team_seed_positive CHECK (seed_number IS NULL OR seed_number > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_team_name ON community_tournament_teams(tournament_id, name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_team_seed ON community_tournament_teams(tournament_id, seed_number) WHERE seed_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_community_teams_tournament_status ON community_tournament_teams(tournament_id, status);

CREATE TABLE IF NOT EXISTS community_tournament_team_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    team_id uuid NOT NULL REFERENCES community_tournament_teams(id) ON DELETE CASCADE,
    user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role varchar(24) NOT NULL DEFAULT 'player',
    game_id varchar(120) NOT NULL,
    verification_status varchar(24) NOT NULL DEFAULT 'pending',
    joined_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_team_member ON community_tournament_team_members(team_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_tournament_accepted_member
    ON community_tournament_team_members(tournament_id, user_id)
    WHERE verification_status IN ('accepted', 'verified');

CREATE TABLE IF NOT EXISTS community_tournament_matches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    stage varchar(32) NOT NULL DEFAULT 'bracket',
    round_number integer NOT NULL,
    match_number integer NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'scheduled',
    team_a_id uuid REFERENCES community_tournament_teams(id) ON DELETE SET NULL,
    team_b_id uuid REFERENCES community_tournament_teams(id) ON DELETE SET NULL,
    participant_team_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    winner_team_id uuid REFERENCES community_tournament_teams(id) ON DELETE SET NULL,
    next_match_id uuid REFERENCES community_tournament_matches(id) ON DELETE SET NULL,
    next_match_slot varchar(1),
    team_a_score integer,
    team_b_score integer,
    scheduled_at timestamptz,
    started_at timestamptz,
    result_due_at timestamptz,
    completed_at timestamptz,
    lobby_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    standings jsonb NOT NULL DEFAULT '[]'::jsonb,
    stream_url text,
    admin_notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_community_match_team_a_score CHECK (team_a_score IS NULL OR team_a_score >= 0),
    CONSTRAINT ck_community_match_team_b_score CHECK (team_b_score IS NULL OR team_b_score >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_match_slot ON community_tournament_matches(tournament_id, stage, round_number, match_number);
CREATE INDEX IF NOT EXISTS ix_community_matches_tournament_status ON community_tournament_matches(tournament_id, status);
CREATE INDEX IF NOT EXISTS ix_community_matches_scheduled_at ON community_tournament_matches(scheduled_at);

CREATE TABLE IF NOT EXISTS community_match_result_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id uuid NOT NULL REFERENCES community_tournament_matches(id) ON DELETE CASCADE,
    team_id uuid NOT NULL REFERENCES community_tournament_teams(id) ON DELETE CASCADE,
    submitted_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    winner_team_id uuid REFERENCES community_tournament_teams(id) ON DELETE SET NULL,
    team_a_score integer,
    team_b_score integer,
    evidence_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    notes text,
    status varchar(24) NOT NULL DEFAULT 'submitted',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_match_submission_team ON community_match_result_submissions(match_id, team_id);

CREATE TABLE IF NOT EXISTS community_tournament_announcements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    created_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    title varchar(160) NOT NULL,
    message text NOT NULL,
    audience varchar(32) NOT NULL DEFAULT 'all_participants',
    target_team_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    published_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_community_announcements_tournament_published
    ON community_tournament_announcements(tournament_id, published_at DESC);

CREATE TABLE IF NOT EXISTS community_tournament_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    host_user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reviewer_user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    management_rating integer NOT NULL CHECK (management_rating BETWEEN 1 AND 5),
    communication_rating integer NOT NULL CHECK (communication_rating BETWEEN 1 AND 5),
    fairness_rating integer NOT NULL CHECK (fairness_rating BETWEEN 1 AND 5),
    scheduling_rating integer NOT NULL CHECK (scheduling_rating BETWEEN 1 AND 5),
    dispute_handling_rating integer NOT NULL CHECK (dispute_handling_rating BETWEEN 1 AND 5),
    overall_rating numeric(3, 2) NOT NULL,
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_tournament_reviewer
    ON community_tournament_reviews(tournament_id, reviewer_user_id);
CREATE INDEX IF NOT EXISTS ix_community_reviews_host_created
    ON community_tournament_reviews(host_user_id, created_at DESC);

ALTER TABLE community_tournament_disputes
    ADD COLUMN IF NOT EXISTS match_id uuid REFERENCES community_tournament_matches(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS response_deadline_at timestamptz,
    ADD COLUMN IF NOT EXISTS resolution_action varchar(32);
CREATE INDEX IF NOT EXISTS ix_community_disputes_match_id ON community_tournament_disputes(match_id);

ALTER TABLE community_tournament_payouts
    ADD COLUMN IF NOT EXISTS payout_type varchar(32) NOT NULL DEFAULT 'player_prize';
CREATE INDEX IF NOT EXISTS ix_community_payout_type ON community_tournament_payouts(payout_type);
