# Graph Report - hfg-user-onboard  (2026-10-20)

## Corpus Check
- 118 files · ~72,908 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1120 nodes · 3056 edges · 79 communities (64 shown, 15 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 189 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `64a8f2fd`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- community_tournament_controller.py
- payment_service.py
- community_tournament_control_service.py
- create_tournament
- event_participation_controller.py
- community_tournament_service.py
- tournament_engine_controller.py
- extensions.py
- community_tournaments
- review_controller.py
- CommunityEsportsOperationTests
- User APIs
- user_controller.py
- community_dispute_chat_service.py
- user_service.py
- Voucher
- CommunityValidationError
- passModels.py
- app/__init__.py
- Phone Number APIs (hfg-user-onboard)
- Unified Public Tournament APIs
- DropCrateClaimTests
- _run_notification_dispatch_job
- _EmailText
- _now
- _refund_or_cancel_registration
- WalletCreditSecurityTests
- delete_user_id
- enqueue_community_payment_webhook
- test_notification_campaign.py
- Community Host Tournament Management E2E
- 3B. Match Operations
- UserSignupApiTests
- create_community_payment_attempt
- Cloudinary Community Evidence Setup
- Community Tournament APIs (Frontend Handoff)
- tournament_matches
- Exception
- drop-crate-claim.md
- notification-context.md
- 20261005_notification_context.sql
- RazorpayWebhookTests
- 2. Create and Edit a Tournament
- 3A. Esports Teams and Rosters
- 4. Results and Disputes
- Suggested Screen Flows
- Public APIs
- 3. Participant and Check-in Management
- 3C. Control Room and Communication
- Data Models
- 1. Host Onboarding
- 6. Platform Admin Operations
- booking.py
- test_hash_coin_spend_pg.py
- HashCoin item purchases and app handoff
- AGENTS.md
- user-deletion-lifecycle.md
- job/__init__.py
- 20260817_user_soft_deletion.sql
- test_seed_20_community_tournament_participants.sql
- cafe_reviews
- registrations
- users
- security.py

## God Nodes (most connected - your core abstractions)
1. `CommunityValidationError` - 108 edges
2. `auth_required_self()` - 78 edges
3. `CommunityConflictError` - 76 edges
4. `_handle_service_error()` - 67 edges
5. `CommunityForbiddenError` - 59 edges
6. `_now()` - 47 edges
7. `_audit()` - 44 edges
8. `CommunityStorageError` - 37 edges
9. `_body()` - 32 edges
10. `CommunityEsportsOperationTests` - 28 edges

## Surprising Connections (you probably didn't know these)
- `CommunityValidationError` --uses--> `CommunityHostStatus`  [INFERRED]
  services/community_tournament_service.py → models/communityTournament.py
- `CommunityValidationError` --uses--> `CommunityHostTier`  [INFERRED]
  services/community_tournament_service.py → models/communityTournament.py
- `CommunityValidationError` --uses--> `CommunityTournamentStatus`  [INFERRED]
  services/community_tournament_service.py → models/communityTournament.py
- `CommunityEsportsOperationTests` --uses--> `CommunityTournamentStatus`  [INFERRED]
  tests/test_community_esports_operations.py → models/communityTournament.py
- `CommunityValidationError` --uses--> `CommunityTournamentRegistrationStatus`  [INFERRED]
  services/community_tournament_service.py → models/communityTournament.py

## Import Cycles
- None detected.

## Communities (79 total, 15 thin omitted)

### Community 0 - "community_tournament_controller.py"
Cohesion: 0.08
Nodes (94): after_request, accept_community_result_proposal(), admin_list_community_disputes(), admin_list_community_payouts(), admin_list_duplicate_payment_recoveries(), admin_list_host_verifications(), admin_list_pending_community_payments(), _admin_required() (+86 more)

### Community 1 - "payment_service.py"
Cohesion: 0.07
Nodes (54): Any, _amount_in_paise(), _as_dict(), create_payment_intent(), fetch_tournament_payment(), fetch_tournament_payment_for_order(), fetch_tournament_refund(), _mock_create_intent() (+46 more)

### Community 2 - "community_tournament_control_service.py"
Cohesion: 0.09
Nodes (36): CommunityMatchResultSubmission, CommunityTeamStatus, CommunityTournamentReview, CommunityTournamentTeam, CommunityTournamentTeamMember, _auto_check_in_teams(), _automatic_team_ready(), create_team() (+28 more)

### Community 3 - "create_tournament"
Cohesion: 0.15
Nodes (21): _banner_asset(), _bounded_int(), cancel_registration(), create_tournament(), get_tournament(), _host_commission_rate(), _invite_code_hash(), _json_object() (+13 more)

### Community 4 - "event_participation_controller.py"
Cohesion: 0.06
Nodes (62): _body(), create_team(), _dispatch_push_async(), _event_flag(), force_remove_team_member(), get_team_members(), get_user_joined_tournaments(), get_user_teams() (+54 more)

### Community 5 - "community_tournament_service.py"
Cohesion: 0.09
Nodes (49): CommunityFileAsset, CommunityHostStatus, CommunityHostTier, CommunityHostVerification, CommunityTournament, CommunityTournamentRegistration, CommunityTournamentRegistrationStatus, CommunityTournamentStatus (+41 more)

### Community 6 - "tournament_engine_controller.py"
Cohesion: 0.20
Nodes (21): add_map_veto(), _advance_winner(), _body(), _build_lobby_instructions(), check_in_team(), confirm_match(), _ensure_captain(), _ensure_team_member() (+13 more)

### Community 7 - "extensions.py"
Cohesion: 0.05
Nodes (16): BookingExtraService, CafePass, ExtraServiceCategory, ExtraServiceMenu, ExtraServiceMenuImage, FCMToken, MatchParticipant, PassType (+8 more)

### Community 8 - "community_tournaments"
Cohesion: 0.14
Nodes (24): community_audit_logs, community_file_assets, community_host_verifications, community_match_results, community_tournament_disputes, community_tournament_payouts, community_tournament_registrations, community_tournaments (+16 more)

### Community 9 - "review_controller.py"
Cohesion: 0.27
Nodes (16): _clean_text(), create_review(), edit_review(), _internal_authorized(), internal_list_reviews(), internal_respond_review(), internal_reviews_summary(), internal_update_review_status() (+8 more)

### Community 10 - "CommunityEsportsOperationTests"
Cohesion: 0.12
Nodes (3): _derive_status(), CommunityEsportsOperationTests, patch

### Community 11 - "User APIs"
Cohesion: 0.08
Nodes (25): Admin Referee Result, Authenticated Tournament Detail, Cancel My Registration, Cancel Tournament, Captain-Submitted Result Alternative, Close Registration Early, Cloudinary Evidence Upload, Create Dispute (+17 more)

### Community 12 - "user_controller.py"
Cohesion: 0.09
Nodes (48): add_hash_coins(), add_wallet_balance(), claim_drop_crate(), create_voucher_for_referral_points(), _ensure_hash_wallet_row(), get_all_fcm(), get_extra_service(), get_extra_service_categories() (+40 more)

### Community 13 - "community_dispute_chat_service.py"
Cohesion: 0.18
Nodes (19): _admin_user_ids(), CommunityDisputeChatError, _dispute_initiator(), _evidence_previews(), firebase_uid_for_user(), _match_details(), _match_participant_user_ids(), mint_dispute_chat_token() (+11 more)

### Community 14 - "user_service.py"
Cohesion: 0.06
Nodes (24): _merge_existing_user_by_email(), Merge signup payload into an existing user identified by email. Also updates…, declared_attr, ContactInfo, Safely serialize contact info to dictionary, DeletedUserCooldown, HashWallet, PasswordManager (+16 more)

### Community 16 - "CommunityValidationError"
Cohesion: 0.17
Nodes (23): CommunityTournamentAnnouncement, create_announcement(), create_manual_match(), host_results_overview(), list_audit_log(), Operational result-tab payload for the tournament manager., CommunityValidationError, _gamer_summaries() (+15 more)

### Community 17 - "passModels.py"
Cohesion: 0.12
Nodes (6): CafePass, PassRedemptionLog, PassType, Generate unique pass UID for hour-based passes, Validate pass configuration, UserPass

### Community 18 - "app/__init__.py"
Cohesion: 0.31
Nodes (5): Config, load_key_from_file(), init_firebase(), Send an FCM notification and return structured status for async workers., send_notification_with_result()

### Community 19 - "Phone Number APIs (hfg-user-onboard)"
Cohesion: 0.13
Nodes (14): 1) Check Registered Phone, 2) Update Registered Phone, Error Responses, Latency Notes (Production), Ownership / Source, Phone Number APIs (hfg-user-onboard), Request, Request Body (+6 more)

### Community 20 - "Unified Public Tournament APIs"
Cohesion: 0.13
Nodes (14): Backend Files, Frontend Rules, Gamer Profile, Get Gamer Profile, Get Provisional Results, Get Tournament Detail, Get Unified Leaderboard, Leaderboard (+6 more)

### Community 22 - "_run_notification_dispatch_job"
Cohesion: 0.11
Nodes (22): create_app(), cron_trigger_daily_notifications(), _ensure_notification_tracking_tables(), get_notification_dispatch_job(), _is_valid_cron_request(), list_notification_dispatch_failures(), notification_dispatch_failures_summary(), preview_campaign_notification() (+14 more)

### Community 23 - "_EmailText"
Cohesion: 0.20
Nodes (8): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., generate_referral_code(), send_email()

### Community 24 - "_now"
Cohesion: 0.10
Nodes (47): CommunityTournamentDispute, accept_result_proposal(), admin_resolve_match_result(), _advance_match_winner(), create_result_proposal(), dispute_result_proposal(), _finalize_result_proposal(), manage_match() (+39 more)

### Community 25 - "_refund_or_cancel_registration"
Cohesion: 0.37
Nodes (7): _apply_wallet_transaction(), Keep the wallet balance and its immutable transaction ledger in sync., _refund_or_cancel_registration(), CommunityRegistrationRefundTests, patch, registration(), tournament()

### Community 27 - "delete_user_id"
Cohesion: 0.24
Nodes (10): _clear_deleted_user_caches(), delete_user_id(), _is_valid_user_deletion_cron_request(), _purge_soft_deleted_user(), purge_soft_deleted_users(), Return records that must be retained instead of hard-deleted., restore_deleted_user(), _user_deletion_blockers() (+2 more)

### Community 28 - "enqueue_community_payment_webhook"
Cohesion: 0.67
Nodes (3): enqueue_community_payment_webhook(), _find_community_registration_for_provider_ids(), Persist an already-authenticated provider event before acknowledging it.

### Community 29 - "test_notification_campaign.py"
Cohesion: 0.53
Nodes (4): generator(), test_ai_failure_uses_configured_fallback(), test_invalid_ai_response_uses_configured_fallback(), test_saved_context_replaces_old_campaign()

### Community 30 - "Community Host Tournament Management E2E"
Cohesion: 0.20
Nodes (9): 5. Winners and Payouts, 5A. Organizer Reputation, Community Host Tournament Management E2E, Error Handling, Frontend Rules, Host Payout Tracker, Lifecycle, Roles and Access (+1 more)

### Community 31 - "3B. Match Operations"
Cohesion: 0.20
Nodes (10): 3B. Match Operations, Admin Referee Resolution, Captain Result Agreement, Dispute Chat Provisioning, Generate Schedule and Bracket, Host Result Proposal and 15-Minute Review, Operate a Match, Read Matches (+2 more)

### Community 32 - "UserSignupApiTests"
Cohesion: 0.13
Nodes (9): create_user(), _find_existing_user_fid_by_email(), _invalidate_fid_caches(), Attach requested_fid to the existing user identified by email. Returns dict:…, _relink_fid_for_existing_email(), _sanitize_signup_payload(), _validate_signup_payload(), patch (+1 more)

### Community 33 - "create_community_payment_attempt"
Cohesion: 0.29
Nodes (7): _bind_verified_payment_attempt(), create_community_payment_attempt(), _payment_attempt_receipt(), _payment_checkout_payload(), Keep the Razorpay receipt unique, stable, and within its 40-character limit., Create or reuse the one active Razorpay checkout for a registration. The public…, Attach a provider-verified payment to its registration exactly once.

### Community 34 - "Cloudinary Community Evidence Setup"
Cohesion: 0.22
Nodes (8): 1. Cloudinary Configuration, 2. Database Migration, 3. App Upload Flow, 4. Result and Dispute Usage, 5. Cleanup Cron, 6. Security Rules, 7. Troubleshooting, Cloudinary Community Evidence Setup

### Community 35 - "Community Tournament APIs (Frontend Handoff)"
Cohesion: 0.22
Nodes (8): Admin APIs, Community Tournament APIs (Frontend Handoff), Frontend Feature Scope, Frontend Validation Checklist, Review Dispute, Review Host Verification, Source Files, Status Values

### Community 36 - "tournament_matches"
Cohesion: 0.58
Nodes (8): events, map_veto_actions, match_disputes, match_participants, match_result_submissions, tournament_matches, tournament_seeds, teams

### Community 37 - "Exception"
Cohesion: 0.17
Nodes (9): create_registration(), create_team(), get_event(), get_open_events(), get_results(), route, Exception, ProvisionalResults (+1 more)

### Community 41 - "RazorpayWebhookTests"
Cohesion: 0.48
Nodes (3): object, dict, RazorpayWebhookTests

### Community 42 - "2. Create and Edit a Tournament"
Cohesion: 0.33
Nodes (6): 2. Create and Edit a Tournament, Cancel Tournament, Create a Draft, Edit or Publish, Host Dashboard List and Detail, Upload/Register a File Asset

### Community 43 - "3A. Esports Teams and Rosters"
Cohesion: 0.33
Nodes (6): 3A. Esports Teams and Rosters, Accept or Decline Roster Invitation, Create Team for a Registration, Invite One Member, Replace Roster, Team Lists and Host Actions

### Community 44 - "4. Results and Disputes"
Cohesion: 0.33
Nodes (6): 4. Results and Disputes, Host Dispute Inbox, Host Result Inbox, Player Opens a Dispute, Submit a Result, Verify or Reject Result

### Community 45 - "Suggested Screen Flows"
Cohesion: 0.33
Nodes (6): Discovery, Host Onboarding, Paid Registration, Suggested Screen Flows, Tournament Creation, Tournament Detail

### Community 46 - "Public APIs"
Cohesion: 0.33
Nodes (6): Health, Host Program Config, List Tournaments, Public APIs, Public Tournament Detail, Shared Public Events Feed

### Community 47 - "3. Participant and Check-in Management"
Cohesion: 0.67
Nodes (3): 3. Participant and Check-in Management, Host Roster, Player Registration

### Community 48 - "3C. Control Room and Communication"
Cohesion: 0.40
Nodes (5): 3C. Control Room and Communication, Captured Payment Recovery and Duplicate Refunds, Host Registration Actions, Payment Retry Queue, Rules and Publish Readiness

### Community 49 - "Data Models"
Cohesion: 0.40
Nodes (5): Data Models, File Asset, Host Verification, Registration, Tournament

### Community 50 - "1. Host Onboarding"
Cohesion: 0.50
Nodes (4): 1. Host Onboarding, Read Host Program, Read My Verification State, Submit or Resubmit Verification

### Community 51 - "6. Platform Admin Operations"
Cohesion: 0.50
Nodes (4): 6. Platform Admin Operations, Dispute Queue and Review, Payout Queue and Settlement, Review Host Verification

### Community 53 - "test_hash_coin_spend_pg.py"
Cohesion: 0.18
Nodes (16): fixture, parametrize, spend(), buy(), coins(), test_balance_and_receipt_rollback_together(), test_competing_purchases_do_not_overdraw(), test_concurrent_item_purchase_different_references() (+8 more)

### Community 54 - "HashCoin item purchases and app handoff"
Cohesion: 0.18
Nodes (9): 12 October update, Firebase team changes (not deployed or verified here), HashCoin item purchases and app handoff, Rollout, Spend contract, App behavior, Existing credit endpoint, HashCoin spend API (+1 more)

### Community 76 - "security.py"
Cohesion: 0.25
Nodes (6): _build_auth_response_for_fid(), get_user_by_fid_auth(), Build the same payload contract as GET /users/fid/<fid>: {"user": ..., "token":…, encode_user(), Encode a user ID using RSA public key PEM string. Returns a base64-encoded…, Fetch only fields required by /users/fid auth response. Returns already-…

## Knowledge Gaps
- **133 isolated node(s):** `BookingExtraService`, `EventStatus`, `MatchParticipant`, `TournamentSeed`, `community_audit_logs` (+128 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `User` connect `user_service.py` to `UserSignupApiTests`, `community_tournament_control_service.py`, `event_participation_controller.py`, `community_tournament_service.py`, `review_controller.py`, `user_controller.py`, `community_dispute_chat_service.py`, `Voucher`, `CommunityValidationError`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `CommunityValidationError` connect `CommunityValidationError` to `community_tournament_controller.py`, `create_community_payment_attempt`, `community_tournament_control_service.py`, `create_tournament`, `event_participation_controller.py`, `community_tournament_service.py`, `payment_service.py`, `CommunityEsportsOperationTests`, `user_service.py`, `_now`, `enqueue_community_payment_webhook`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `auth_required_self()` connect `community_tournament_controller.py` to `review_controller.py`, `delete_user_id`, `user_controller.py`, `security.py`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `CommunityValidationError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityValidationError` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `CommunityConflictError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityConflictError` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `CommunityForbiddenError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityForbiddenError` has 33 INFERRED edges - model-reasoned connections that need verification._
- **What connects `BookingExtraService`, `EventStatus`, `MatchParticipant` to the rest of the system?**
  _133 weakly-connected nodes found - possible documentation gaps or missing edges._