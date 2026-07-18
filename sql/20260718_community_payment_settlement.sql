-- Verified Razorpay settlement state and a durable retry queue for community registrations.

ALTER TABLE community_tournament_registrations
    ADD COLUMN IF NOT EXISTS payment_provider varchar(32),
    ADD COLUMN IF NOT EXISTS razorpay_payment_id varchar(120),
    ADD COLUMN IF NOT EXISTS razorpay_order_id varchar(120),
    ADD COLUMN IF NOT EXISTS payment_verified_at timestamptz,
    ADD COLUMN IF NOT EXISTS confirmed_at timestamptz,
    ADD COLUMN IF NOT EXISTS paid_at timestamptz;

UPDATE community_tournament_registrations
SET payment_status = 'unpaid'
WHERE status = 'pending_payment'
  AND payment_status = 'pending';

CREATE INDEX IF NOT EXISTS ix_community_registration_razorpay_payment_id
    ON community_tournament_registrations(razorpay_payment_id);
CREATE INDEX IF NOT EXISTS ix_community_registration_razorpay_order_id
    ON community_tournament_registrations(razorpay_order_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_registration_razorpay_payment_id
    ON community_tournament_registrations(razorpay_payment_id)
    WHERE razorpay_payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS community_payment_settlement_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id uuid NOT NULL REFERENCES community_tournament_registrations(id) ON DELETE CASCADE,
    tournament_id uuid NOT NULL REFERENCES community_tournaments(id) ON DELETE CASCADE,
    provider varchar(32) NOT NULL DEFAULT 'razorpay',
    payment_id varchar(120) NULL,
    order_id varchar(120) NULL,
    status varchar(32) NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NULL,
    last_error text NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    settled_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_community_payment_settlement_job_registration
    ON community_payment_settlement_jobs(registration_id);
CREATE INDEX IF NOT EXISTS ix_community_payment_settlement_ready
    ON community_payment_settlement_jobs(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS ix_community_payment_settlement_payment_id
    ON community_payment_settlement_jobs(payment_id);
