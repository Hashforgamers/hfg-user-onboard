-- Standalone community tournament module for Hash user-onboard service.
-- This schema is intentionally separate from cafe-owned events/tournaments.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS community_file_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id bigint NULL REFERENCES users(id) ON DELETE SET NULL,
    tournament_id uuid NULL,
    purpose varchar(64) NOT NULL,
    file_url text NOT NULL,
    storage_key text NULL,
    mime_type varchar(120) NULL,
    file_size_bytes bigint NULL,
    checksum varchar(128) NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_file_assets_owner_user_id ON community_file_assets(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_community_file_assets_tournament_id ON community_file_assets(tournament_id);
CREATE INDEX IF NOT EXISTS ix_community_file_assets_purpose ON community_file_assets(purpose);

CREATE TABLE IF NOT EXISTS community_host_verifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id bigint NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name varchar(160) NOT NULL,
    email varchar(254) NOT NULL,
    phone varchar(32) NOT NULL,
    government_id_asset_id uuid NULL REFERENCES community_file_assets(id),
    government_id_reference varchar(120) NULL,
    upi_id varchar(120) NOT NULL,
    address text NOT NULL,
    verification_status varchar(32) NOT NULL DEFAULT 'pending',
    host_tier varchar(32) NOT NULL DEFAULT 'bronze',
    average_rating numeric(3, 2) NOT NULL DEFAULT 0,
    dispute_rate numeric(5, 2) NOT NULL DEFAULT 0,
    completion_rate numeric(5, 2) NOT NULL DEFAULT 0,
    on_time_payout_rate numeric(5, 2) NOT NULL DEFAULT 0,
    policy_violation_count integer NOT NULL DEFAULT 0,
    rejection_reason text NULL,
    reviewed_by_admin_id bigint NULL,
    reviewed_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_host_verifications_user_id ON community_host_verifications(user_id);
CREATE INDEX IF NOT EXISTS ix_community_host_verifications_email ON community_host_verifications(email);
CREATE INDEX IF NOT EXISTS ix_community_host_verifications_phone ON community_host_verifications(phone);
CREATE INDEX IF NOT EXISTS ix_community_host_verifications_status ON community_host_verifications(verification_status);
CREATE INDEX IF NOT EXISTS ix_community_host_verifications_host_tier ON community_host_verifications(host_tier);

CREATE TABLE IF NOT EXISTS community_tournaments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    host_user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title varchar(200) NOT NULL,
    description text NULL,
    banner_asset_id uuid NULL REFERENCES community_file_assets(id),
    banner_url text NULL,
    game varchar(80) NOT NULL,
    tournament_type varchar(64) NOT NULL DEFAULT 'single_elimination',
    team_mode varchar(24) NOT NULL DEFAULT 'solo',
    entry_fee numeric(12, 2) NOT NULL DEFAULT 0,
    currency varchar(8) NOT NULL DEFAULT 'INR',
    max_players integer NOT NULL,
    registration_start_at timestamptz NOT NULL,
    registration_end_at timestamptz NOT NULL,
    tournament_start_at timestamptz NOT NULL,
    tournament_end_at timestamptz NULL,
    rules text NULL,
    prize_distribution jsonb NOT NULL DEFAULT '[]'::jsonb,
    discord_link text NULL,
    whatsapp_link text NULL,
    room_details text NULL,
    room_details_published_at timestamptz NULL,
    visibility boolean NOT NULL DEFAULT true,
    is_featured boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL DEFAULT 'draft',
    total_collection numeric(12, 2) NOT NULL DEFAULT 0,
    platform_fee_amount numeric(12, 2) NOT NULL DEFAULT 0,
    host_tier varchar(32) NOT NULL DEFAULT 'bronze',
    organizer_commission_rate numeric(5, 2) NOT NULL DEFAULT 8,
    organizer_commission_amount numeric(12, 2) NOT NULL DEFAULT 0,
    prize_pool numeric(12, 2) NOT NULL DEFAULT 0,
    registered_players_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_community_tournament_entry_fee_non_negative CHECK (entry_fee >= 0),
    CONSTRAINT ck_community_tournament_max_players_positive CHECK (max_players > 0),
    CONSTRAINT ck_community_tournament_registered_non_negative CHECK (registered_players_count >= 0),
    CONSTRAINT ck_community_tournament_commission_rate CHECK (organizer_commission_rate >= 0 AND organizer_commission_rate <= 100),
    CONSTRAINT ck_community_tournament_registration_window CHECK (registration_end_at > registration_start_at),
    CONSTRAINT ck_community_tournament_starts_after_registration CHECK (tournament_start_at >= registration_end_at)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_community_file_assets_tournament'
    ) THEN
        ALTER TABLE community_file_assets
            ADD CONSTRAINT fk_community_file_assets_tournament
            FOREIGN KEY (tournament_id) REFERENCES community_tournaments(id) ON DELETE CASCADE;
    END IF;
END $$;

ALTER TABLE community_host_verifications
    ADD COLUMN IF NOT EXISTS host_tier varchar(32) NOT NULL DEFAULT 'bronze',
    ADD COLUMN IF NOT EXISTS average_rating numeric(3, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS dispute_rate numeric(5, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS completion_rate numeric(5, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS on_time_payout_rate numeric(5, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS policy_violation_count integer NOT NULL DEFAULT 0;

ALTER TABLE community_tournaments
    ADD COLUMN IF NOT EXISTS host_tier varchar(32) NOT NULL DEFAULT 'bronze',
    ADD COLUMN IF NOT EXISTS organizer_commission_rate numeric(5, 2) NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS organizer_commission_amount numeric(12, 2) NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_tournament_commission_rate'
    ) THEN
        ALTER TABLE community_tournaments
            ADD CONSTRAINT ck_community_tournament_commission_rate
            CHECK (organizer_commission_rate >= 0 AND organizer_commission_rate <= 100);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_community_tournaments_host_user_id ON community_tournaments(host_user_id);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_status ON community_tournaments(status);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_visibility ON community_tournaments(visibility);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_is_featured ON community_tournaments(is_featured);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_created_at ON community_tournaments(created_at);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_host_tier ON community_tournaments(host_tier);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_discovery ON community_tournaments(visibility, status, registration_start_at, tournament_start_at);
CREATE INDEX IF NOT EXISTS ix_community_tournaments_host_status ON community_tournaments(host_user_id, status);

CREATE TABLE IF NOT EXISTS community_tournament_registrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status varchar(32) NOT NULL DEFAULT 'pending_payment',
    payment_status varchar(32) NOT NULL DEFAULT 'unpaid',
    amount_paid numeric(12, 2) NOT NULL DEFAULT 0,
    payment_reference varchar(120) NULL,
    checked_in_at timestamptz NULL,
    cancelled_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_tournament_registrations_tournament_id ON community_tournament_registrations(tournament_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_registrations_user_id ON community_tournament_registrations(user_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_registrations_status ON community_tournament_registrations(status);
CREATE INDEX IF NOT EXISTS ix_community_tournament_registrations_payment_status ON community_tournament_registrations(payment_status);
CREATE INDEX IF NOT EXISTS ix_community_tournament_registrations_payment_reference ON community_tournament_registrations(payment_reference);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_tournament_active_registration
    ON community_tournament_registrations(tournament_id, user_id)
    WHERE status NOT IN ('cancelled', 'refunded');

CREATE TABLE IF NOT EXISTS community_match_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    submitted_by_user_id bigint NULL REFERENCES users(id) ON DELETE SET NULL,
    winner_user_id bigint NULL REFERENCES users(id) ON DELETE SET NULL,
    rank integer NULL,
    score varchar(80) NULL,
    evidence_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    stream_url text NULL,
    notes text NULL,
    status varchar(32) NOT NULL DEFAULT 'submitted',
    verified_by_user_id bigint NULL,
    verified_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_match_results_tournament_id ON community_match_results(tournament_id);
CREATE INDEX IF NOT EXISTS ix_community_match_results_submitted_by_user_id ON community_match_results(submitted_by_user_id);
CREATE INDEX IF NOT EXISTS ix_community_match_results_winner_user_id ON community_match_results(winner_user_id);
CREATE INDEX IF NOT EXISTS ix_community_match_results_status ON community_match_results(status);
CREATE INDEX IF NOT EXISTS ix_community_results_tournament_rank ON community_match_results(tournament_id, rank);

CREATE TABLE IF NOT EXISTS community_tournament_disputes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    result_id uuid NULL REFERENCES community_match_results(id) ON DELETE SET NULL,
    reported_by_user_id bigint NULL REFERENCES users(id) ON DELETE SET NULL,
    reason varchar(120) NOT NULL,
    description text NOT NULL,
    evidence_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    status varchar(32) NOT NULL DEFAULT 'open',
    admin_comment text NULL,
    reviewed_by_admin_id bigint NULL,
    reviewed_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_tournament_disputes_tournament_id ON community_tournament_disputes(tournament_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_disputes_result_id ON community_tournament_disputes(result_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_disputes_reported_by_user_id ON community_tournament_disputes(reported_by_user_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_disputes_status ON community_tournament_disputes(status);

CREATE TABLE IF NOT EXISTS community_tournament_payouts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rank integer NULL,
    amount numeric(12, 2) NOT NULL,
    currency varchar(8) NOT NULL DEFAULT 'INR',
    status varchar(32) NOT NULL DEFAULT 'pending_admin_approval',
    approved_by_admin_id bigint NULL,
    approved_at timestamptz NULL,
    paid_at timestamptz NULL,
    wallet_transaction_id bigint NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_tournament_payouts_tournament_id ON community_tournament_payouts(tournament_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_payouts_user_id ON community_tournament_payouts(user_id);
CREATE INDEX IF NOT EXISTS ix_community_tournament_payouts_status ON community_tournament_payouts(status);

CREATE TABLE IF NOT EXISTS community_audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id bigint NULL,
    actor_type varchar(32) NOT NULL DEFAULT 'user',
    action varchar(100) NOT NULL,
    entity_type varchar(80) NOT NULL,
    entity_id varchar(80) NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_audit_logs_actor_user_id ON community_audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS ix_community_audit_logs_actor_type ON community_audit_logs(actor_type);
CREATE INDEX IF NOT EXISTS ix_community_audit_logs_action ON community_audit_logs(action);
CREATE INDEX IF NOT EXISTS ix_community_audit_logs_entity_type ON community_audit_logs(entity_type);
CREATE INDEX IF NOT EXISTS ix_community_audit_logs_entity_id ON community_audit_logs(entity_id);
CREATE INDEX IF NOT EXISTS ix_community_audit_logs_created_at ON community_audit_logs(created_at);
