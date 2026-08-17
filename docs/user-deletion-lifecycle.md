# User Deletion Lifecycle

Run `sql/20260817_user_soft_deletion.sql` before deploying the backend.

`DELETE /api/users` now returns `202` and places an eligible account in a
seven-day `pending_purge` quarantine. It does not delete relational data.
Users with active tournament or event-team obligations receive `409` and must
leave, transfer, cancel, or resolve those obligations first.

`POST /api/users/restore` restores a quarantined account when called with a
still-valid account token before `purge_after`.

Schedule this endpoint once daily after the 7-day retention period:

```text
POST /api/internal/users/purge-deleted
X-User-Deletion-Cron-Token: <USER_DELETION_CRON_TOKEN>
Content-Type: application/json

{"limit": 50}
```

The purge writes `user_deletion_archives` with a hashed FID and record counts,
then deletes credentials/contact data and anonymizes the retained user row.
Financial and tournament references remain valid without retaining personal
details.
