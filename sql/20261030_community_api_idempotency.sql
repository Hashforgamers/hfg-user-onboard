-- Apply before deploying Idempotency-Key support. No user/provider secrets stored.
BEGIN;
CREATE TABLE IF NOT EXISTS community_api_idempotency (
    scope_hash VARCHAR(64) PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL,
    response_body JSONB NOT NULL,
    response_status INTEGER NOT NULL CHECK (response_status BETWEEN 200 AND 399),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_community_api_idempotency_created_at
    ON community_api_idempotency (created_at);
COMMIT;
