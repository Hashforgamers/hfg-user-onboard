-- A match may have one active dispute case. Historical resolved cases remain intact.
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_active_dispute_per_match
    ON community_tournament_disputes(match_id)
    WHERE match_id IS NOT NULL AND status IN ('open', 'under_review');
