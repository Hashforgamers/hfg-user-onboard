-- Preserve and refund every verified duplicate community-tournament payment.

CREATE TABLE IF NOT EXISTS community_duplicate_payment_recoveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id uuid NOT NULL REFERENCES community_tournament_registrations(id) ON DELETE CASCADE,
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider varchar(32) NOT NULL DEFAULT 'razorpay',
    payment_id varchar(120) NOT NULL UNIQUE,
    order_id varchar(120),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    currency varchar(8) NOT NULL,
    reason text NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'pending_refund',
    refund_id varchar(120) UNIQUE,
    refund_status varchar(32),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    last_error text,
    refunded_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_community_duplicate_payment_recovery_ready
    ON community_duplicate_payment_recoveries(status, next_attempt_at);
