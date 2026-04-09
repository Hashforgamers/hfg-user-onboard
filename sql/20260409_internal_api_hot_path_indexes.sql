-- Internal API hot-path indexes for user-onboard read endpoints.
-- Safe to run multiple times.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_transactions_user_created_at_desc
    ON transactions (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_user_booking_date_time_desc
    ON transactions (user_id, booking_date DESC, booking_time DESC);

CREATE INDEX IF NOT EXISTS idx_hash_wallet_transactions_user_timestamp_desc
    ON hash_wallet_transactions (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_vouchers_user_active_created_desc
    ON vouchers (user_id, is_active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_passes_user_active_valid_to
    ON user_passes (user_id, is_active, valid_to DESC);

CREATE INDEX IF NOT EXISTS idx_user_passes_user_cafe_pass
    ON user_passes (user_id, cafe_pass_id);

CREATE INDEX IF NOT EXISTS idx_cafe_passes_active_vendor_mode
    ON cafe_passes (is_active, vendor_id, pass_mode);

CREATE INDEX IF NOT EXISTS idx_extra_service_category_vendor_active
    ON extra_service_categories (vendor_id, is_active);

CREATE INDEX IF NOT EXISTS idx_extra_service_menu_category_active
    ON extra_service_menus (category_id, is_active);

CREATE INDEX IF NOT EXISTS idx_extra_service_menu_images_menu_active_primary
    ON extra_service_menu_images (menu_id, is_active, is_primary DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created_desc
    ON notifications (user_id, is_read, created_at DESC);

COMMIT;
