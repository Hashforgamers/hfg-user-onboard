-- Join exactly 10 sample users to one community tournament.
--
-- Neon SQL Editor:
--   1. Replace the tournament UUID below.
--   2. Run the complete script.
--
-- This script creates users and confirmed registrations only. It does not create
-- teams, rosters, matches, results, or payouts. It is idempotent when rerun for
-- the same tournament. Paid tournaments use mock payment references.

BEGIN;

CREATE TEMP TABLE seed_input (
    tournament_id uuid PRIMARY KEY
) ON COMMIT DROP;

-- EDIT ONLY THIS VALUE.
INSERT INTO seed_input (tournament_id)
VALUES ('00000000-0000-0000-0000-000000000000');

CREATE TEMP TABLE seed_context ON COMMIT DROP AS
SELECT
    tournament.id AS tournament_id,
    tournament.title,
    tournament.entry_fee,
    tournament.currency,
    tournament.status,
    replace(tournament.id::text, '-', '') AS tournament_key
FROM community_tournaments tournament
JOIN seed_input input ON input.tournament_id = tournament.id;

DO $$
DECLARE
    context_count integer;
    context_status varchar(32);
BEGIN
    PERFORM 1
    FROM community_tournaments tournament
    JOIN seed_context context ON context.tournament_id = tournament.id
    FOR UPDATE OF tournament;

    SELECT count(*), max(status)
    INTO context_count, context_status
    FROM seed_context;

    IF context_count = 0 THEN
        RAISE EXCEPTION 'requested community tournament does not exist';
    END IF;

    IF context_status IN ('completed', 'cancelled') THEN
        RAISE EXCEPTION 'cannot seed a tournament in % state', context_status;
    END IF;
END $$;

INSERT INTO users (
    fid,
    name,
    game_username,
    parent_type,
    platform,
    referral_rewards
)
SELECT
    'hfg-sample-join10-' || context.tournament_key || '-' || lpad(sample.number::text, 2, '0'),
    'Sample Tournament User ' || lpad(sample.number::text, 2, '0'),
    'SAMPLE_' || left(context.tournament_key, 10) || '_' || lpad(sample.number::text, 2, '0'),
    'user',
    'test_seed',
    0
FROM seed_context context
CROSS JOIN generate_series(1, 10) AS sample(number)
ON CONFLICT (fid) DO UPDATE
SET
    name = EXCLUDED.name,
    platform = EXCLUDED.platform,
    updated_at = now();

INSERT INTO community_tournament_registrations (
    tournament_id,
    user_id,
    status,
    payment_status,
    amount_paid,
    payment_reference,
    payment_provider,
    razorpay_payment_id,
    razorpay_order_id,
    payment_verified_at,
    confirmed_at,
    paid_at
)
SELECT
    context.tournament_id,
    sample_user.id,
    'confirmed',
    CASE WHEN context.entry_fee > 0 THEN 'paid' ELSE 'not_required' END,
    CASE WHEN context.entry_fee > 0 THEN context.entry_fee ELSE 0 END,
    CASE
        WHEN context.entry_fee > 0
        THEN 'sample_pay_' || left(context.tournament_key, 23) || '_' || lpad(sample.number::text, 2, '0')
        ELSE NULL
    END,
    CASE WHEN context.entry_fee > 0 THEN 'mock' ELSE NULL END,
    CASE
        WHEN context.entry_fee > 0
        THEN 'sample_pay_' || left(context.tournament_key, 23) || '_' || lpad(sample.number::text, 2, '0')
        ELSE NULL
    END,
    CASE
        WHEN context.entry_fee > 0
        THEN 'sample_order_' || left(context.tournament_key, 21) || '_' || lpad(sample.number::text, 2, '0')
        ELSE NULL
    END,
    CASE WHEN context.entry_fee > 0 THEN now() ELSE NULL END,
    now(),
    CASE WHEN context.entry_fee > 0 THEN now() ELSE NULL END
FROM seed_context context
CROSS JOIN generate_series(1, 10) AS sample(number)
JOIN users sample_user
  ON sample_user.fid =
     'hfg-sample-join10-' || context.tournament_key || '-' || lpad(sample.number::text, 2, '0')
ON CONFLICT (tournament_id, user_id)
    WHERE status NOT IN ('cancelled', 'refunded')
DO UPDATE SET
    status = 'confirmed',
    payment_status = EXCLUDED.payment_status,
    amount_paid = EXCLUDED.amount_paid,
    payment_reference = EXCLUDED.payment_reference,
    payment_provider = EXCLUDED.payment_provider,
    razorpay_payment_id = EXCLUDED.razorpay_payment_id,
    razorpay_order_id = EXCLUDED.razorpay_order_id,
    payment_verified_at = EXCLUDED.payment_verified_at,
    confirmed_at = COALESCE(community_tournament_registrations.confirmed_at, now()),
    paid_at = EXCLUDED.paid_at,
    updated_at = now();

UPDATE community_tournaments tournament
SET
    registered_players_count = totals.confirmed_entries,
    max_players = GREATEST(tournament.max_players, totals.confirmed_entries + 1),
    total_collection = totals.total_collection,
    platform_fee_amount =
        round(totals.total_collection * tournament.platform_fee_rate / 100, 2),
    organizer_commission_amount =
        round(totals.total_collection * tournament.organizer_commission_rate / 100, 2),
    prize_pool =
        totals.total_collection
        - round(totals.total_collection * tournament.platform_fee_rate / 100, 2)
        - round(totals.total_collection * tournament.organizer_commission_rate / 100, 2),
    updated_at = now()
FROM (
    SELECT
        context.tournament_id,
        count(registration.id)::integer AS confirmed_entries,
        count(registration.id)::numeric * context.entry_fee AS total_collection
    FROM seed_context context
    LEFT JOIN community_tournament_registrations registration
      ON registration.tournament_id = context.tournament_id
     AND registration.status = 'confirmed'
    GROUP BY context.tournament_id, context.entry_fee
) totals
WHERE tournament.id = totals.tournament_id;

INSERT INTO community_audit_logs (
    actor_type,
    action,
    entity_type,
    entity_id,
    metadata
)
SELECT
    'system',
    'test_users_joined',
    'community_tournament',
    context.tournament_id::text,
    jsonb_build_object(
        'seed_type', 'hfg_sample_join_10',
        'user_count', 10,
        'paid_test_seed', context.entry_fee > 0
    )
FROM seed_context context
WHERE NOT EXISTS (
    SELECT 1
    FROM community_audit_logs audit
    WHERE audit.action = 'test_users_joined'
      AND audit.entity_type = 'community_tournament'
      AND audit.entity_id = context.tournament_id::text
      AND audit.metadata->>'seed_type' = 'hfg_sample_join_10'
);

SELECT
    tournament.id AS tournament_id,
    tournament.title,
    tournament.status,
    tournament.max_players,
    tournament.registered_players_count AS confirmed_entries,
    count(DISTINCT sample_user.id) AS sample_users_joined,
    tournament.total_collection,
    tournament.platform_fee_amount,
    tournament.organizer_commission_amount,
    tournament.prize_pool
FROM community_tournaments tournament
JOIN seed_context context ON context.tournament_id = tournament.id
LEFT JOIN users sample_user
  ON sample_user.fid LIKE
     'hfg-sample-join10-' || context.tournament_key || '-%'
GROUP BY tournament.id;

COMMIT;
