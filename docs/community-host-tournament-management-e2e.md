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
3. Host edits the draft and sets `status: "published"` when ready. Time-based statuses then progress automatically.
4. Players register. Razorpay verification or a webhook confirms paid registrations; the host never approves provider payments.
5. Host publishes room details, runs check-in, and verifies submitted results.
6. Host submits winners once. The tournament becomes `completed` and payouts enter `pending_admin_approval`.
7. Platform admin reviews disputes and approves/settles payouts.

## 1. Host Onboarding

### Read Host Program

`GET /hosts/program`

No auth. Use this to show the monthly verification fee, included tournament allowance, host tiers, and organizer commission rates.

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

The response is the managed tournament object, including calculated `total_collection`, `organizer_commission_amount`, `prize_pool`, and the commission rate snapshotted from the host tier.

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

### Host Payout Tracker

`GET /tournaments/<tournament_id>/payouts?status=pending_admin_approval&page=1&per_page=50`

Host-only, read-only. Use it to show winner payout progress. Each payout includes its gamer summary.

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
