# Community Tournament APIs (Frontend Handoff)

This document covers the community tournament module in `hfg-user-onboard` for app/frontend development.

Base URL examples:
- Production: `https://hfg-user-onboard.onrender.com/api/v1/community`
- Local: `http://localhost:5000/api/v1/community`

Authentication:
- Public discovery endpoints do not require auth.
- User actions require `Authorization: Bearer <JWT_TOKEN>`.
- Admin endpoints require `X-Admin-Token: <COMMUNITY_ADMIN_TOKEN>` and optional `X-Admin-Id: <admin_user_id>`.

Common error shape:
```json
{
  "error": "validation_error",
  "message": "title must be 3-200 characters"
}
```

Common error codes:
- `400 validation_error`: invalid or missing input.
- `403 forbidden`: missing permission, unverified paid host, or invalid admin token.
- `409 conflict`: state conflict such as duplicate registration, full tournament, or terminal tournament edit.
- `500 database_error` / `internal_error`: backend failure.

## Frontend Feature Scope

Build these user-facing areas:
- Community tournament discovery list with filters.
- Tournament detail page.
- My tournaments, split by joined and hosted.
- Host verification form and status page.
- Create/edit/cancel tournament flow for hosts.
- Register/cancel registration flow for players.
- Result submission and verification flow.
- Winner submission flow for hosts.
- Dispute submission flow.
- File asset registration helper after upload.
- Host performance levels and monthly verification fee display.

## Status Values

Host verification:
- `pending`
- `verified`
- `rejected`
- `suspended`

Host tiers:
- `bronze`: 8% organizer commission
- `silver`: 10% organizer commission
- `gold`: 12% organizer commission
- `platinum`: 15% organizer commission

Tournament:
- `draft`
- `published`
- `registration_open`
- `registration_closed`
- `live`
- `completed`
- `cancelled`

Registration:
- `pending_payment`
- `confirmed`
- `cancelled`
- `refunded`

Result:
- `submitted`
- `verified`
- `rejected`
- `admin_overridden`

Dispute:
- `open`
- `under_review`
- `approved`
- `rejected`
- `closed`

Payout:
- `pending_admin_approval`
- `approved`
- `paid`
- `failed`
- `cancelled`

## Data Models

### Tournament
```json
{
  "id": "uuid",
  "host_user_id": 128,
  "title": "BGMI Friday Cup",
  "description": "Squad tournament",
  "banner_asset_id": "uuid-or-null",
  "banner_url": "https://...",
  "game": "BGMI",
  "tournament_type": "single_elimination",
  "team_mode": "solo",
  "entry_fee": 50.0,
  "currency": "INR",
  "max_players": 64,
  "registration_start_at": "2026-07-14T10:00:00+00:00",
  "registration_end_at": "2026-07-20T10:00:00+00:00",
  "tournament_start_at": "2026-07-21T10:00:00+00:00",
  "tournament_end_at": null,
  "rules": "No emulators",
  "prize_distribution": [{"rank": 1, "percent": 70}, {"rank": 2, "percent": 30}],
  "discord_link": "https://discord.gg/...",
  "whatsapp_link": "https://chat.whatsapp.com/...",
  "room_details_published_at": null,
  "visibility": true,
  "is_featured": false,
  "status": "registration_open",
  "total_collection": 500.0,
  "platform_fee_amount": 40.0,
  "host_tier": "bronze",
  "organizer_commission_rate": 8.0,
  "organizer_commission_amount": 40.0,
  "prize_pool": 460.0,
  "registered_players_count": 10,
  "created_at": "2026-07-14T10:00:00+00:00",
  "updated_at": "2026-07-14T10:00:00+00:00"
}
```

`room_details` and `room_details_data` are returned only when the requester is the host or has a confirmed registration. Public detail/list responses do not include either field.

`room_details_data` is a game-neutral object. Use the shared keys when present, but preserve and render unknown keys rather than assuming a particular game:

```json
{
  "schema_version": 1,
  "join": {
    "method": "in_game",
    "lobby_id": "12345",
    "access_code": "6789",
    "join_url": null,
    "server_region": "Mumbai",
    "instructions": "Join 10 minutes before start."
  },
  "schedule": {
    "opens_at": "2026-07-25T09:50:00Z",
    "check_in_at": "2026-07-25T09:55:00Z"
  },
  "contacts": [{"channel": "Discord", "value": "https://discord.gg/example"}],
  "custom_fields": [{"label": "Tournament code", "value": "ABCD"}]
}
```

### Registration
```json
{
  "id": "uuid",
  "tournament_id": "uuid",
  "user_id": 128,
  "status": "pending_payment",
  "payment_status": "unpaid",
  "amount_paid": 0,
  "payment_reference": "pay_123",
  "payment_provider": "razorpay",
  "razorpay_payment_id": "pay_123",
  "razorpay_order_id": null,
  "payment_verified_at": null,
  "confirmed_at": null,
  "paid_at": null,
  "checked_in_at": null,
  "cancelled_at": null,
  "created_at": "2026-07-14T10:00:00+00:00",
  "updated_at": "2026-07-14T10:00:00+00:00"
}
```

### Host Verification
```json
{
  "id": "uuid",
  "user_id": 128,
  "name": "Host Name",
  "email": "host@example.com",
  "phone": "9876543210",
  "government_id_asset_id": "uuid-or-null",
  "government_id_reference": "masked/reference",
  "upi_id": "host@upi",
  "address": "Full address",
  "verification_status": "pending",
  "host_tier": "bronze",
  "average_rating": 0.0,
  "dispute_rate": 0.0,
  "completion_rate": 0.0,
  "on_time_payout_rate": 0.0,
  "policy_violation_count": 0,
  "rejection_reason": null,
  "reviewed_by_admin_id": null,
  "reviewed_at": null,
  "created_at": "2026-07-14T10:00:00+00:00",
  "updated_at": "2026-07-14T10:00:00+00:00"
}
```

### File Asset
```json
{
  "id": "uuid",
  "owner_user_id": 128,
  "tournament_id": "uuid-or-null",
  "purpose": "banner",
  "file_url": "https://...",
  "storage_key": "uploads/community/banner.png",
  "mime_type": "image/png",
  "file_size_bytes": 204800,
  "checksum": null,
  "metadata": {},
  "created_at": "2026-07-14T10:00:00+00:00"
}
```

## Public APIs

### Health
- **Method**: `GET`
- **Path**: `/health`

Response:
```json
{
  "ok": true,
  "module": "community_tournaments",
  "version": "v1"
}
```

### Host Program Config
- **Method**: `GET`
- **Path**: `/hosts/program`
- **Auth**: Not required.

Use this to render host onboarding pricing and tier benefits. The verification fee is controlled by Docker/environment variable `COMMUNITY_HOST_VERIFICATION_MONTHLY_FEE`; default is `199`. Included tournaments per week is controlled by `COMMUNITY_HOST_INCLUDED_TOURNAMENTS_PER_WEEK`; default is `3`.

Response:
```json
{
  "verification_fee": {
    "amount": 199.0,
    "currency": "INR",
    "billing_period": "monthly",
    "included_tournaments_per_week": 3
  },
  "performance_levels": {
    "bronze": {
      "label": "Bronze Host",
      "organizer_commission_rate": 8.0,
      "requirements": ["Verified host account"]
    },
    "silver": {
      "label": "Silver Host",
      "organizer_commission_rate": 10.0,
      "requirements": ["High ratings", "Low dispute rates", "Successful tournament completion"]
    },
    "gold": {
      "label": "Gold Host",
      "organizer_commission_rate": 12.0,
      "requirements": ["High ratings", "Low dispute rates", "Successful tournament completion", "On-time payouts"]
    },
    "platinum": {
      "label": "Platinum Host",
      "organizer_commission_rate": 15.0,
      "requirements": ["High ratings", "Low dispute rates", "Successful tournament completion", "On-time payouts", "No policy violations"]
    }
  }
}
```

### Shared Public Events Feed
- **Method**: `GET`
- **Path**: `/api/events/public`
- **Auth**: Not required.

This existing app-level feed now returns both cafe dashboard events and community tournaments in one list. Use `source` to distinguish records:
- `source = "cafe"`: created from cafe/dashboard events, has `vendor_id`.
- `source = "community"`: created from community tournament flow, has `host_user_id` and `vendor_id = null`.

Notes:
- `vendor_id` query param keeps the old cafe-only behavior and excludes community tournaments.
- `flag=live|upcoming|completed` applies to both sources.
- Shared fields are normalized as `registration_fee`, `format`, `prize_pool`, `banner_image_url`, `start_at`, and `end_at`.
- `GET /api/events/<id>` also falls back to community tournament detail when the id is not a cafe event.

### List Tournaments
- **Method**: `GET`
- **Path**: `/tournaments`
- **Auth**: Not required.

Query params:
- `page`: default `1`.
- `per_page` or `limit`: default `20`, max `100`.
- `view`: `featured`, `free`, `paid`, `upcoming`, `popular`, or `admin`.
- `game`: exact game filter, case-insensitive.
- `search`: searches title, description, and game.
- `sort`: `soonest`, `popular`, `newest`, `fee_low`.

Notes:
- Non-admin views only return visible tournaments in public statuses.
- `view=admin` only changes filtering behavior; this endpoint itself has no admin auth in the current backend.

Request:
```bash
curl --request GET \
  --url 'https://hfg-user-onboard.onrender.com/api/v1/community/tournaments?view=upcoming&game=BGMI&page=1&per_page=20'
```

Response:
```json
{
  "items": [],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 0,
    "pages": 0
  }
}
```

### Public Tournament Detail
- **Method**: `GET`
- **Path**: `/tournaments/public/<tournament_id>`
- **Auth**: Not required.

Use for anonymous detail pages. It returns the tournament model without `room_details`.

## User APIs

### Authenticated Tournament Detail
- **Method**: `GET`
- **Path**: `/tournaments/<tournament_id>`
- **Auth**: Required.

Use this when a logged-in user opens the detail page. If the user is the host or confirmed participant, response includes `room_details`.

### Submit Host Verification
- **Method**: `POST`
- **Path**: `/hosts/verification`
- **Auth**: Required.

Request body:
```json
{
  "name": "Host Name",
  "email": "host@example.com",
  "phone": "9876543210",
  "upi_id": "host@upi",
  "address": "Full address with city and state",
  "government_id": "optional-reference",
  "government_id_asset_id": "optional-file-asset-uuid"
}
```

Validation:
- `name` required, max 160 chars.
- `email` must be valid.
- `phone` must be 8-32 chars.
- `upi_id` must match UPI format like `name@bank`.
- `address` must be at least 10 chars.

### Get My Host Verification
- **Method**: `GET`
- **Path**: `/hosts/me/verification`
- **Auth**: Required.

Response is a host verification object or `null`.

Important UI rule:
- Paid tournament creation is allowed only when `verification_status` is `verified`.
- Free tournaments can be created without verified host status unless host status is `suspended`.
- Show host tier and commission benefits from `GET /hosts/program`; do not hardcode the monthly verification fee.

### Create Tournament
- **Method**: `POST`
- **Path**: `/tournaments`
- **Auth**: Required.

Request body:
```json
{
  "title": "BGMI Friday Cup",
  "description": "Squad tournament",
  "banner_url": "https://...",
  "banner_asset_id": "optional-uuid",
  "game": "BGMI",
  "tournament_type": "single_elimination",
  "team_mode": "solo",
  "entry_fee": 50,
  "currency": "INR",
  "max_players": 64,
  "registration_start_at": "2026-07-14T10:00:00Z",
  "registration_end_at": "2026-07-20T10:00:00Z",
  "tournament_start_at": "2026-07-21T10:00:00Z",
  "tournament_end_at": "2026-07-21T14:00:00Z",
  "rules": "No emulators",
  "prize_distribution": [{"rank": 1, "percent": 70}, {"rank": 2, "percent": 30}],
  "discord_link": "https://discord.gg/...",
  "whatsapp_link": "https://chat.whatsapp.com/...",
  "visibility": true,
  "status": "published"
}
```

Validation:
- `title`: 3-200 chars.
- `game`: required.
- `max_players`: 1-10000.
- `registration_end_at` must be after `registration_start_at`.
- `tournament_start_at` must be after or equal to `registration_end_at`.
- `tournament_end_at`, if provided, must be after `tournament_start_at`.
- New tournament `status` can only be `draft` or `published`.

Financial behavior:
- Backend snapshots the host's current `host_tier` and `organizer_commission_rate` when the tournament is created.
- Organizer commission is deducted from total collection before prize calculation.
- `prize_pool = total_collection - organizer_commission_amount`.
- `platform_fee_amount` currently mirrors `organizer_commission_amount` for backward compatibility with existing clients.
- `total_collection`, `organizer_commission_amount`, `platform_fee_amount`, and `prize_pool` are recalculated by backend.

### Update Tournament
- **Method**: `PATCH`
- **Path**: `/tournaments/<tournament_id>`
- **Auth**: Required host.

Editable fields:
- `title`
- `description`
- `banner_url`
- `game`
- `tournament_type`
- `team_mode`
- `rules`
- `prize_distribution`
- `discord_link`
- `whatsapp_link`
- `visibility`
- `room_details`
- `status`
- `max_players`
- `registration_start_at`
- `registration_end_at`
- `tournament_start_at`
- `tournament_end_at`
- `entry_fee`

Important rules:
- `entry_fee` cannot be changed after registrations exist.
- `max_players` cannot be lower than current registrations.
- Completed or cancelled tournaments cannot be edited.
- When `room_details` is first set, backend sets `room_details_published_at`.

### Cancel Tournament
- **Method**: `POST`
- **Path**: `/tournaments/<tournament_id>/cancel`
- **Auth**: Required host.

Request body:
```json
{
  "reason": "Host unavailable"
}
```

Behavior:
- Status becomes `cancelled`.
- Confirmed paid registrations are marked `refunded`.
- Backend creates refund wallet transactions.
- Completed tournaments cannot be cancelled.

### My Tournaments
- **Method**: `GET`
- **Path**: `/me/tournaments?role=joined`
- **Auth**: Required.

Query:
- `role=joined`: tournaments where the user registered. Each item includes `registration`.
- `role=hosted`: tournaments hosted by the user. Items include `room_details`.

Response:
```json
{
  "items": []
}
```

### Register For Tournament
- **Method**: `POST`
- **Path**: `/tournaments/<tournament_id>/registrations`
- **Auth**: Required.

Request body:
```json
{
  "payment_reference": "pay_123"
}
```

Behavior:
- Free tournament: registration becomes `confirmed`, payment status `not_required`, amount `0`.
- Paid tournament: registration always becomes `pending_payment` with payment status `unpaid`; a payment reference only starts the backend retry queue.
- Host cannot register for their own tournament.
- Registration only works when tournament status is `registration_open`.

Frontend recommendation:
- For paid tournaments, create the registration with `payment_reference: pay_xxx`, then immediately call `/api/payments/verify` with the Razorpay order ID, payment ID, signature, and returned `registration_id`.
- Treat the persisted verification response as the source of truth. Until it returns `confirmed` and `paid`, show the payment-pending state and hide room details.

### Cancel My Registration
- **Method**: `DELETE`
- **Path**: `/tournaments/<tournament_id>/registrations/me`
- **Auth**: Required.

Behavior:
- Cannot cancel after tournament is `live` or `completed`.
- Paid confirmed registrations are moved to `refunded`.
- Registration count and prize pool are recalculated.

### Submit Match Result
- **Method**: `POST`
- **Path**: `/tournaments/<tournament_id>/results`
- **Auth**: Required host or confirmed participant.

Request body:
```json
{
  "winner_user_id": 128,
  "rank": 1,
  "score": "2-0",
  "evidence_asset_ids": ["uuid"],
  "stream_url": "https://...",
  "notes": "Final result"
}
```

Response is a result object with status `submitted`.

### Verify Match Result
- **Method**: `PATCH`
- **Path**: `/tournaments/<tournament_id>/results/<result_id>`
- **Auth**: Required host.

Request body:
```json
{
  "status": "verified"
}
```

Allowed status:
- `verified`
- `rejected`
- `admin_overridden`

### Submit Winners
- **Method**: `POST`
- **Path**: `/tournaments/<tournament_id>/winners`
- **Auth**: Required host.

Request body:
```json
{
  "winners": [
    {"user_id": 128, "rank": 1, "amount": 315},
    {"user_id": 129, "rank": 2, "amount": 135}
  ]
}
```

Notes:
- `winners` must be a non-empty list.
- If `amount` is `0`, backend tries to calculate amount from `prize_distribution[rank - 1].percent`.
- Winners can be submitted only once.
- Tournament status becomes `completed`.
- Response is `{ "items": [payouts...] }`.

### Create Dispute
- **Method**: `POST`
- **Path**: `/tournaments/<tournament_id>/disputes`
- **Auth**: Required.

Request body:
```json
{
  "result_id": "optional-result-uuid",
  "reason": "Wrong winner",
  "description": "The submitted screenshot does not match the match result.",
  "evidence_asset_ids": ["uuid"]
}
```

Validation:
- `reason` and `description` are required.

### Create File Asset
- **Method**: `POST`
- **Path**: `/files`
- **Auth**: Required.

Use after the frontend uploads a file to storage. This endpoint does not upload binary data; it stores file metadata and returns a reusable asset id.

Request body:
```json
{
  "purpose": "banner",
  "file_url": "https://...",
  "storage_key": "uploads/community/banner.png",
  "mime_type": "image/png",
  "file_size_bytes": 204800,
  "checksum": "optional",
  "tournament_id": "optional-tournament-uuid",
  "metadata": {
    "width": 1200,
    "height": 600
  }
}
```

Common purposes:
- `banner`
- `government_id`
- `result_evidence`
- `dispute_evidence`

## Admin APIs

These are included for internal/admin frontend planning.

### Review Host Verification
- **Method**: `PATCH`
- **Path**: `/admin/hosts/<verification_id>/verification`
- **Headers**: `X-Admin-Token`, optional `X-Admin-Id`.

Request body:
```json
{
  "status": "verified",
  "host_tier": "silver",
  "average_rating": 4.7,
  "dispute_rate": 1.5,
  "completion_rate": 98.0,
  "on_time_payout_rate": 99.0,
  "policy_violation_count": 0,
  "rejection_reason": null
}
```

Allowed status:
- `pending`
- `verified`
- `rejected`
- `suspended`

Optional performance fields:
- `host_tier`: `bronze`, `silver`, `gold`, or `platinum`.
- `average_rating`: 0-5.
- `dispute_rate`, `completion_rate`, `on_time_payout_rate`: 0-100 percentages.
- `policy_violation_count`: non-negative integer.

### Review Dispute
- **Method**: `PATCH`
- **Path**: `/admin/disputes/<dispute_id>`
- **Headers**: `X-Admin-Token`, optional `X-Admin-Id`.

Request body:
```json
{
  "status": "under_review",
  "admin_comment": "Checking evidence"
}
```

Allowed status:
- `under_review`
- `approved`
- `rejected`
- `closed`

## Suggested Screen Flows

### Discovery
1. Call `GET /tournaments` with `view=featured` for highlighted modules.
2. Call `GET /tournaments` with filters for browse/search.
3. Use `status`, `registration_end_at`, `registered_players_count`, and `max_players` to show CTA state.

CTA rules:
- `registration_open`: show Register.
- `registration_closed`: show Closed.
- `live`: show Live / View.
- `completed`: show Results if available in frontend state.
- `cancelled`: show Cancelled.

### Tournament Detail
1. If logged out, call public detail.
2. If logged in, call authenticated detail.
3. Show room details only when `room_details` exists in response.
4. Use `discord_link` and `whatsapp_link` as external links.

### Host Onboarding
1. Call `GET /hosts/program` to render monthly fee and tier benefits.
2. Call `GET /hosts/me/verification`.
3. If `null` or `rejected`, show host verification form.
4. If `pending`, show pending review state.
5. If `verified`, allow paid tournament creation and show current tier.
6. If `suspended`, block hosting actions.

### Tournament Creation
1. Upload banner externally.
2. Call `POST /files` with purpose `banner`.
3. Submit tournament with `banner_asset_id` and/or `banner_url`.
4. Use `draft` for saved drafts and `published` for live/public creation.

### Paid Registration
1. Complete the Razorpay checkout and retain `razorpay_order_id`, `razorpay_payment_id`, and `razorpay_signature`.
2. Call registration API with `payment_reference: razorpay_payment_id`.
3. Call `POST /api/payments/verify` with those three Razorpay fields plus `registration_id` and `tournament_id`.
4. Use the verification response; it must be `status: "confirmed"`, `payment_status: "paid"`, and `amount_paid` equal to the entry fee before showing confirmed-only content.

## Frontend Validation Checklist

- Send ISO datetimes. `Z` suffix is accepted.
- Keep all currency values numeric, not formatted strings.
- Use `entry_fee = 0` for free tournaments.
- Prevent host from registering for their own tournament in UI.
- Prevent paid tournament creation unless host status is `verified`.
- Prevent registration when `registered_players_count >= max_players`.
- Hide room details unless present in API response.
- Treat status values as backend-owned; backend recalculates by time windows.
- Use server response values for prize pool, organizer commission, and platform fee.

## Source Files

Controller:
- `controllers/community_tournament_controller.py`

Service:
- `services/community_tournament_service.py`

Models:
- `models/communityTournament.py`
- `models/communityTournamentOperations.py`

Migration:
- `sql/20260712_community_tournament_module.sql`
- `sql/20260717_community_host_performance_levels.sql`
