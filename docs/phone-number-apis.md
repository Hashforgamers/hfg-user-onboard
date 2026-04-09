# Phone Number APIs (hfg-user-onboard)

This document covers the production APIs to:
- Check whether the logged-in user has a registered phone number.
- Create/update the logged-in user's registered phone number.

Base URL examples:
- Production: `https://hfg-user-onboard.onrender.com/api`
- Local: `http://localhost:5000/api`

Authentication:
- Both APIs require `Authorization: Bearer <token>`.
- Token is validated through `auth_required_self(decrypt_user=True)`.

## 1) Check Registered Phone

- **Method**: `GET`
- **Path**: `/users/phone/registered`
- **Purpose**: Returns whether a phone number exists for the authenticated user.

### Request
```bash
curl --request GET \
  --url 'https://hfg-user-onboard.onrender.com/api/users/phone/registered' \
  --header 'Authorization: Bearer <JWT_TOKEN>'
```

### Success Response (200)
```json
{
  "success": true,
  "user_id": 128,
  "is_phone_registered": true,
  "phone": "9876543210"
}
```

### Success Response (200, no phone)
```json
{
  "success": true,
  "user_id": 128,
  "is_phone_registered": false,
  "phone": null
}
```

### Error Responses
- `401/403`: Invalid token or unauthorized
- `500`: Internal server error

## 2) Update Registered Phone

- **Method**: `PUT`
- **Path**: `/users/phone`
- **Purpose**: Updates or creates the phone number entry in `contact_info` for the authenticated user.

### Request Body
```json
{
  "phone": "+91 9876543210"
}
```

Accepted input forms:
- `9876543210`
- `09876543210`
- `919876543210`
- `+91 9876543210`

Stored format:
- Always normalized to `10-digit` Indian mobile format, e.g. `9876543210`.

### Request Example
```bash
curl --request PUT \
  --url 'https://hfg-user-onboard.onrender.com/api/users/phone' \
  --header 'Authorization: Bearer <JWT_TOKEN>' \
  --header 'Content-Type: application/json' \
  --data '{"phone":"+91 9876543210"}'
```

### Success Response (200)
```json
{
  "success": true,
  "message": "Phone number updated successfully",
  "user_id": 128,
  "phone": "9876543210"
}
```

### Validation/Error Responses
- `400` invalid format:
```json
{
  "success": false,
  "message": "Valid Indian phone number is required",
  "format": "Use 10-digit mobile number (supports +91/0 prefix input)"
}
```

- `409` duplicate phone used by another user:
```json
{
  "success": false,
  "message": "Phone number already registered with another user"
}
```

- `401/403`: Invalid token or unauthorized
- `500`: Internal server error

## Latency Notes (Production)

Target:
- Keep typical response near/under 50 ms at application layer.

Optimizations implemented:
- Lightweight SQL-only query paths.
- Small in-memory cache for `GET /users/phone/registered`.
- Cache invalidation after phone update.
- Lookup indexes in migration:
  - `idx_contact_info_user_parent_lookup (parent_type, parent_id)`
  - `idx_contact_info_user_phone_lookup (parent_type, phone)`

Migration file:
- `sql/20260406_contact_info_phone_fast_lookup_indexes.sql`

## Rollout Checklist

1. Deploy app code with new endpoints.
2. Run SQL migration on production DB.
3. Smoke test both endpoints with a real auth token.
4. Monitor p95 latency and DB query plans.

## Ownership / Source

Controller implementation:
- `controllers/user_controller.py`

Routes:
- `GET /api/users/phone/registered`
- `PUT /api/users/phone`
