# Drop crate claim

Deploy hfg-user-onboard to expose `POST /api/users/wallet/drop-crate/claim`.
No schema migration or wallet credit token is required for this endpoint.

The app sends `Authorization: Bearer <login JWT>` with an empty JSON object
(`{}`) or no body. No other fields are accepted.

First claim (HTTP 200):
```json
{"message":"Drop crate claimed","amount":10,"credited_amount":10,"new_balance":35,"already_claimed":false,"idempotent":false}
```

A retry returns HTTP 200 with `credited_amount: 0`, `already_claimed: true`,
`idempotent: true`, and the current wallet balance. Show an already-claimed
state instead of another reward animation. Refresh the wallet after success.

Eligibility is an existing, non-deleted account with an unexpired login JWT
and no prior `drop_crate` wallet transaction. This includes legacy claims
with different references. The reward is 10 existing wallet units (₹10 under
the current wallet convention); amount and recipient are fixed server-side.
Claims are per account, not per device or natural person.

Wallet creation, the wallet row lock, the eligibility lookup, the balance
update, and the ledger entry run in one database transaction. PostgreSQL's
normal READ COMMITTED isolation allows a waiting concurrent request to see
the first request's committed claim. Keep drop_crate ledger history intact.

Errors: 400 for a nonempty/invalid body; 401 for missing, invalid, or expired
JWT; 404 for a missing/deleted account; 500 for a failed transaction (safe to retry).
The shared authentication middleware may reject deleted accounts earlier.

General `POST /api/users/wallet` retains its internal-token requirement.
Never include that token in the app. Before production rollout, exercise two
simultaneous claims against a staging PostgreSQL database and confirm one
ledger entry and exactly a 10-unit balance increase.
