# HashCoin spend API

Deploy `sql/20261011_hash_coin_spends.sql` against the shared PostgreSQL database before deploying this service. Then switch the app to Spend. No production migrations or purchases were run during implementation.

```http
POST https://hfg-user-onboard.onrender.com/api/users/hash-coins/spend
Authorization: Bearer <same authenticated user token used for hash-coins>
Content-Type: application/json

{"amount":2000,"source":"arrow_escape_continue","reference_id":"purchase-generated-uuid"}
```

The user comes only from the bearer token. Do not send a user ID. Expired tokens are rejected, including in legacy auth mode. Reference IDs must be nonempty strings of at most 128 characters with no surrounding whitespace. Persist the purchase reference before the first attempt; retries must reuse it.

- 200: `{"hash_coins":3000}` — integer coins remaining at the original successful purchase.
- 402: `{"error":"insufficient_hash_coins","hash_coins":1000}` — no debit or receipt; reference can be retried after earning coins.
- 400: `invalid_request`, `invalid_amount`, `unknown_source`, or `invalid_reference_id`.
- 409: `idempotency_conflict` if a successful reference is reused with a different allowed purchase.
- 401: authentication rejection / expired token.
- 500: `hash_coin_spend_failed`; retry using the same reference after recovery, never generate another reference for the same purchase.

The only enabled price is `arrow_escape_continue: 2000`. `ludo_skin_purchase` is not enabled until a server-side price is defined. Prices are configured in `services/hash_coin_spend.py`, not accepted from the app. All amounts are whole coins, not rupees/paise.

References are scoped to the authenticated user and unique across sources. Successful retries return the original receipt result even if later purchases changed the current balance. Refresh GET `/api/users/hash-coins` when the app needs current balance; invalidate its local cached balance after a successful spend.

Balance updates and receipt insertion commit atomically. Concurrent spends serialize on the balance row; credit uses an atomic SQL increment on the same row. Keep receipts durable for audit and retry safety. Do not delete receipts while retrying clients may exist.

## Existing credit endpoint

Before this change, POST `/api/users/hash-coins` already rejected negative amounts, including `-2000`, with HTTP 400. It did accept JSON `true` as an integer; that is now rejected. The app must remove the negative-credit stopgap and use Spend. Existing credit responses retain their `new_hash_coins` field. This implementation does not redesign who is allowed to grant credits through that pre-existing route.

## App behavior

Grant the continuation only after confirmed HTTP 200. On a lost response, retry the same reference to determine whether the debit committed. Prevent duplicate local grants for the same purchase reference. Treat 402 as insufficient coins. Do not fall back to a negative credit request, wallet debit, or client-calculated price.
