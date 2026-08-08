-- Server-owned Firebase chat references for community tournament disputes.

ALTER TABLE community_tournament_disputes
    ADD COLUMN IF NOT EXISTS chat_room_id varchar(160),
    ADD COLUMN IF NOT EXISTS chat_room_status varchar(24) NOT NULL DEFAULT 'not_requested';

CREATE UNIQUE INDEX IF NOT EXISTS uq_community_dispute_chat_room_id
    ON community_tournament_disputes(chat_room_id)
    WHERE chat_room_id IS NOT NULL;
