# Unified Public Tournament APIs

This document is for the app frontend team. These endpoints expose tournaments from both cafe dashboard events and community-host tournaments through the existing public event routes.

Base URL examples:
- Production: `https://hfg-user-onboard.onrender.com/api`
- Local: `http://localhost:5000/api`

Auth:
- Public feed, detail, leaderboard, provisional result, and gamer profile endpoints do not require auth.

## Sources

Every unified response includes `source`:
- `cafe`: tournament/event created from the cafe dashboard `events` flow.
- `community`: tournament created from the community host flow.

Event feed and detail items also include `can_manage`:
- Send the logged-in user's `Authorization: Bearer <token>` header when calling the public feed/detail endpoints.
- `can_manage = true` only when the caller is the `host_user_id` of a community tournament.
- `can_manage = false` for anonymous callers, other users, and cafe/dashboard events. Dashboard event ownership is currently vendor-based and is not linked to an app user ID.
- Treat this as a UI hint for the **Manage tournament** action. Management endpoints still enforce authorization server-side.

Use `source` to decide where to route user actions:
- `source = "cafe"`: use existing cafe event registration/team flows.
- `source = "community"`: use community registration/result/dispute flows under `/api/v1/community`.

Legacy compatibility:
- Existing app clients that still call `POST /api/events/<id>/teams` and then `POST /api/events/<id>/register` are bridged for community `team_mode = "solo"` tournaments. The backend creates or reuses the community registration and returns its UUID as a temporary `team_id` alias.
- Existing app clients using `GET /api/users/<user_id>/tournaments/joined` or `GET /api/users/<user_id>/teams` now receive community registrations in the legacy response shape as well. Check `source = "community"`; the temporary `team_id` is the community registration ID.
- `GET /api/events/<community-id>/teams/<registration-id>/members` also resolves that temporary ID and returns the registered gamer as the single legacy team member.
- New frontend work must use `POST /api/v1/community/tournaments/<id>/registrations` for community tournaments. Team routes remain the cafe contract and cannot support community team-mode tournaments.

## Public Feed

### List Tournaments
- **Method**: `GET`
- **Path**: `/events/public`

Query params:
- `limit`: default `30`, max `100`.
- `flag`: optional `live`, `upcoming`, or `completed`.
- `vendor_id`: optional cafe vendor filter. If present, only cafe events are returned.

Response item:
```json
{
  "id": "uuid",
  "source": "community",
  "vendor_id": null,
  "host_user_id": 2482,
  "can_manage": false,
  "title": "BGMI Friday Cup",
  "description": "Squad tournament",
  "start_at": "2026-07-21T10:00:00+00:00",
  "end_at": "2026-07-21T14:00:00+00:00",
  "registration_fee": 50.0,
  "currency": "INR",
  "game": "BGMI",
  "format": "single_elimination",
  "prize_pool": 460.0,
  "team_size": 1,
  "match_rules": "No emulators",
  "region": null,
  "server": null,
  "map_pool": [],
  "veto_mode": "none",
  "banner_image_url": "https://...",
  "flag": "upcoming"
}
```

Cafe events use the same shape with `source = "cafe"`, `vendor_id` populated, `host_user_id = null`, and `can_manage = false`.

## Gamer Profile

### Get Gamer Profile
- **Method**: `GET`
- **Path**: `/gamers/<user_id>/profile`

Use this on the tournament page's host/gamer section. For a community tournament, pass its `host_user_id` from the feed or detail response. Do not call this for cafe tournaments when `host_user_id` is `null`.

Response:
```json
{
  "id": 2482,
  "display_name": "Player One",
  "game_username": "PlayerOne",
  "avatar_url": "https://...",
  "member_since": "2026-01-10T08:30:00+00:00",
  "tournament_stats": {
    "tournaments_joined": 12,
    "tournaments_hosted": 8,
    "tournaments_completed": 7,
    "wins": 3,
    "podium_finishes": 5
  },
  "host": {
    "is_verified": true,
    "tier": "gold",
    "average_rating": 4.8,
    "completion_rate": 98.5,
    "on_time_payout_rate": 100.0
  }
}
```

Field rules:
- Show `display_name`, `game_username`, and `avatar_url` as the profile identity.
- Show `wins` and `podium_finishes` as player achievements. `tournaments_joined` counts confirmed community registrations only.
- Show the host badge and tier only when `host.is_verified` is `true`.
- `average_rating`, `completion_rate`, and `on_time_payout_rate` are `null` for an unverified host; do not render placeholders for them.
- This is intentionally a public-safe response. It never includes phone, email, address, date of birth, FID, payment details, or host-verification review status.

Errors:
- `404`: no public gamer exists for that `user_id`.

## Public Detail

### Get Tournament Detail
- **Method**: `GET`
- **Path**: `/events/<event_or_tournament_id>`

The backend first checks cafe `events`. If not found, it falls back to `community_tournaments`.

Response includes the feed fields plus detail fields:
```json
{
  "id": "uuid",
  "source": "community",
  "vendor_id": null,
  "host_user_id": 2482,
  "can_manage": true,
  "title": "BGMI Friday Cup",
  "description": "Squad tournament",
  "start_at": "2026-07-21T10:00:00+00:00",
  "end_at": "2026-07-21T14:00:00+00:00",
  "registration_fee": 50.0,
  "currency": "INR",
  "game": "BGMI",
  "format": "single_elimination",
  "prize_pool": 460.0,
  "team_size": 1,
  "match_rules": "No emulators",
  "region": null,
  "server": null,
  "check_in_starts_at": null,
  "check_in_ends_at": null,
  "map_pool": [],
  "veto_mode": "none",
  "capacity_team": null,
  "capacity_player": 64,
  "min_team_size": 1,
  "max_team_size": 1,
  "allow_solo": true,
  "allow_individual": true,
  "registration_deadline": "2026-07-20T10:00:00+00:00",
  "team_count": 10,
  "banner_image_url": "https://...",
  "flag": "upcoming"
}
```

## Leaderboard

### Get Unified Leaderboard
- **Method**: `GET`
- **Path**: `/events/<event_or_tournament_id>/leaderboard`

Query params:
- `stage`: `auto`, `winners`, or `provisional`. Default is `auto`.

Stage behavior:
- `auto`: returns final winners if available, otherwise provisional results.
- `winners`: returns final submitted winners.
- `provisional`: returns provisional/verified result standings.

Availability behavior:
- This endpoint always returns `200` for a valid UUID, including when the event has no published leaderboard yet or is not currently public.
- `availability = "available"`: render the returned entries.
- `availability = "not_available_yet"`: render a results-pending state; `leaderboard` will be an empty array. `event_title` and `source` can be `null` when the event is not publicly discoverable.

Cafe source:
- `winners` reads from `winners`.
- `provisional` reads from `provisional_results`.
- Entries are team-based.

Community source:
- `winners` reads from `community_tournament_payouts` created by host winner submission.
- `provisional` reads verified/admin-overridden `community_match_results`.
- Entries are user-based, but still include `team_name` as a display-compatible alias using `game_username` or user name.

Cafe response:
```json
{
  "event_id": "uuid",
  "event_title": "Hash Valorant Cup",
  "source": "cafe",
  "stage": "winners",
  "availability": "available",
  "leaderboard": [
    {
      "team_id": "uuid",
      "team_name": "Team Alpha",
      "user_id": null,
      "rank": 1
    }
  ]
}
```

Community final winners response:
```json
{
  "event_id": "uuid",
  "event_title": "BGMI Friday Cup",
  "source": "community",
  "stage": "winners",
  "availability": "available",
  "leaderboard": [
    {
      "team_id": null,
      "team_name": "PlayerOne",
      "user_id": 2482,
      "user_name": "Player One",
      "game_username": "PlayerOne",
      "rank": 1,
      "amount": 315.0,
      "currency": "INR",
      "payout_status": "pending_admin_approval"
    }
  ]
}
```

Community provisional response:
```json
{
  "event_id": "uuid",
  "event_title": "BGMI Friday Cup",
  "source": "community",
  "stage": "provisional",
  "leaderboard": [
    {
      "team_id": null,
      "team_name": "PlayerOne",
      "user_id": 2482,
      "user_name": "Player One",
      "game_username": "PlayerOne",
      "rank": 1,
      "score": "12 kills",
      "result_id": "uuid",
      "result_status": "verified"
    }
  ]
}
```

## Provisional Results

### Get Provisional Results
- **Method**: `GET`
- **Path**: `/events/<event_or_tournament_id>/results/provisional`

This route also supports both sources. Prefer `/leaderboard?stage=provisional` for new UI, but this endpoint is available for existing screens.

Community responses include `user_id`, `user_name`, `game_username`, `score`, and `status`. Cafe responses keep existing team fields.

## Frontend Rules

- Use `/events/public` for the main public tournament feed, regardless of source.
- Show **Manage tournament** only when `can_manage` is `true`; send the same Bearer token to the community management APIs.
- Use `source` to choose the correct CTA:
  - `cafe`: existing cafe event registration/team flow.
  - `community`: `POST /api/v1/community/tournaments/<id>/registrations`.
- Use `/events/<id>/leaderboard?stage=auto` for result/leaderboard widgets.
- When `availability` is `not_available_yet`, show a neutral results-pending state and do not treat the response as an error.
- For a community event's host panel, use `/gamers/<host_user_id>/profile`.
- Display `team_name` for both sources as the primary row label.
- For community final winners, show `amount`, `currency`, and `payout_status` when present.
- If `leaderboard` is empty, show an empty/results-pending state instead of treating it as an error.

## Backend Files

- `controllers/event_public_controller.py`
- `controllers/community_tournament_controller.py`
- `services/community_tournament_service.py`
- `models/communityTournament.py`
- `models/communityTournamentOperations.py`
