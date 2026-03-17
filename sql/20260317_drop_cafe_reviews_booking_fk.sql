-- Drop booking FK from cafe_reviews (bookings table is in another service DB/metadata)
ALTER TABLE cafe_reviews
  DROP CONSTRAINT IF EXISTS cafe_reviews_booking_id_fkey;
