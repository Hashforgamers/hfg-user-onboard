-- Seven-day user deletion quarantine and purge audit manifest.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS purge_after timestamptz,
    ADD COLUMN IF NOT EXISTS deletion_status varchar(32);

CREATE INDEX IF NOT EXISTS ix_users_pending_purge
    ON users (purge_after)
    WHERE deleted_at IS NOT NULL AND deletion_status = 'pending_purge';

CREATE TABLE IF NOT EXISTS user_deletion_archives (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    original_user_id bigint NOT NULL,
    original_fid_hash varchar(64),
    deletion_status varchar(32) NOT NULL,
    deleted_at timestamptz,
    purged_at timestamptz,
    record_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_deletion_archives_original_user
    ON user_deletion_archives (original_user_id, created_at DESC);
