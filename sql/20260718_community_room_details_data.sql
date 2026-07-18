-- Generic, game-neutral room/lobby details for confirmed community participants.

ALTER TABLE community_tournaments
    ADD COLUMN IF NOT EXISTS room_details_data jsonb NULL;
