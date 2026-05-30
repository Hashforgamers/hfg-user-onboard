CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE events
  ADD COLUMN IF NOT EXISTS game varchar(64) NOT NULL DEFAULT 'valorant',
  ADD COLUMN IF NOT EXISTS format varchar(64) NOT NULL DEFAULT 'single_elimination',
  ADD COLUMN IF NOT EXISTS prize_pool numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS team_size integer NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS match_rules text,
  ADD COLUMN IF NOT EXISTS region varchar(80),
  ADD COLUMN IF NOT EXISTS server varchar(80),
  ADD COLUMN IF NOT EXISTS check_in_starts_at timestamptz,
  ADD COLUMN IF NOT EXISTS check_in_ends_at timestamptz,
  ADD COLUMN IF NOT EXISTS map_pool jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS veto_mode varchar(64) NOT NULL DEFAULT 'none';

ALTER TABLE registrations
  ADD COLUMN IF NOT EXISTS checked_in_at timestamptz,
  ADD COLUMN IF NOT EXISTS seed_number integer;

CREATE TABLE IF NOT EXISTS tournament_seeds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  seed_number integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tournament_seed_team UNIQUE (event_id, team_id),
  CONSTRAINT uq_tournament_seed_number UNIQUE (event_id, seed_number)
);

CREATE TABLE IF NOT EXISTS tournament_matches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  round_number integer NOT NULL,
  match_number integer NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'pending',
  team_a_id uuid REFERENCES teams(id) ON DELETE SET NULL,
  team_b_id uuid REFERENCES teams(id) ON DELETE SET NULL,
  winner_team_id uuid REFERENCES teams(id) ON DELETE SET NULL,
  scheduled_at timestamptz,
  lobby_instructions text,
  map_name varchar(80),
  server_region varchar(80),
  admin_notes text,
  map_pool jsonb NOT NULL DEFAULT '[]'::jsonb,
  veto_mode varchar(64) NOT NULL DEFAULT 'none',
  team_a_captain_confirmed_at timestamptz,
  team_b_captain_confirmed_at timestamptz,
  observer_user_id integer,
  stream_url text,
  match_timer_started_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tournament_match_slot UNIQUE (event_id, round_number, match_number)
);

CREATE TABLE IF NOT EXISTS match_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id uuid NOT NULL REFERENCES tournament_matches(id) ON DELETE CASCADE,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  side varchar(16) NOT NULL,
  captain_confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_match_participant_team UNIQUE (match_id, team_id),
  CONSTRAINT uq_match_participant_side UNIQUE (match_id, side)
);

CREATE TABLE IF NOT EXISTS match_result_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id uuid NOT NULL REFERENCES tournament_matches(id) ON DELETE CASCADE,
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  submitted_by_user bigint,
  submitted_by_vendor bigint,
  winner_team_id uuid REFERENCES teams(id) ON DELETE SET NULL,
  team_a_score integer,
  team_b_score integer,
  screenshot_url text,
  notes text,
  status varchar(32) NOT NULL DEFAULT 'submitted',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS match_disputes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id uuid NOT NULL REFERENCES tournament_matches(id) ON DELETE CASCADE,
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  opened_by_user bigint,
  opened_by_vendor bigint,
  team_id uuid REFERENCES teams(id) ON DELETE SET NULL,
  reason text,
  status varchar(32) NOT NULL DEFAULT 'open',
  resolution text,
  resolved_by_vendor bigint,
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS map_veto_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id uuid NOT NULL REFERENCES tournament_matches(id) ON DELETE CASCADE,
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  actor_user_id bigint,
  action varchar(24) NOT NULL,
  map_name varchar(80) NOT NULL,
  action_order integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_map_veto_order UNIQUE (match_id, action_order)
);

CREATE INDEX IF NOT EXISTS ix_tournament_matches_event_round ON tournament_matches(event_id, round_number, match_number);
CREATE INDEX IF NOT EXISTS ix_tournament_matches_team_a ON tournament_matches(team_a_id);
CREATE INDEX IF NOT EXISTS ix_tournament_matches_team_b ON tournament_matches(team_b_id);
CREATE INDEX IF NOT EXISTS ix_match_result_submissions_match ON match_result_submissions(match_id);
CREATE INDEX IF NOT EXISTS ix_match_disputes_match_status ON match_disputes(match_id, status);
CREATE INDEX IF NOT EXISTS ix_map_veto_actions_match ON map_veto_actions(match_id, action_order);
