# Cloudinary Community Evidence Setup

This guide configures temporary result and dispute screenshots for community
tournaments. The app uploads the screenshot to Hash; Hash uploads it to
Cloudinary using the same Python SDK configuration as `hfg-dashboard-service`
and registers the evidence asset automatically.

## 1. Cloudinary Configuration

In the Cloudinary Console, open **Settings > Access Keys** and collect:

- Cloud name
- API key
- API secret

Set these variables in Render and any local deployment environment:

```env
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
COMMUNITY_EVIDENCE_RETENTION_DAYS=7
COMMUNITY_EVIDENCE_MAX_BYTES=10485760
```

`CLOUDINARY_API_SECRET` is backend-only. Never place it in the mobile app or
frontend configuration.

The Docker variables are defined in `docker-compose.yml` and loaded by
`app/config.py`.

## 2. Database Migration

Run this migration before deploying the backend:

```text
sql/20260820_community_evidence_retention.sql
```

It adds `community_tournaments.completed_at`. Cleanup retention begins from this
timestamp, rather than from the evidence upload date.

## 3. App Upload Flow

Submit the selected image as multipart form data. The app does not call
Cloudinary, does not need a signed URL, and does not call `/files` afterward.

```http
POST /api/v1/community/tournaments/{tournament_id}/evidence/upload
Authorization: Bearer <user-token>
Content-Type: multipart/form-data
```

Form fields:

```text
file=<image binary>
purpose=result_evidence
```

Allowed values for `purpose`:

- `result_evidence`
- `dispute_evidence`

Only the tournament host or a confirmed participant can upload evidence. The
image must be JPG, JPEG, PNG, or WebP and may not exceed
`COMMUNITY_EVIDENCE_MAX_BYTES` (10 MB by default).

Example response:

```json
{
  "id": "evidence-asset-uuid",
  "tournament_id": "{tournament_id}",
  "purpose": "result_evidence",
  "file_url": "https://res.cloudinary.com/your-cloud/image/upload/...",
  "storage_key": "hfg/community/{tournament_id}/evidence/result_evidence-unique-id",
  "mime_type": "image/png",
  "file_size_bytes": 204800,
  "metadata": {
    "storage_provider": "cloudinary",
    "temporary": true,
    "cleanup_status": "pending"
  }
}
```

The response contains the Hash evidence `id`. Use that ID in:

- `evidence_asset_ids` for a host result proposal
- `evidence_asset_ids` for a captain result submission
- `evidence_asset_ids` when disputing a proposal

The backend marks a valid Cloudinary evidence asset as:

```json
{
  "storage_provider": "cloudinary",
  "temporary": true,
  "cleanup_status": "pending"
}
```

## 4. Result and Dispute Usage

Host proposal:

```http
POST /api/v1/community/tournaments/{tournament_id}/matches/{match_id}/result-proposals
```

```json
{
  "winner_team_id": "winner-team-uuid",
  "team_a_score": 2,
  "team_b_score": 1,
  "evidence_asset_ids": ["cloudinary-evidence-asset-uuid"]
}
```

Player dispute:

```http
POST /api/v1/community/tournaments/{tournament_id}/matches/{match_id}/result-proposals/{proposal_id}/dispute
```

```json
{
  "description": "The final scoreboard shows a different winner.",
  "evidence_asset_ids": ["cloudinary-evidence-asset-uuid"]
}
```

## 5. Cleanup Cron

Create one daily cron job, preferably during low traffic:

```http
POST /api/v1/community/internal/evidence/purge-expired
X-Community-Payment-Cron-Token: <COMMUNITY_PAYMENT_CRON_TOKEN>
Content-Type: application/json

{
  "limit": 50
}
```

The job selects only assets that are:

1. `result_evidence` or `dispute_evidence`
2. Stored under the backend-issued Cloudinary evidence folder
3. Marked as Cloudinary temporary evidence
4. Attached to a completed tournament
5. Older than `COMMUNITY_EVIDENCE_RETENTION_DAYS` after `completed_at`

It calls Cloudinary's signed destroy API with CDN invalidation. A successful
deletion sets `metadata.cleanup_status` to `deleted`; the database record remains
for match and audit history. Failed deletion attempts become `retry_pending` and
are retried by the next cron run.

## 6. Security Rules

- Never expose `CLOUDINARY_API_SECRET` to the app.
- The app sends the original image only to the authenticated Hash endpoint.
- Hash owns the Cloudinary folder and `storage_key`.
- Accept only screenshots: `jpg`, `jpeg`, `png`, and `webp`.
- Always register `secure_url`, never a client-created arbitrary URL.
- Do not delete evidence rows from PostgreSQL; the Cloudinary object is deleted,
  but its audit tombstone remains.

## 7. Troubleshooting

| Problem | Likely Cause | Resolution |
| --- | --- | --- |
| `Cloudinary evidence storage is not configured` | Missing Cloudinary environment variable | Set all three Cloudinary variables and redeploy. |
| `storage_unavailable` | Cloudinary credentials are absent or Cloudinary is temporarily unavailable | Set all three Cloudinary variables, redeploy, then retry the multipart upload. |
| `file must be a jpg, jpeg, png, or webp image` | The app sent an unsupported MIME type or filename | Use an image file and retain its original extension. |
| Evidence is not deleted | Tournament has no `completed_at`, retention has not elapsed, or job has not run | Run the SQL migration, complete the tournament, then run the daily cleanup cron. |
| Cleanup retries | Cloudinary outage or temporary API error | Leave the asset record unchanged; the next cron invocation retries it. |
