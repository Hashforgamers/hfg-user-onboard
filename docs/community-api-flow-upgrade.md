# Community tournament flow upgrade — 30 October 2026

This is the current frontend contract for the community flow changes. It supersedes older documentation describing missing player inboxes, host-only check-in, automatic check-in during generation, and registration-only access for teammates. All paths below are relative to `/api/v1/community` and require the user's Bearer JWT. These changes are implemented locally; deployment is separate.

## New endpoints

| Method/path | Response and intended use |
| --- | --- |
| `GET /tournaments/{id}/me?invite_code=...` | `tournament`, current/latest `registration` or null, accepted `team` or null, `invitations`, assigned `matches`, `current_match`, `actions`, `server_time`. Use as the player screen bootstrap. A roster member need not have a personal registration. |
| `GET /me/team-invitations?page=1&per_page=50` | Paginated invited memberships with tournament ID/title, team name, and `can_respond`. Respond through the existing team invitation endpoint. |
| `GET /tournaments/{id}/matches/me?status=in_progress` | `{items:[...]}` containing only matches assigned to the caller's eligible team, including private lobby details. An unassigned user receives an empty list. |
| `POST /tournaments/{id}/check-in` | Body `{}`; returns `registration` and `team` (null for a solo entry with no engine team yet). Solo entrants check themselves in; captains check their whole team in. Repeated successful check-in preserves its timestamp. |
| `GET /me/disputes?page=1&per_page=50&status=open` | Paginated cases visible as reporter, tournament host or accepted member of an assigned match team; includes multi-team matches. |
| `GET /disputes/{id}` | One authorized dispute, including status, evidence asset IDs, response deadline, referee comment and chat metadata. Unauthorized callers get 403. |
| `GET /me/payouts?page=1&per_page=50&status=paid` | Caller-owned payouts, with `destination: "hash_wallet"`. Do not label these bank transfers. |
| `GET /tournaments/{id}/finalization-preview` | Host-only: `ready_to_finalize`, `blockers`, unfinished matches, open disputes, eligible payees, proposed awards/totals, currency, commission, payout policy and existing payouts. `requires_winner_selection: true` means the host must select actual winners. |

Paginated new inbox responses use `items` and `pagination: {page, per_page, total, pages}`; per-page maximum is 100. Invalid pagination integers return 400. Existing invitation response paths still use tournament/team IDs, not membership IDs.

### Player screen bootstrap

`actions` contains `can_manage`, `can_join`, `can_continue_payment`, `can_check_in`, `can_cancel_registration`, `can_view_match`, and `can_play`. These are UI hints; refresh after writes and handle server conflicts. `can_play` requires an assigned in-progress match. Match-specific proposal actions still come from `/matches/{match_id}/result-state`.

## Changed behavior

- Confirmed solo entrants and accepted/verified members of **approved teams with a confirmed registration** share the participant eligibility policy. A disqualified/rejected team or pending payment does not grant play access.
- Tournament-level room details and evidence upload/registration use this policy. Assigned match result access uses the same policy plus assignment. General private match lists redact credentials for opponents' unrelated matches; `/matches/me` returns only assigned matches.
- Private tournament overview can be opened by an invited/accepted roster member without separately re-entering the invite code. This does not grant room credentials to an unapproved team.
- Invitation accept/decline locks the tournament/team records, checks lifecycle, roster lock and team state, and rejects already-answered invitations. Use captain roster management to change an accepted roster.
- POST creation with `status=published` and PATCH publication both enforce readiness blockers. Saving an incomplete draft remains supported.
- Host proposal action flags and proposal writes use the same blocker function. Pending proposals, open disputes and unsupported match states/formats prevent proposal creation.
- Bracket generation no longer auto-checks entrants in. Approved entrants remain eligible for generation; attendance is tracked independently. Self-check-in respects configured windows, confirmed registration, team approval and captain ownership. Without a configured opening time, registration must be closed.
- Start supports both head-to-head and multi-team matches. Multi-team dispute authorization includes all `participant_team_ids`; chat room participants also include those teams.
- Host standings cannot overwrite a closed match or bypass an active dispute. A referee can resolve an unresolved multi-team match using complete standings through the existing admin `resolve-result` endpoint.

### Multi-team referee decision

```json
{
  "reason": "Reviewed all scoreboard evidence",
  "standings": [
    {"team_id": "team-a-uuid", "placement": 1, "kills": 12, "penalty_points": 0},
    {"team_id": "team-b-uuid", "placement": 2, "kills": 7, "penalty_points": 0}
  ]
}
```

Every configured participant must appear exactly once with a unique positive placement. Scores use the existing placement-points configuration, kills and penalties, or explicit `points`. Head-to-head referee payloads remain winner_team_id plus both scores. Multi-team host proposals/captain score consensus are not supported: their outcome contract is full standings, not two scores.

## Team awards and finalization

The supported team payout policy is **captain**. Team awards credit the confirmed captain registration's Hash wallet. There is no automatic split across roster members. Solo awards continue to use user IDs. Existing team user-ID submissions are accepted only for an approved team's captain.

```json
{
  "winners": [
    {"team_id": "approved-team-uuid", "rank": 1, "amount": 100}
  ]
}
```

A caller-supplied `user_id` alongside `team_id` must match that team's captain. Invalid/unapproved teams and mismatched/unconfirmed payees are rejected. Finalization preview and submission share lifecycle/dispute/match/payout blockers. Submission still revalidates recipients, unique positive ranks, unique users and total prize budget while holding the tournament lock. Amount zero/omitted uses the configured share for that explicit rank. Preview is not a reservation; refetch after 409.

Prizes enter `pending_admin_approval`. Admin approval and settlement remain separate. `paid` records a Hash wallet credit. The preview intentionally does not infer a champion from total league points for an elimination bracket; the host selects winners from eligible recipients.

## Safe write retries

Send a unique **`Idempotency-Key`** (1–128 nonblank characters) for a logical action. Retry the same path and JSON payload with the same key after a timeout. The key is scoped to authenticated user, method and path.

A replay returns the original JSON/status and `Idempotency-Replayed: true`. Reusing the key with a different JSON payload returns 409. A failed write rolls back and does not consume the key. Concurrent first requests are serialized using a PostgreSQL transaction advisory lock; the successful database mutation and replay record commit together. JSON key order does not change the fingerprint. Browser CORS permits the request header and exposes the replay header.

Supported operations:

- Create/update tournament; close registration; start tournament.
- Create team; replace roster; invite member; answer invitation.
- Generate matches; create a manual match.
- Create/verify legacy tournament-level results; create/accept host result proposals.
- Submit winners; create announcement; submit review; self-check-in.

The header is optional for backward compatibility. Provider payment/refund, binary upload and Firebase dispute-provisioning calls are **not** covered by this database-only replay mechanism. They retain their existing reconciliation/error behavior. Captain result submissions can provision a dispute and likewise retain their existing amendment/consensus contract; reload result-state after an uncertain response rather than promising universal replay support. Never reuse one key for a different user action. No automatic receipt expiry is configured, so old keys remain reserved.

## Deployment and verification

1. Apply `sql/20261030_community_api_idempotency.sql` before clients enable keyed writes. The migration is additive and repeatable.
2. Deploy the backend changes, including CORS updates. No provider secrets or new external services are needed.
3. Integrate the new player reads/CTAs and explicit attendance/payout policy. Keep the existing deadline/payment workers enabled.
4. Run regression tests. The PostgreSQL tests require **a disposable database** and create/drop a unique schema per test:

```bash
COMMUNITY_FLOW_TEST_DATABASE_URL=postgresql+psycopg://localhost/test_database \
python -m pytest tests/test_community_flow_pg.py \
  tests/test_community_esports_operations.py \
  tests/test_community_payment_security.py \
  tests/test_community_registration_refunds.py \
  tests/test_tournament_payment_refunds.py -q
```

The tests exercise real PostgreSQL writes, rollback, concurrent idempotency, JWT-protected HTTP routes, participant redaction, roster locks, publication rejection, proposal agreement, multi-team disputes/referee resolution and winner/payee validation. Provider/Firebase/Cloudinary integrations are not live-tested by this suite.

Local verification result: **50 tests passed** across the five suites above. Python compilation and `git diff --check` passed. Repository graph refresh was attempted but the `graphify` executable was unavailable. No production migration or deployment was performed.
