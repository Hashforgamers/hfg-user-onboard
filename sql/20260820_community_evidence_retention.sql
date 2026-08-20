ALTER TABLE community_tournaments
    ADD COLUMN IF NOT EXISTS completed_at timestamptz;

-- Existing completed tournaments lack a completion timestamp. Their last update
-- is the conservative retention baseline.
UPDATE community_tournaments
SET completed_at = updated_at
WHERE status = 'completed' AND completed_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_community_tournaments_completed_at
    ON community_tournaments(status, completed_at)
    WHERE status = 'completed';
