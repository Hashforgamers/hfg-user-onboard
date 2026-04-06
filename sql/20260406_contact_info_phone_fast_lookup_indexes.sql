-- Fast lookup indexes for user phone registration APIs.
-- Safe to run multiple times.

CREATE INDEX IF NOT EXISTS idx_contact_info_user_parent_lookup
    ON contact_info (parent_type, parent_id);

CREATE INDEX IF NOT EXISTS idx_contact_info_user_phone_lookup
    ON contact_info (parent_type, phone);

