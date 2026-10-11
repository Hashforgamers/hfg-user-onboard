BEGIN;
ALTER TABLE hash_coin_spends ADD COLUMN IF NOT EXISTS item_id VARCHAR(128);
CREATE TABLE IF NOT EXISTS hash_coin_items (
    source VARCHAR(80) NOT NULL CHECK (source IN ('ludo_skin_purchase','mini_game_cosmetic')),
    item_id VARCHAR(128) NOT NULL,
    price INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (source,item_id),
    CHECK ((source='ludo_skin_purchase' AND price BETWEEN 400 AND 10000)
        OR (source='mini_game_cosmetic' AND price BETWEEN 300 AND 4000))
);
CREATE TABLE IF NOT EXISTS hash_coin_purchases (
    user_id INTEGER NOT NULL REFERENCES users(id),
    source VARCHAR(80) NOT NULL,
    item_id VARCHAR(128) NOT NULL,
    spend_id BIGINT NOT NULL UNIQUE REFERENCES hash_coin_spends(id),
    purchased_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id,source,item_id)
);
COMMIT;
