CREATE TABLE IF NOT EXISTS notification_campaign_settings (
 id INTEGER PRIMARY KEY CHECK(id=1),
 context TEXT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 fallback_title VARCHAR(80) NOT NULL,
 fallback_message VARCHAR(200) NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
