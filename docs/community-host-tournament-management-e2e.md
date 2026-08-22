# Community Host Tournament Management E2E

This is the frontend contract for the community host tournament-management experience. It covers the complete lifecycle from host verification through payout settlement.

Base URL: `https://hfg-user-onboard.onrender.com/api/v1/community`

All host and player calls require:

```http
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

Platform-admin calls require:

```http
X-Admin-Token: <COMMUNITY_ADMIN_TOKEN>
X-Admin-Id: <admin_user_id>
Content-Type: application/json
```

## Roles and Access

| Role | Capability |
| --- | --- |
| Public visitor | Discover public tournaments and public results. |
| Player | Register, cancel their own registration, submit results, and open disputes. |
| Community host | Create and edit only tournaments where `host_user_id` is their authenticated user ID; manage roster, check-ins, results, and winner submission. |
| Platform admin | Review host verification, disputes, and payout settlement. |

Use `GET /api/events/<tournament_id>` with the logged-in user's Bearer token before showing host controls. The response has `can_manage: true` only for the community tournament owner.

## Lifecycle

1. Host reads `/hosts/program`, submits verification, and waits for platform approval.
2. Host optionally creates a banner file asset, then creates a draft tournament.
3. Host edits the draft and sets `status: "published"` when ready. A scheduled cron call progresses the non-terminal time-based statuses: `published`, `registration_open`, `registration_closed`, and `live`.
4. Players register. Razorpay verification or a webhook confirms paid registrations; the host never approves provider payments.
5. Host publishes room details, runs check-in, and verifies submitted results.
6. Host submits winners once. The tournament becomes `completed` and payouts enter `pending_admin_approval`.
7. Platform admin reviews disputes and approves/settles payouts.

The esports operations extension also supports team rosters, consent-based roster
invitations, seeding, generated brackets, captain result agreement, targeted
announcements, and a host control room. Existing solo registration APIs remain
compatible.

## 1. Host Onboarding

### Read Host Program

`GET /hosts/program`

No auth. Use this to show the monthly verification fee, included tournament allowance, Hash platform fee, host tiers, and organizer commission rates.

### Submit or Resubmit Verification

`POST /hosts/verification`

```json
{
  "name": "Aman Sharma",
  "email": "aman@example.com",
  "phone": "9876543210",
  "upi_id": "aman@upi",
  "address": "Full postal address",
  "government_id_asset_id": "uuid-or-null",
  "government_id": "optional-masked-reference"
}
```

### Read My Verification State

`GET /hosts/me/verification`

Check `verification_status` before allowing a paid tournament. Paid tournament creation requires `verified`; free tournaments are allowed for non-suspended hosts.

## 2. Create and Edit a Tournament

### Create a Draft

`POST /tournaments`

```json
{
  "title": "BGMI Friday Cup",
  "description": "Community solo tournament",
  "game": "BGMI",
  "tournament_type": "single_elimination",
  "team_mode": "solo",
  "entry_fee": 50,
  "currency": "INR",
  "max_players": 64,
  "registration_start_at": "2026-07-21T08:00:00+00:00",
  "registration_end_at": "2026-07-24T08:00:00+00:00",
  "tournament_start_at": "2026-07-25T10:00:00+00:00",
  "tournament_end_at": "2026-07-25T14:00:00+00:00",
  "rules": "No emulators",
  "prize_distribution": [{"rank": 1, "percent": 70}, {"rank": 2, "percent": 30}],
  "visibility": true,
  "status": "draft"
}
```

Additional esports configuration fields:

```json
{
  "game_mode": "5v5",
  "platform": "pc",
  "organization_name": "Hash Community",
  "team_size": 5,
  "substitute_limit": 2,
  "minimum_age": 16,
  "region": "India",
  "registration_policy": "manual_approval",
  "is_private": false,
  "invite_code": null,
  "min_entries": 8,
  "roster_lock_at": "2026-07-25T08:00:00Z",
  "check_in_start_at": "2026-07-25T09:00:00Z",
  "check_in_end_at": "2026-07-25T09:45:00Z",
  "match_duration_minutes": 45,
  "break_duration_minutes": 15,
  "max_matches_per_team_per_day": 6,
  "result_submission_window_minutes": 15,
  "dispute_window_minutes": 30,
  "schedule_config": {"concurrent_matches": 2},
  "rules_config": {"evidence_required": true}
}
```

Allowed automatic formats are `single_elimination`, `round_robin`, and `league`.
Other stored format values require manually managed matches until their dedicated
generator is enabled.

The response is the managed tournament object, including calculated `total_collection`, `organizer_commission_amount`, `prize_pool`, and the commission rate snapshotted from the host tier.

New tournaments also snapshot the configured Hash `platform_fee_rate`.
`prize_pool = total_collection - platform_fee_amount - organizer_commission_amount`.
Clients cannot supply either fee rate.

### Upload/Register a File Asset

Upload the binary with the app's storage flow first, then register its public URL:

`POST /files`

```json
{
  "tournament_id": "tournament-uuid",
  "purpose": "banner",
  "file_url": "https://cdn.example.com/banner.png",
  "storage_key": "community/banner.png",
  "mime_type": "image/png",
  "file_size_bytes": 204800,
  "metadata": {}
}
```

Use the returned `id` as `banner_asset_id` in the next edit.
Unattached banner assets are allowed for the create wizard and are attached when
the tournament is created. Evidence assets require `tournament_id`, must be
created by the host or a confirmed participant, and can only be referenced by
their owner.

### Edit or Publish

`PATCH /tournaments/<tournament_id>`

Send only changed fields. Editable fields are:

- `title`, `description`, `banner_url`, `banner_asset_id`, `game`, `tournament_type`, `team_mode`
- `entry_fee`, `currency`, `max_players`, `visibility`
- `registration_start_at`, `registration_end_at`, `tournament_start_at`, `tournament_end_at`
- `rules`, `prize_distribution`, `discord_link`, `whatsapp_link`, `room_details`, `room_details_data`
- `status`: only `draft` or `published`

```json
{
  "banner_asset_id": "asset-uuid",
  "discord_link": "https://discord.gg/example",
  "room_details": "Room ID: 12345, password: 6789",
  "room_details_data": {
    "schema_version": 1,
    "join": {"method": "in_game", "lobby_id": "12345", "access_code": "6789", "server_region": "Mumbai"},
    "custom_fields": [{"label": "Map", "value": "Erangel"}]
  },
  "status": "published"
}
```

Rules:

- The host can edit only their own tournament.
- A terminal tournament (`completed` or `cancelled`) cannot be edited.
- `entry_fee` cannot change after any confirmed registration.
- `max_players` cannot be lower than confirmed registrations.
- Dates must remain ordered: registration start < registration end <= tournament start < tournament end.
- Setting room details makes them visible to the host and confirmed players only.
- Never set `status: "cancelled"` through PATCH. Use the cancellation endpoint so refunds are processed.

### Cancel Tournament

`POST /tournaments/<tournament_id>/cancel`

```json
{
  "reason": "Venue unavailable"
}
```

Confirmed paid registrations are marked refunded and notified. Completed tournaments cannot be cancelled.
Razorpay registrations use the same idempotent provider refund flow as player
cancellation. A tournament is not reported as successfully cancelled when a
provider refund request fails.

### Host Dashboard List and Detail

- `GET /me/tournaments?role=hosted`
- `GET /tournaments/<tournament_id>`

The authenticated detail response includes `room_details` for the host.

## 3. Participant and Check-in Management

### Player Registration

`POST /tournaments/<tournament_id>/registrations`

```json
{
  "payment_reference": "pay_xxx"
}
```

Free registrations are immediately `confirmed` with `payment_status: "not_required"`. A paid registration is always created as `pending_payment` with `payment_status: "unpaid"`, even when `payment_reference` is supplied. The reference queues a server-side retry; it is never proof of payment by itself.

After Razorpay success, call `POST /api/payments/verify` with `razorpay_payment_id`, `razorpay_order_id`, `razorpay_signature`, and the community `registration_id` (the legacy `team_id` alias is accepted). The backend verifies the signature, fetched payment/order, captured status, currency, and entry-fee amount before returning the persisted `confirmed`/`paid` registration. Retrying the same valid request is safe.

For Razorpay deployments, set `PAYMENT_PROVIDER=razorpay`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, and `COMMUNITY_PAYMENT_CRON_TOKEN` on `hfg-user-onboard`, then configure Razorpay to send `payment.captured`, `payment.failed`, and `order.paid` webhooks to `POST /api/payments/webhook`. The booking service and `hfg-user-onboard` must use the same Razorpay account and mode. Without a verified callback, a paid registration correctly remains `pending_payment`/`unpaid` because the backend has no trusted proof of payment.

### Host Roster

`GET /tournaments/<tournament_id>/registrations?status=pending_payment&page=1&per_page=50`

Host-only. `status` is optional: `pending_payment`, `confirmed`, `cancelled`, or `refunded`.

Each item includes the registration fields plus a display-safe gamer object:

```json
{
  "id": "registration-uuid",
  "user_id": 2482,
  "status": "confirmed",
  "payment_status": "paid",
  "checked_in_at": null,
  "gamer": {
    "id": 2482,
    "display_name": "Player One",
    "game_username": "PlayerOne",
    "avatar_url": "https://..."
  }
}
```

## 3A. Esports Teams and Rosters

### Create Team for a Registration

`POST /tournaments/<tournament_id>/teams`

```json
{
  "name": "Team Phoenix",
  "members": [
    {"user_id": 2482, "game_id": "Phoenix#001", "role": "captain"},
    {"user_id": 2501, "game_id": "Hydra#002", "role": "player"},
    {"user_id": 2502, "game_id": "Nova#003", "role": "substitute"}
  ]
}
```

The caller must own an active registration. Non-captain members start as
`invited`; adding a user ID does not enroll that user without consent.

### Invite One Member

To invite a friend without replacing the full roster, the captain calls:

`POST /tournaments/<tournament_id>/teams/<team_id>/members`

```json
{"user_id": 2502, "game_id": "Nova#003", "role": "player"}
```

The captain counts as one active player. Therefore, a duo (`team_size: 2`) can
invite one `player`; a four-player squad can invite three. `substitute_limit`
adds only substitute slots. A tournament configured with `team_size: 1` has no
additional active-player slot.

### Accept or Decline Roster Invitation

`POST /tournaments/<tournament_id>/teams/<team_id>/invitation`

```json
{"action": "accept"}
```

Allowed actions are `accept` and `decline`.

This endpoint is for the invited user to respond. It is not the captain's
add-friend endpoint.

### Replace Roster

`PUT /tournaments/<tournament_id>/teams/<team_id>/roster`

Only the captain can replace the roster, and only before roster lock. Any roster
change returns the team to pending until all members accept.

### Team Lists and Host Actions

- Authenticated: `GET /tournaments/<tournament_id>/teams`
- Public, member-redacted: `GET /tournaments/public/<tournament_id>/teams`
- Host action: `PATCH /tournaments/<tournament_id>/teams/<team_id>`

Host actions are `approve`, `reject`, `request_information`, `lock_roster`,
`check_in`, `undo_check_in`, `seed`, `warn`, `disqualify`, and `refund`.
Reason-bearing actions are audited. Approval requires confirmed payment,
the configured active-player count, and accepted invitations from every roster
member.

## 3B. Match Operations

### Generate Schedule and Bracket

`POST /tournaments/<tournament_id>/matches/generate`

Generation is one-time and host-only. Single elimination uses seeded,
power-of-two brackets with byes and winner advancement. Round robin and league
generate every pair. Scheduling uses `match_duration_minutes`,
`break_duration_minutes`, and `schedule_config.concurrent_matches`. Generation
automatically checks in every approved bracket entrant that is not already
checked in, including the matching captain registration.

### Read Matches

- Public/redacted: `GET /tournaments/<tournament_id>/matches`
- Host or active participant, including lobby details:
  `GET /tournaments/<tournament_id>/matches/private`
- Public standings: `GET /tournaments/<tournament_id>/leaderboard`

Public match payloads never include lobby access credentials.

### Operate a Match

For formats without an automatic generator, hosts can create scheduled matches
with `POST /tournaments/<tournament_id>/matches`. Supply `team_a_id` and
`team_b_id` for head-to-head play, or `participant_team_ids` for a multi-team
battle-royale round.

`PATCH /tournaments/<tournament_id>/matches/<match_id>`

Host actions are `start`, `reschedule`, `set_lobby`, `record_standings`,
`restart`, and `cancel`. `record_standings` accepts placement, kills, penalty
points, and optional total points for every multi-team participant; it feeds
the cumulative leaderboard. Restart and cancellation require a reason and
create audit entries. Host result overrides must use result proposals; the
legacy `override_result` action is rejected to prevent bypassing captain review.

### Host Result Proposal and 15-Minute Review

### Results Tab Overview

Use this host-only endpoint to populate the tournament-management Results tab:

`GET /tournaments/<tournament_id>/results/overview?page=1&per_page=25`

It returns summary counters, every requested match's final scores, host proposals,
captain submissions, open disputes, Cloudinary evidence metadata/URLs, and action
flags. This is the operational endpoint for the Results tab; the older
`GET /tournaments/<tournament_id>/results` endpoint remains available for legacy
tournament-level winner submissions.

`POST /tournaments/<tournament_id>/matches/<match_id>/result-proposals`

```json
{
  "winner_team_id": "uuid",
  "team_a_score": 2,
  "team_b_score": 1,
  "evidence_asset_ids": ["asset-uuid"],
  "evidence_urls": ["https://firebasestorage.googleapis.com/.../scoreboard.png"],
  "ocr_data": {
    "text": "Team Alpha 2 Team Bravo 1",
    "detected_teams": ["Team Alpha", "Team Bravo"],
    "scores": {"team_a": 2, "team_b": 1},
    "confidence": 0.94,
    "submitter_type": "host"
  }
}
```

Only the tournament host can create a proposal, and it is valid for 15 minutes.
Supply at least one uploaded Hash evidence asset or an absolute HTTPS screenshot
URL. The backend stores the URLs and OCR/consensus metadata but does not grant
Firestore access; Firebase Security Rules must still enforce authenticated,
authorized writes.

Each match team's accepted captain can respond:

- `POST /tournaments/<tournament_id>/matches/<match_id>/result-proposals/<proposal_id>/accept`
- `POST /tournaments/<tournament_id>/matches/<match_id>/result-proposals/<proposal_id>/dispute`

Before rendering a review action, load the authenticated match state from:

`GET /tournaments/<tournament_id>/matches/<match_id>/result-state`

It returns proposal evidence, captain submissions, any active dispute, the server
time, and the viewer's `can_accept_pending_proposal` / `can_dispute_pending_proposal`
permissions. Only the host and assigned accepted/verified match members can read it.

Both captains accepting finalizes the match immediately and advances the winner.
A dispute marks the proposal disputed and opens the normal organizer/admin
dispute record. If nobody disputes, the deadline processor finalizes the pending
proposal once its 15-minute server deadline has elapsed.

An open match dispute blocks further host proposals. A platform referee resolves
the match through `resolve-result`; changing a dispute to `closed` alone is not a
result decision and is intentionally rejected.

### Admin Referee Resolution

For a disputed or otherwise unresolved match, a platform administrator can make
the final referee decision:

`POST /admin/tournaments/<tournament_id>/matches/<match_id>/resolve-result`

Send `X-Admin-Token`, `X-Admin-Id`, a non-empty `reason`, `winner_team_id`, and
both non-negative scores. This closes open match disputes, marks pending
proposals/submissions as admin-overridden, writes an audit record, notifies the
host, and advances the bracket. It cannot alter a completed match; a completed
match requires a separate controlled restart workflow.

### Dispute Chat Provisioning

When `COMMUNITY_DISPUTE_CHAT_ENABLED=true`, every newly opened dispute receives
a backend-created Firestore room. The tournament host manages the room by
default. `COMMUNITY_DISPUTE_ADMIN_USER_IDS=123,456` is optional and adds Hash
support staff only for escalated disputes. The dispute response exposes
`chat_room_id` and `chat_room_status: ready`; the backend owns the room roster
and initial system message. Clients obtain a Firebase custom token from
`POST /chat/firebase-token` before opening the returned room.

### Temporary Result Evidence (Cloudinary)

1. Request a signed image upload using
   `POST /tournaments/<tournament_id>/evidence/upload-signature` with
   `{ "purpose": "result_evidence" }` or `{ "purpose": "dispute_evidence" }`.
2. Upload the screenshot directly to the returned `upload_url`, sending the
   returned `api_key`, `timestamp`, `signature`, `folder`, `public_id`, and
   `allowed_formats` fields.
3. Register Cloudinary's `secure_url` using `POST /files`, with the returned
   `storage_key`, purpose, tournament ID, and upload metadata. Use the returned
   asset ID in result proposals, captain submissions, or disputes.

Only the host or a confirmed participant can request a signature. Cloudinary
evidence is retained until the tournament completes, then deleted by the evidence
cleanup cron after `COMMUNITY_EVIDENCE_RETENTION_DAYS` (default: seven days).
The database retains a deletion tombstone for audit purposes.

Schedule:

`POST /internal/evidence/purge-expired`

Use `X-Community-Payment-Cron-Token` and optional `{ "limit": 50 }`.

### Captain Result Agreement

`POST /tournaments/<tournament_id>/matches/<match_id>/result-submissions`

```json
{
  "winner_team_id": "uuid",
  "team_a_score": 2,
  "team_b_score": 1,
  "evidence_asset_ids": ["asset-uuid"],
  "notes": "Final scoreboard"
}
```

Only each match team's accepted captain can submit once. Matching winner and
score submissions automatically complete the match and advance the winner.
Conflicting submissions mark the match disputed and create a structured
platform-admin dispute.

The first captain may amend their own submission only while the match is still
awaiting the other captain and before its original response deadline. An
amendment does not extend that deadline. Once the other captain responds, both
submissions are immutable and either finalize or create a dispute.

Schedule `POST /internal/operations/process-deadlines` every 1-2 minutes with
`X-Community-Payment-Cron-Token`. It finalizes undisputed expired result
proposals, escalates one-sided submissions after
`result_submission_window_minutes`, notifies the host, and progresses scheduled
tournament statuses through registration open, registration closed, and live.

## 3C. Control Room and Communication

- Host dashboard: `GET /hosts/me/dashboard`
- Tournament control room: `GET /tournaments/<tournament_id>/control-room`
- Audit trail: `GET /tournaments/<tournament_id>/audit-log`
- Publish: `POST /tournaments/<tournament_id>/announcements`
- Participant inbox: `GET /tournaments/<tournament_id>/announcements`

Announcement audiences are `all_participants`, `captains`, `unchecked_in`, and
`specific_teams`. The inbox enforces audience membership server-side.

### Rules and Publish Readiness

- `GET /rules/template?game=Valorant`
- `GET /tournaments/<tournament_id>/readiness`

Templates include game defaults and mandatory Hash safety rules. Readiness
returns `ready_to_publish`, hard blockers, and operational warnings without
silently changing tournament state.

### Host Registration Actions

`PATCH /tournaments/<tournament_id>/registrations/<registration_id>`

```json
{"action": "check_in"}
```

```json
{"action": "undo_check_in"}
```

```json
{"action": "remove_participant"}
```

Action rules:

- Provider payment confirmation and failure are deliberately unavailable to hosts. Use `/api/payments/verify`, Razorpay webhooks, or the retry queue.
- `check_in` and `undo_check_in`: only confirmed registrations after registration is closed or while the tournament is live.
- `remove_participant`: before the tournament starts only; paid confirmed registrations are refunded.

### Payment Retry Queue

`GET /admin/payments/pending?status=pending&page=1&per_page=50` lists durable community payment settlement jobs for platform admins (`X-Admin-Token`).

`POST /internal/payments/process-pending` runs the cron batch and requires `X-Community-Payment-Cron-Token`. Optional body: `{ "limit": 50 }`. Schedule it every 1-2 minutes. The worker fetches each Razorpay payment, confirms that it is captured and matches the tournament amount/currency, then settles the same registration transaction used by `/api/payments/verify`.

### Captured Payment Recovery and Duplicate Refunds

A player can safely retry or reopen a tournament after an interrupted payment.
The backend keeps the original pending registration and reconciles a later
captured Razorpay webhook against the registration's current or historical
payment-attempt order. A verified first payment confirms that same registration;
it does not create a second slot or require the player to join again.

If Razorpay confirms more than one payment for the same registration, the first
captured payment remains the tournament entry payment. Every additional captured
payment creates a durable duplicate-payment recovery record and is automatically
refunded by the existing `POST /internal/payments/process-pending` cron. It never
changes registration state, player counts, collection totals, or prize pool.

Super admins can monitor these records through:

`GET /admin/payments/duplicate-recoveries?status=pending_refund&page=1&per_page=50`

The response includes `admin_summary`, payment/refund IDs, attempts, retry time,
and provider error text. Status values are `pending_refund`, `processing`,
`refund_pending`, `refunded`, and `failed`. `failed` means the automatic Razorpay
refund needs super-admin follow-up; it is never silently discarded.

## 4. Results and Disputes

### Submit a Result

`POST /tournaments/<tournament_id>/results`

The host or a confirmed player can submit a result.

```json
{
  "winner_user_id": 2482,
  "rank": 1,
  "score": "18 kills",
  "evidence_asset_ids": ["asset-uuid"],
  "stream_url": "https://...",
  "notes": "Final match"
}
```

### Host Result Inbox

`GET /tournaments/<tournament_id>/results?status=submitted&page=1&per_page=50`

Host-only. Each item includes `winner` and `submitted_by` gamer summaries.

### Verify or Reject Result

`PATCH /tournaments/<tournament_id>/results/<result_id>`

```json
{"status": "verified"}
```

Allowed status values: `verified`, `rejected`, `admin_overridden`.

### Player Opens a Dispute

`POST /tournaments/<tournament_id>/disputes`

```json
{
  "result_id": "result-uuid",
  "reason": "Incorrect placement",
  "description": "The submitted screenshot has the wrong score.",
  "evidence_asset_ids": ["asset-uuid"]
}
```

### Host Dispute Inbox

`GET /tournaments/<tournament_id>/disputes?status=open&page=1&per_page=50`

Host-only, read-only. The host can see the dispute and its reporter but cannot adjudicate it. Platform admin owns the final decision.

## 5. Winners and Payouts

### Submit Winners

`POST /tournaments/<tournament_id>/winners`

```json
{
  "winners": [
    {"user_id": 2482, "rank": 1, "amount": 322.0},
    {"user_id": 2501, "rank": 2, "amount": 138.0}
  ]
}
```

This is host-only and one-time, available once the tournament is live or has ended. Winners must be confirmed tournament participants, ranks and users must be unique, and the total cannot exceed the calculated `prize_pool`. If `amount` is `0`, the backend calculates it from `prize_distribution`. Winner submission changes the tournament status to `completed` and creates payouts with `pending_admin_approval`.

Winner submission is blocked while any dispute is `open` or `under_review`.
It also creates a separate `organizer_commission` payout for the snapshotted
organizer commission. Platform admin must approve and settle it exactly like a
player prize.

### Host Payout Tracker

`GET /tournaments/<tournament_id>/payouts?status=pending_admin_approval&page=1&per_page=50`

Host-only, read-only. Use it to show winner payout progress. Each payout includes its gamer summary.

## 5A. Organizer Reputation

After completion, a confirmed participant can submit one review:

`POST /tournaments/<tournament_id>/reviews`

```json
{
  "management_rating": 5,
  "communication_rating": 4,
  "fairness_rating": 5,
  "scheduling_rating": 4,
  "dispute_handling_rating": 5,
  "comment": "Well managed."
}
```

Ratings must be integers from 1 to 5. Public organizer trust data is available at:

`GET /hosts/<host_user_id>/profile`

It includes verified status, hosted/completed/cancelled counts, calculated
completion rate, participant rating, review count, and paid prize history.

## 6. Platform Admin Operations

These calls belong to the internal admin application, not the host app.

### Review Host Verification

`GET /admin/hosts/verifications?status=pending&page=1&per_page=50`

`PATCH /admin/hosts/<verification_id>/verification`

```json
{
  "status": "verified",
  "host_tier": "silver",
  "average_rating": 4.6,
  "dispute_rate": 1.2,
  "completion_rate": 98.0,
  "on_time_payout_rate": 100.0,
  "policy_violation_count": 0
}
```

### Dispute Queue and Review

- `GET /admin/tournaments/<tournament_id>/disputes?status=open&page=1&per_page=50`
- `PATCH /admin/disputes/<dispute_id>`

```json
{
  "status": "approved",
  "admin_comment": "Verified against supplied evidence."
}
```

Allowed dispute updates: `under_review`, `approved`, `rejected`, `closed`.

### Payout Queue and Settlement

- `GET /admin/tournaments/<tournament_id>/payouts?status=pending_admin_approval&page=1&per_page=50`
- `PATCH /admin/tournaments/<tournament_id>/payouts/<payout_id>`

Approve first:

```json
{"status": "approved"}
```

Then mark settled:

```json
{"status": "paid"}
```

Other valid decisions are `failed` and `cancelled`. A payout must be `approved` before it can become `paid`; paid and cancelled payouts are immutable.

## Error Handling

All errors return:

```json
{
  "error": "validation_error",
  "message": "Human-readable explanation"
}
```

- `400 validation_error`: invalid fields, action, status, or state input.
- `403 forbidden`: caller is not the host of the tournament, or platform-admin token is invalid.
- `409 conflict`: lifecycle prevents the action, such as editing terminal tournaments, confirming a full event, duplicate winner submission, or changing paid/cancelled payouts.
- `500`: unexpected backend/database failure. Show a retry state; do not optimistically assume completion.

## Frontend Rules

- Use `can_manage` from `/api/events/public` or `/api/events/<id>` only as a UI switch. Every management API enforces ownership again.
- Always refetch the affected roster, result, or payout list after a mutation; counts and payout values are server-calculated.
- Hide financial-admin controls from hosts. Hosts submit winners; platform admin approves and settles payouts.
- Render `room_details` only from authenticated tournament detail responses. Do not cache or show it to public users.
- Do not expose host verification PII (email, phone, address, UPI, government ID) in public tournament screens.
