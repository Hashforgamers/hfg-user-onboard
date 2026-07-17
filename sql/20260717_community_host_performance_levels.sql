-- Adds host performance levels and organizer commission snapshots to an
-- existing community tournament database.

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

UPDATE community_tournaments
SET
    organizer_commission_rate = 8
WHERE organizer_commission_rate IS NULL;

UPDATE community_tournaments
SET
    organizer_commission_amount = ROUND((COALESCE(total_collection, 0) * organizer_commission_rate / 100)::numeric, 2),
    platform_fee_amount = ROUND((COALESCE(total_collection, 0) * organizer_commission_rate / 100)::numeric, 2),
    prize_pool = COALESCE(total_collection, 0) - ROUND((COALESCE(total_collection, 0) * organizer_commission_rate / 100)::numeric, 2)
WHERE organizer_commission_amount = 0
  AND COALESCE(total_collection, 0) > 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_community_tournament_commission_rate'
    ) THEN
        ALTER TABLE community_tournaments
            ADD CONSTRAINT ck_community_tournament_commission_rate
            CHECK (organizer_commission_rate >= 0 AND organizer_commission_rate <= 100);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_community_host_verifications_host_tier
    ON community_host_verifications(host_tier);

CREATE INDEX IF NOT EXISTS ix_community_tournaments_host_tier
    ON community_tournaments(host_tier);
