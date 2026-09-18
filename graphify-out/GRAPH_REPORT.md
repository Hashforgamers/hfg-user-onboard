# Graph Report - hfg-user-onboard  (2026-09-18)

## Corpus Check
- 105 files · ~69,074 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1048 nodes · 2937 edges · 76 communities (62 shown, 14 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 184 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8b30c6c1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- community_tournament_controller.py
- payment_service.py
- community_tournament_control_service.py
- community_tournament_service.py
- event_participation_controller.py
- CommunityConflictError
- tournament_engine_controller.py
- user_controller.py
- community_tournaments
- review_controller.py
- CommunityEsportsOperationTests
- User APIs
- route
- community_dispute_chat_service.py
- UserService
- extensions.py
- user_service.py
- passModels.py
- add_wallet_balance
- Phone Number APIs (hfg-user-onboard)
- Unified Public Tournament APIs
- delete_user_id
- _run_notification_dispatch_job
- _EmailText
- process_pending_community_payments
- _refund_or_cancel_registration
- WalletCreditSecurityTests
- security.py
- upload_temporary_evidence
- _ensure_notification_tracking_tables
- Community Host Tournament Management E2E
- 3B. Match Operations
- UserSignupApiTests
- PasswordManager
- Cloudinary Community Evidence Setup
- Community Tournament APIs (Frontend Handoff)
- tournament_matches
- Exception
- _result_contexts
- event_controller.py
- create_user
- RazorpayWebhookTests
- 2. Create and Edit a Tournament
- 3A. Esports Teams and Rosters
- 4. Results and Disputes
- Suggested Screen Flows
- Public APIs
- vendor.py
- 3C. Control Room and Communication
- Data Models
- 1. Host Onboarding
- 6. Platform Admin Operations
- booking.py
- PhysicalAddress
- 5. Winners and Payouts
- review_payout
- AGENTS.md
- user-deletion-lifecycle.md
- job/__init__.py
- 20260817_user_soft_deletion.sql
- test_seed_20_community_tournament_participants.sql
- cafe_reviews
- registrations
- users

## God Nodes (most connected - your core abstractions)
1. `CommunityValidationError` - 108 edges
2. `CommunityConflictError` - 76 edges
3. `auth_required_self()` - 75 edges
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

## Communities (76 total, 14 thin omitted)

### Community 0 - "community_tournament_controller.py"
Cohesion: 0.08
Nodes (91): after_request, accept_community_result_proposal(), admin_list_community_disputes(), admin_list_community_payouts(), admin_list_duplicate_payment_recoveries(), admin_list_host_verifications(), admin_list_pending_community_payments(), _admin_required() (+83 more)

### Community 1 - "payment_service.py"
Cohesion: 0.07
Nodes (54): Any, _amount_in_paise(), _as_dict(), create_payment_intent(), fetch_tournament_payment(), fetch_tournament_payment_for_order(), fetch_tournament_refund(), _mock_create_intent() (+46 more)

### Community 2 - "community_tournament_control_service.py"
Cohesion: 0.09
Nodes (63): CommunityTournamentAnnouncement, CommunityTournamentDispute, accept_result_proposal(), admin_resolve_match_result(), _advance_match_winner(), _auto_check_in_teams(), _automatic_team_ready(), control_room() (+55 more)

### Community 3 - "community_tournament_service.py"
Cohesion: 0.10
Nodes (56): CommunityHostVerification, create_manual_match(), list_audit_log(), _banner_asset(), _bind_verified_payment_attempt(), _bounded_int(), cancel_registration(), CommunityValidationError (+48 more)

### Community 4 - "event_participation_controller.py"
Cohesion: 0.10
Nodes (40): _body(), create_team(), _dispatch_push_async(), _event_flag(), force_remove_team_member(), get_team_members(), get_user_joined_tournaments(), get_user_teams() (+32 more)

### Community 5 - "CommunityConflictError"
Cohesion: 0.10
Nodes (36): CommunityHostStatus, CommunityHostTier, CommunityTournament, CommunityTournamentRegistration, CommunityTournamentRegistrationStatus, CommunityTournamentStatus, CommunityAuditLog, CommunityDisputeStatus (+28 more)

### Community 6 - "tournament_engine_controller.py"
Cohesion: 0.09
Nodes (41): _event_flag(), get_event(), get_event_leaderboard(), get_event_provisional_results(), get_public_gamer_profile(), list_public_events(), _optional_request_user_id(), get (+33 more)

### Community 7 - "user_controller.py"
Cohesion: 0.09
Nodes (16): get_all_fcm(), get_user(), _normalize_indian_phone(), Update (or create) user phone entry in contact_info. Production-safe checks: -…, register_fcm_token(), update_registered_phone(), user_purchase_pass(), CafePass (+8 more)

### Community 8 - "community_tournaments"
Cohesion: 0.14
Nodes (24): community_audit_logs, community_file_assets, community_host_verifications, community_match_results, community_tournament_disputes, community_tournament_payouts, community_tournament_registrations, community_tournaments (+16 more)

### Community 9 - "review_controller.py"
Cohesion: 0.16
Nodes (20): Config, create_app(), _clean_text(), create_review(), edit_review(), _internal_authorized(), internal_list_reviews(), internal_respond_review() (+12 more)

### Community 10 - "CommunityEsportsOperationTests"
Cohesion: 0.11
Nodes (3): _derive_status(), CommunityEsportsOperationTests, patch

### Community 11 - "User APIs"
Cohesion: 0.08
Nodes (25): Admin Referee Result, Authenticated Tournament Detail, Cancel My Registration, Cancel Tournament, Captain-Submitted Result Alternative, Close Registration Early, Cloudinary Evidence Upload, Create Dispute (+17 more)

### Community 12 - "route"
Cohesion: 0.18
Nodes (24): get_extra_service(), get_extra_service_categories(), get_extra_service_menu_item(), get_extra_service_menus(), get_registered_phone_status(), get_user_available_passes_by_id(), get_user_hash_coins(), get_voucher_by_user() (+16 more)

### Community 13 - "community_dispute_chat_service.py"
Cohesion: 0.14
Nodes (18): CommunityFileAsset, CommunityMatchResult, CommunityMatchResultSubmission, CommunityTournamentTeamMember, _admin_user_ids(), CommunityDisputeChatError, firebase_uid_for_user(), _match_details() (+10 more)

### Community 14 - "UserService"
Cohesion: 0.12
Nodes (12): ContactInfo, Safely serialize contact info to dictionary, ReferralTracking, Idempotent finalization for post-signup side effects. Safe to run multiple…, Add physical address to user using relationship, Add contact info to user using relationship, Creates a new user and related entities in the database, with validations., Fetch a user by ID with eager loading of relationships (+4 more)

### Community 15 - "extensions.py"
Cohesion: 0.11
Nodes (6): BookingExtraService, MatchParticipant, ProvisionalResults, TournamentSeed, VerificationChecks, Winners

### Community 16 - "user_service.py"
Cohesion: 0.18
Nodes (6): DeletedUserCooldown, HashWallet, Safely serialize user object to dictionary, User, Voucher, create_voucher_if_eligible()

### Community 17 - "passModels.py"
Cohesion: 0.12
Nodes (6): CafePass, PassRedemptionLog, PassType, Generate unique pass UID for hour-based passes, Validate pass configuration, UserPass

### Community 18 - "add_wallet_balance"
Cohesion: 0.16
Nodes (13): add_hash_coins(), add_wallet_balance(), create_voucher_for_referral_points(), _ensure_hash_wallet_row(), _invalidate_user_microcache(), mark_notification_read(), notify_user(), Example: Add hash coins to user and notify. { "amount": 500 } (+5 more)

### Community 19 - "Phone Number APIs (hfg-user-onboard)"
Cohesion: 0.13
Nodes (14): 1) Check Registered Phone, 2) Update Registered Phone, Error Responses, Latency Notes (Production), Ownership / Source, Phone Number APIs (hfg-user-onboard), Request, Request Body (+6 more)

### Community 20 - "Unified Public Tournament APIs"
Cohesion: 0.13
Nodes (14): Backend Files, Frontend Rules, Gamer Profile, Get Gamer Profile, Get Provisional Results, Get Tournament Detail, Get Unified Leaderboard, Leaderboard (+6 more)

### Community 21 - "delete_user_id"
Cohesion: 0.18
Nodes (13): _clear_deleted_user_caches(), delete_user_id(), _invalidate_fid_caches(), _is_valid_user_deletion_cron_request(), _purge_soft_deleted_user(), purge_soft_deleted_users(), Return records that must be retained instead of hard-deleted., Attach requested_fid to the existing user identified by email. Returns dict:… (+5 more)

### Community 22 - "_run_notification_dispatch_job"
Cohesion: 0.20
Nodes (11): _run_notification_dispatch_job(), _upsert_notification_failure(), gemini_agent(), generate_notification(), is_within_time_window(), main(), Check if current time is between 6:00 AM and 10:00 PM IST, run_notification_cycle() (+3 more)

### Community 23 - "_EmailText"
Cohesion: 0.20
Nodes (8): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., generate_referral_code(), send_email()

### Community 24 - "process_pending_community_payments"
Cohesion: 0.17
Nodes (13): _apply_provider_refund(), enqueue_community_payment_webhook(), _find_community_registration_for_provider_ids(), process_pending_community_payment_webhooks(), process_pending_community_payments(), process_pending_community_refunds(), Persist an already-authenticated provider event before acknowledging it., Reconcile durable Razorpay webhook events, including out-of-order delivery. (+5 more)

### Community 25 - "_refund_or_cancel_registration"
Cohesion: 0.48
Nodes (5): _refund_or_cancel_registration(), CommunityRegistrationRefundTests, patch, registration(), tournament()

### Community 27 - "security.py"
Cohesion: 0.20
Nodes (8): _build_auth_response_for_fid(), get_user_by_fid_auth(), Build the same payload contract as GET /users/fid/<fid>: {"user": ..., "token":…, auth_required(), encode_user(), - match_route_user: if True, ensure token user_id matches the user_id in the…, Encode a user ID using RSA public key PEM string. Returns a base64-encoded…, Fetch only fields required by /users/fid auth response. Returns already-…

### Community 28 - "upload_temporary_evidence"
Cohesion: 0.20
Nodes (11): _cloudinary_evidence_config(), _cloudinary_signature(), _configure_cloudinary_evidence(), create_temporary_evidence_upload(), _evidence_upload_access(), _is_cloudinary_evidence_asset(), purge_expired_community_evidence(), Issue a short-lived direct-upload signature; evidence bytes bypass Render. (+3 more)

### Community 29 - "_ensure_notification_tracking_tables"
Cohesion: 0.29
Nodes (9): cron_trigger_daily_notifications(), _ensure_notification_tracking_tables(), get_notification_dispatch_job(), _is_valid_cron_request(), list_notification_dispatch_failures(), notification_dispatch_failures_summary(), Shared-secret gate for cron endpoints. It fails closed when the secret is…, unblock_notification_dispatch_failure() (+1 more)

### Community 30 - "Community Host Tournament Management E2E"
Cohesion: 0.20
Nodes (9): 3. Participant and Check-in Management, 5A. Organizer Reputation, Community Host Tournament Management E2E, Error Handling, Frontend Rules, Host Roster, Lifecycle, Player Registration (+1 more)

### Community 31 - "3B. Match Operations"
Cohesion: 0.20
Nodes (10): 3B. Match Operations, Admin Referee Resolution, Captain Result Agreement, Dispute Chat Provisioning, Generate Schedule and Bracket, Host Result Proposal and 15-Minute Review, Operate a Match, Read Matches (+2 more)

### Community 33 - "PasswordManager"
Cohesion: 0.25
Nodes (4): declared_attr, PasswordManager, Generates credentials for the user and sends a notification email., generate_credentials()

### Community 34 - "Cloudinary Community Evidence Setup"
Cohesion: 0.22
Nodes (8): 1. Cloudinary Configuration, 2. Database Migration, 3. App Upload Flow, 4. Result and Dispute Usage, 5. Cleanup Cron, 6. Security Rules, 7. Troubleshooting, Cloudinary Community Evidence Setup

### Community 35 - "Community Tournament APIs (Frontend Handoff)"
Cohesion: 0.22
Nodes (8): Admin APIs, Community Tournament APIs (Frontend Handoff), Frontend Feature Scope, Frontend Validation Checklist, Review Dispute, Review Host Verification, Source Files, Status Values

### Community 36 - "tournament_matches"
Cohesion: 0.58
Nodes (8): events, map_veto_actions, match_disputes, match_participants, match_result_submissions, tournament_matches, tournament_seeds, teams

### Community 38 - "_result_contexts"
Cohesion: 0.25
Nodes (8): _dispute_initiator(), _evidence_previews(), Resolve registered evidence once, before the backend writes the room., Build immutable, UI-ready previews for the result that led to a dispute., Identify the person who opened the dispute without trusting client input., _result_contexts(), _submitter(), _team_name()

### Community 39 - "event_controller.py"
Cohesion: 0.48
Nodes (6): create_registration(), create_team(), get_event(), get_open_events(), get_results(), route

### Community 40 - "create_user"
Cohesion: 0.33
Nodes (6): create_user(), _find_existing_user_fid_by_email(), _merge_existing_user_by_email(), Merge signup payload into an existing user identified by email. Also updates…, _sanitize_signup_payload(), _validate_signup_payload()

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

### Community 54 - "5. Winners and Payouts"
Cohesion: 0.67
Nodes (3): 5. Winners and Payouts, Host Payout Tracker, Submit Winners

### Community 55 - "review_payout"
Cohesion: 0.67
Nodes (3): _apply_wallet_transaction(), Keep the wallet balance and its immutable transaction ledger in sync., review_payout()

## Knowledge Gaps
- **123 isolated node(s):** `BookingExtraService`, `EventStatus`, `MatchParticipant`, `TournamentSeed`, `community_audit_logs` (+118 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `User` connect `user_service.py` to `UserSignupApiTests`, `community_tournament_control_service.py`, `community_tournament_service.py`, `event_participation_controller.py`, `CommunityConflictError`, `user_controller.py`, `review_controller.py`, `community_dispute_chat_service.py`, `UserService`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `CommunityValidationError` connect `community_tournament_service.py` to `community_tournament_controller.py`, `payment_service.py`, `community_tournament_control_service.py`, `event_participation_controller.py`, `CommunityConflictError`, `CommunityEsportsOperationTests`, `community_dispute_chat_service.py`, `user_service.py`, `review_payout`, `process_pending_community_payments`, `upload_temporary_evidence`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `auth_required_self()` connect `community_tournament_controller.py` to `user_controller.py`, `review_controller.py`, `route`, `add_wallet_balance`, `delete_user_id`, `security.py`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `CommunityValidationError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityValidationError` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `CommunityConflictError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityConflictError` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `CommunityForbiddenError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityForbiddenError` has 33 INFERRED edges - model-reasoned connections that need verification._
- **What connects `BookingExtraService`, `EventStatus`, `MatchParticipant` to the rest of the system?**
  _123 weakly-connected nodes found - possible documentation gaps or missing edges._