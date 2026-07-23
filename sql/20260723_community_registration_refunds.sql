-- Durable, provider-backed refunds for community tournament registrations.

ALTER TABLE community_tournament_registrations
    ADD COLUMN IF NOT EXISTS refund_status varchar(32),
    ADD COLUMN IF NOT EXISTS refund_amount numeric(12, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS razorpay_refund_id varchar(120),
    ADD COLUMN IF NOT EXISTS refund_requested_at timestamptz,
    ADD COLUMN IF NOT EXISTS refunded_at timestamptz,
    ADD COLUMN IF NOT EXISTS refund_error text;

CREATE INDEX IF NOT EXISTS ix_community_registration_refund_status
    ON community_tournament_registrations(refund_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_registration_razorpay_refund_id
    ON community_tournament_registrations(razorpay_refund_id)
    WHERE razorpay_refund_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_community_registration_refund_pending
    ON community_tournament_registrations(status, refund_requested_at)
    WHERE status = 'refund_pending';
