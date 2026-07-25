-- Seed 20 deterministic test users into one community tournament.
--
-- Neon SQL Editor:
--   1. Replace the tournament UUID in seed_input below.
--   2. Run the complete script.
--
-- The script is idempotent for the same tournament. Test users are identified by
-- a tournament-specific fid beginning with "hfg-e2e-seed-".
-- Paid tournaments receive MOCK payment references; no Razorpay payment is used.
-- If needed, max_players is increased to leave one registration slot open.

BEGIN;

CREATE TEMP TABLE seed_input (
    tournament_id uuid PRIMARY KEY
) ON COMMIT DROP;

-- EDIT ONLY THIS VALUE.
INSERT INTO seed_input (tournament_id)
VALUES ('00000000-0000-0000-0000-000000000000');

CREATE TEMP TABLE seed_context ON COMMIT DROP AS
SELECT
    t.id AS tournament_id,
    t.title,
    t.team_mode,
    CASE WHEN t.team_mode = 'solo' THEN 1 ELSE t.team_size END AS roster_size,
    t.entry_fee,
    t.currency,
    t.max_players,
    t.status,
    replace(t.id::text, '-', '') AS tournament_key
FROM community_tournaments t
JOIN seed_input input ON input.tournament_id = t.id;

DO $$
DECLARE
    context_count integer;
    context_status varchar(32);
    context_roster_size integer;
    required_entries integer;
    existing_other_entries integer;
BEGIN
    PERFORM 1
    FROM community_tournaments tournament
    JOIN seed_context context ON context.tournament_id = tournament.id
    FOR UPDATE OF tournament;

    SELECT count(*) INTO context_count FROM seed_context;
    IF context_count = 0 THEN
        RAISE EXCEPTION 'requested community tournament does not exist';
    END IF;

    SELECT status, roster_size
    INTO context_status, context_roster_size
    FROM seed_context;

    IF context_status IN ('completed', 'cancelled') THEN
        RAISE EXCEPTION 'cannot seed a tournament in % state', context_status;
    END IF;

    IF context_roster_size <= 0 THEN
        RAISE EXCEPTION 'tournament team_size must be positive';
    END IF;

    IF 20 % context_roster_size <> 0 THEN
        RAISE EXCEPTION
            '20 test users cannot form complete rosters of %. Change team_size or adjust this seed script.',
            context_roster_size;
    END IF;

    required_entries := 20 / context_roster_size;

    SELECT count(*)
    INTO existing_other_entries
    FROM community_tournament_registrations registration
    CROSS JOIN seed_context context
    WHERE registration.tournament_id = context.tournament_id
      AND registration.status = 'confirmed'
      AND NOT EXISTS (
          SELECT 1
          FROM users seeded_user
          WHERE seeded_user.id = registration.user_id
            AND seeded_user.fid LIKE 'hfg-e2e-seed-' || context.tournament_key || '-%'
      );

    IF existing_other_entries + required_entries >= (SELECT max_players FROM seed_context) THEN
        UPDATE community_tournaments tournament
        SET
            max_players = existing_other_entries + required_entries + 1,
            updated_at = now()
        FROM seed_context context
        WHERE tournament.id = context.tournament_id;

        UPDATE seed_context
        SET max_players = existing_other_entries + required_entries + 1;
    END IF;
END $$;

CREATE TEMP TABLE seed_players (
    player_number integer PRIMARY KEY,
    user_id bigint,
    team_number integer,
    is_captain boolean
) ON COMMIT DROP;

INSERT INTO users (
    fid,
    name,
    game_username,
    parent_type,
    platform,
    referral_rewards
)
SELECT
    'hfg-e2e-seed-' || context.tournament_key || '-' || lpad(series.player_number::text, 2, '0'),
    'Tournament Test Player ' || lpad(series.player_number::text, 2, '0'),
    'E2E_' || left(context.tournament_key, 12) || '_' || lpad(series.player_number::text, 2, '0'),
    'user',
    'test_seed',
    0
FROM seed_context context
CROSS JOIN generate_series(1, 20) AS series(player_number)
ON CONFLICT (fid) DO UPDATE
SET
    name = EXCLUDED.name,
    platform = EXCLUDED.platform,
    updated_at = now();

INSERT INTO seed_players (player_number, user_id, team_number, is_captain)
SELECT
    series.player_number,
    seeded_user.id,
    ((series.player_number - 1) / context.roster_size) + 1,
    ((series.player_number - 1) % context.roster_size) = 0
FROM seed_context context
CROSS JOIN generate_series(1, 20) AS series(player_number)
JOIN users seeded_user
  ON seeded_user.fid =
     'hfg-e2e-seed-' || context.tournament_key || '-' || lpad(series.player_number::text, 2, '0');

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
    player.user_id,
    'confirmed',
    CASE WHEN context.entry_fee > 0 THEN 'paid' ELSE 'not_required' END,
    CASE WHEN context.entry_fee > 0 THEN context.entry_fee ELSE 0 END,
    CASE
        WHEN context.entry_fee > 0
        THEN 'seed_pay_' || left(context.tournament_key, 24) || '_' || lpad(player.player_number::text, 2, '0')
        ELSE NULL
    END,
    CASE WHEN context.entry_fee > 0 THEN 'mock' ELSE NULL END,
    CASE
        WHEN context.entry_fee > 0
        THEN 'seed_pay_' || left(context.tournament_key, 24) || '_' || lpad(player.player_number::text, 2, '0')
        ELSE NULL
    END,
    CASE
        WHEN context.entry_fee > 0
        THEN 'seed_order_' || left(context.tournament_key, 22) || '_' || lpad(player.player_number::text, 2, '0')
        ELSE NULL
    END,
    CASE WHEN context.entry_fee > 0 THEN now() ELSE NULL END,
    now(),
    CASE WHEN context.entry_fee > 0 THEN now() ELSE NULL END
FROM seed_context context
JOIN seed_players player ON player.is_captain
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

INSERT INTO community_tournament_teams (
    tournament_id,
    registration_id,
    captain_user_id,
    name,
    status
)
SELECT
    context.tournament_id,
    registration.id,
    captain.user_id,
    CASE
        WHEN context.team_mode = 'solo'
        THEN 'Seed Player ' || lpad(captain.player_number::text, 2, '0')
        ELSE 'Seed Team ' || lpad(captain.team_number::text, 2, '0')
    END,
    'approved'
FROM seed_context context
JOIN seed_players captain ON captain.is_captain
JOIN community_tournament_registrations registration
  ON registration.tournament_id = context.tournament_id
 AND registration.user_id = captain.user_id
 AND registration.status = 'confirmed'
ON CONFLICT (registration_id) DO UPDATE
SET
    captain_user_id = EXCLUDED.captain_user_id,
    status = 'approved',
    updated_at = now();

INSERT INTO community_tournament_team_members (
    tournament_id,
    team_id,
    user_id,
    role,
    game_id,
    verification_status
)
SELECT
    context.tournament_id,
    team.id,
    player.user_id,
    CASE WHEN player.is_captain THEN 'captain' ELSE 'player' END,
    'E2E-' || left(context.tournament_key, 8) || '-' || lpad(player.player_number::text, 2, '0'),
    'verified'
FROM seed_context context
JOIN seed_players player ON true
JOIN seed_players captain
  ON captain.team_number = player.team_number
 AND captain.is_captain
JOIN community_tournament_registrations registration
  ON registration.tournament_id = context.tournament_id
 AND registration.user_id = captain.user_id
 AND registration.status = 'confirmed'
JOIN community_tournament_teams team
  ON team.registration_id = registration.id
ON CONFLICT (team_id, user_id) DO UPDATE
SET
    role = EXCLUDED.role,
    game_id = EXCLUDED.game_id,
    verification_status = 'verified';

UPDATE community_tournaments tournament
SET
    registered_players_count = totals.confirmed_entries,
    total_collection = totals.total_collection,
    platform_fee_amount = round(totals.total_collection * tournament.platform_fee_rate / 100, 2),
    organizer_commission_amount = round(totals.total_collection * tournament.organizer_commission_rate / 100, 2),
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
    'test_participants_seeded',
    'community_tournament',
    context.tournament_id::text,
    jsonb_build_object(
        'seed_type', 'hfg_e2e_20_participants',
        'user_count', 20,
        'team_count', 20 / context.roster_size,
        'paid_test_seed', context.entry_fee > 0
    )
FROM seed_context context
WHERE NOT EXISTS (
    SELECT 1
    FROM community_audit_logs audit
    WHERE audit.action = 'test_participants_seeded'
      AND audit.entity_type = 'community_tournament'
      AND audit.entity_id = context.tournament_id::text
      AND audit.metadata->>'seed_type' = 'hfg_e2e_20_participants'
);

SELECT
    tournament.id AS tournament_id,
    tournament.title,
    tournament.team_mode,
    tournament.team_size,
    tournament.status,
    tournament.registered_players_count AS confirmed_entries,
    count(DISTINCT seeded_user.id) AS seeded_users,
    count(DISTINCT team.id) AS seeded_teams,
    count(DISTINCT member.user_id) AS seeded_team_members,
    tournament.total_collection,
    tournament.platform_fee_amount,
    tournament.organizer_commission_amount,
    tournament.prize_pool
FROM community_tournaments tournament
LEFT JOIN users seeded_user
  ON seeded_user.fid LIKE
     'hfg-e2e-seed-' || replace(tournament.id::text, '-', '') || '-%'
LEFT JOIN community_tournament_team_members member
  ON member.tournament_id = tournament.id
 AND member.user_id = seeded_user.id
LEFT JOIN community_tournament_teams team
  ON team.id = member.team_id
JOIN seed_context context ON context.tournament_id = tournament.id
GROUP BY tournament.id;

COMMIT;
