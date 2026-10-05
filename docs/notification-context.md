# Managed push notification context

Apply `sql/20261005_notification_context.sql` once to the shared PostgreSQL database used by hfg-onboard and hfg-user-onboard. Both services must see the same campaign row. Deploy both services and vendor-Onboard. Configure hfg-user-onboard SUPER_ADMIN_API_KEY to match the existing key on hfg-onboard. The key remains server-side and is never sent to the dashboard browser. Optional hfg-onboard USER_ONBOARD_BACKEND_URL defaults to the production user service.

Super admin → Push notifications → describe campaign, audience, tone, language, verified offers and CTA → Generate preview → Save settings. Preview uses unsaved form contents and generates AI text without invoking FCM. When AI is unavailable, the preview explicitly reports the configured fallback. Settings are saved in PostgreSQL and read fresh by each cron/job generation; no code deployment is needed for subsequent context edits.

The existing POST /api/cron/notifications/daily, cron credentials, external two-hour schedule and 06:00–22:00 IST time window remain. Disabled settings skip new cron triggers, including force requests, and queued workers check enabled again before generation/sending. Already sending jobs can finish. The endpoint fails closed if campaign settings cannot be read. Apply the migration before deploying the new cron code.

If no campaign row exists yet, the original AI prompt remains the initial default. Once an admin saves context, it replaces the old campaign task while fixed output-format rules remain. Configured fallback title/message are used when generation fails. Existing explicit title/message cron overrides remain supported when enabled.

The implementation and tests did not send live notifications or invoke a real AI preview.
