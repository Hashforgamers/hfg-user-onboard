BEGIN;
CREATE TABLE IF NOT EXISTS hash_coin_spends (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    reference_id VARCHAR(128) NOT NULL,
    source VARCHAR(80) NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, reference_id)
);
COMMIT;
