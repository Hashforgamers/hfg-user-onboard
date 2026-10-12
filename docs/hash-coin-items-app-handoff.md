# HashCoin item purchases and app handoff

Local implementation; backend deployment and database migration are pending.

## Spend contract

POST /api/users/hash-coins/spend with the existing user JWT (user comes from token).

Fixed prices:
- arrow_escape_continue: 2000
- arrow_escape_hint: 200
- pac_man_continue: 1000
- plant_vs_zombie_continue: 1000
- wordly_reveal: 300

Item sources: ludo_skin_purchase (400–10000), mini_game_cosmetic (300–4000). These ranges constrain the catalog, not arbitrary client pricing. Supply item_id and the exact configured amount:
```json
{"amount":500,"source":"ludo_skin_purchase","item_id":"dice_neon","reference_id":"purchase-unique-id"}
```
This is an illustrative request, not a seeded product. The actual item_id/price list must be supplied before items are enabled. Missing item_id -> 400 invalid_item_id; unknown/disabled item -> 400 unknown_item; wrong amount -> 400 invalid_amount; unknown source -> 400 unknown_source.

200 {"hash_coins":3500}; insufficient -> 402 {"error":"insufficient_hash_coins","hash_coins":100}; changed payload with an existing reference -> 409 idempotency_conflict. Same user/reference/payload debits once and returns the ORIGINAL balance even after catalog edits or subsequent purchases. Keep references across network retries; refresh current balance separately. A new reference for an already owned source/item returns 409 item_already_owned, with current hash_coins, without debiting.

Consumable actions are repeatable; item sources are permanent ownership. Debit, receipt and ownership commit together. Do not grant an item until confirmed success; recover uncertain outcomes using the same reference and the ownership endpoint.

GET /api/users/hash-coins/purchases with user JWT returns only that token user's items:
```json
{"purchases":[{"source":"ludo_skin_purchase","item_id":"dice_neon","amount":500,"purchased_at":"2026-10-11T12:00:00Z"}]}
```
Reads are private/no-store; no user_id input. Purchases survive reinstall. Firestore/device state is a convenience cache, never proof of purchase. No automatic import of client-owned items is performed: those claims require a verified receipt/administrative migration.

## Rollout

Apply sql/20261011_hash_coin_spends.sql first if not already applied, then sql/20261011_hash_coin_items.sql. Populate hash_coin_items from the approved list with source,item_id,price,enabled; catalog writes are server/database administration only. Deploy backend before updating app. Existing fixed-action success response is unchanged.

## Firebase team changes (not deployed or verified here)

No Firestore rules or chat invite push dispatcher exist in the provided checkout, so this repository cannot establish the deployed match rules or change that handler.

Merge these blocks into the existing Firestore rules' /databases/{database}/documents scope, preserving other rules:
```
match /ludo_skins/{uid} {
  allow read, write: if request.auth != null && request.auth.uid == uid;
}
match /mini_game_cosmetics/{uid} {
  allow read, write: if request.auth != null && request.auth.uid == uid;
}
```
These rules allow users to edit their own cache (including fake cache ownership); server purchases remain authoritative. Check existing wildcard grants, because matching allow rules are additive and a permissive wildcard can bypass these restrictions. Test unauthenticated denial, own-document access, other-user denial in the Firebase emulator before deploying. If uid is a Hash numeric ID rather than Firebase auth.uid, do not use the above comparison without a trusted verified mapping.

Inspect the deployed wordly_matches rule and apply its participant authorization, field validation and update restrictions to arrow_escape_matches. Do not replace it with a generic signed-in read/write rule; match records may contain multiple participants. Confirm equality only after reviewing and testing both deployed rule blocks.

In the actual chat push dispatcher, add arrow_invite wherever wordly_invite is accepted/formatted, using the same verified sender and recipient checks and invite payload validation. Support mini_games_lounge only through the existing authorized group membership flow, excluding sender from push recipients and preventing duplicate pushes. Do not grant arbitrary room access or unrestricted match writes. Test direct/group arrow invites, invalid payloads, unauthorized sender, existing wordly invites and push deduplication. No messages or pushes were sent by this implementation.

## 12 October update

All supplied Ludo and mini-game item IDs and prices are seeded by sql/20261012_hash_coin_catalog.sql (53 items). Apply it after the two earlier migrations. Re-running the seed updates prices but preserves an operator's disabled flag.

Hash Rush uses the requested full source names, without item_id or level:
- hash_rush_continue: fixed 1000.
- hash_rush_upgrade_fireRate, cannonPower, startArmy, unitDamage, unitHealth, abilityCooldown (each with the hash_rush_upgrade_ prefix): amount must occur in its supplied ladder. Repeatable; server does not enforce level progression.
- hash_rush_skin_army_<id> and hash_rush_skin_cannon_<id>: emerald 150, royal 300, arctic 500, shadow 800, gold 1200. Permanent per user/full source. Purchases response includes full source plus item_id equal to the suffix, e.g. emerald. Omit item_id in these spend requests: the server derives it from source.

Only ludo_skin_purchase and mini_game_cosmetic require the client item_id field. Existing 200/400/402/409 response contracts are unchanged. No live deployment or production migration has been performed by this local update.
