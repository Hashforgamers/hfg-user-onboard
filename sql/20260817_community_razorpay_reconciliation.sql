-- Durable, replay-safe Razorpay reconciliation for community tournaments.

CREATE TABLE IF NOT EXISTS community_payment_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id uuid NOT NULL REFERENCES community_tournament_registrations(id) ON DELETE CASCADE,
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider varchar(32) NOT NULL DEFAULT 'razorpay',
    receipt varchar(40) NOT NULL UNIQUE,
    amount numeric(12, 2) NOT NULL CHECK (amount >= 0),
    currency varchar(8) NOT NULL,
    provider_order_id varchar(120) UNIQUE,
    provider_payment_id varchar(120) UNIQUE,
    status varchar(32) NOT NULL DEFAULT 'created',
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_community_payment_attempt_registration_status
    ON community_payment_attempts(registration_id, status);

CREATE TABLE IF NOT EXISTS community_payment_webhook_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider varchar(32) NOT NULL DEFAULT 'razorpay',
    provider_event_id varchar(160) NOT NULL UNIQUE,
    event_type varchar(80) NOT NULL,
    -- No FK here: webhook delivery can precede registration commit.
    registration_id uuid,
    payment_id varchar(120),
    order_id varchar(120),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(32) NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    last_error text,
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_community_payment_webhook_ready
    ON community_payment_webhook_events(status, next_attempt_at);

-- Imported legacy orders remain valid only when their Razorpay order notes or
-- receipt identify the same registration. New orders are created from attempts.
