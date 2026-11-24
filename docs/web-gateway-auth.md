# Web gateway login endpoints

Used only by the website's server (hfg-new-landing-page `/api/secure/*`), never by browsers or the app.

- `POST /api/web/auth/session` `{ "idToken": "<firebase id token>" }` → same `{user, token}` body and `Authorization` header as `GET /api/users/fid/<fid>`, or `404 {needs_signup: true}`.
- `POST /api/web/auth/signup` `{ "idToken": "...", "profile": {...same fields as POST /api/users...} }` → calls the existing `create_user()`; fid, phone and email are forced from the verified token.

Both require an HMAC signature from the website server:

```
X-HFG-Gateway-Key: <key id>
X-HFG-Gateway-Ts: <unix seconds>      (±60s)
X-HFG-Gateway-Nonce: <random, single use>
X-HFG-Gateway-Signature: hex(HMAC-SHA256(secret, "METHOD\nPATH\nTS\nNONCE\nsha256hex(body)"))
```

Env: `WEB_GATEWAY_HMAC_SECRETS="web1:<secret ≥32 chars>[,web2:<next secret>]"` (rotate by adding the new one first).
Missing config fails closed with 503. The nonce cache is per process; run behind one worker or add Redis if you scale out.
The Firebase token must be fresh (auth_time ≤ 15 min) and is checked for revocation.
Existing app endpoints are unchanged.
