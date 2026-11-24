# Graph Report - hfg-user-onboard  (2026-10-31)

## Corpus Check
- 124 files · ~77,700 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1186 nodes · 3374 edges · 83 communities (67 shown, 16 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 185 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `88df48b4`
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
- user_controller.py
- community_tournaments
- review_controller.py
- CommunityEsportsOperationTests
- User APIs
- route
- community_dispute_chat_service.py
- UserService
- extensions.py
- CommunityValidationError
- passModels.py
- app/__init__.py
- Phone Number APIs (hfg-user-onboard)
- Unified Public Tournament APIs
- DropCrateClaimTests
- _run_notification_dispatch_job
- _EmailText
- commit_community
- _refund_or_cancel_registration
- WalletCreditSecurityTests
- test_user_signup_api.py
- test_community_flow_pg.py
- test_notification_campaign.py
- Community Host Tournament Management E2E
- 3B. Match Operations
- User
- create_community_payment_attempt
- Cloudinary Community Evidence Setup
- Community Tournament APIs (Frontend Handoff)
- tournament_matches
- Exception
- drop-crate-claim.md
- notification-context.md
- 20261005_notification_context.sql
- _invalidate_user_microcache
- 2. Create and Edit a Tournament
- 3A. Esports Teams and Rosters
- 4. Results and Disputes
- Suggested Screen Flows
- Public APIs
- Community tournament flow upgrade — 30 October 2026
- 3C. Control Room and Communication
- community_player_flow_service.py
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
- _build_auth_response_for_fid
- _ensure_notification_tracking_tables
- Vendor
- 5. Winners and Payouts

## God Nodes (most connected - your core abstractions)
1. `CommunityValidationError` - 114 edges
2. `auth_required_self()` - 86 edges
3. `CommunityConflictError` - 78 edges
4. `_handle_service_error()` - 77 edges
5. `CommunityForbiddenError` - 58 edges
6. `commit_community()` - 54 edges
7. `_now()` - 52 edges
8. `_audit()` - 46 edges
9. `CommunityStorageError` - 36 edges
10. `_body()` - 32 edges

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

## Communities (83 total, 16 thin omitted)

### Community 0 - "community_tournament_controller.py"
Cohesion: 0.07
Nodes (109): after_request, accept_community_result_proposal(), admin_list_community_disputes(), admin_list_community_payouts(), admin_list_duplicate_payment_recoveries(), admin_list_host_verifications(), admin_list_pending_community_payments(), _admin_required() (+101 more)

### Community 1 - "payment_service.py"
Cohesion: 0.06
Nodes (57): Any, object, _amount_in_paise(), _as_dict(), create_payment_intent(), fetch_tournament_payment(), fetch_tournament_payment_for_order(), fetch_tournament_refund() (+49 more)

### Community 2 - "community_tournament_control_service.py"
Cohesion: 0.09
Nodes (42): CommunityMatchResultProposal, CommunityTournamentAnnouncement, CommunityTournamentDispute, CommunityTournamentTeam, eligible_memberships(), match_membership(), Shared community eligibility. Pending payments never grant play access., require_participant() (+34 more)

### Community 3 - "create_tournament"
Cohesion: 0.25
Nodes (14): require_publish_ready(), _banner_asset(), _bounded_int(), create_tournament(), _host_commission_rate(), _invite_code_hash(), _json_object(), _money() (+6 more)

### Community 4 - "event_participation_controller.py"
Cohesion: 0.10
Nodes (46): _body(), create_team(), _dispatch_push_async(), _event_flag(), force_remove_team_member(), get_team_members(), get_user_joined_tournaments(), get_user_teams() (+38 more)

### Community 5 - "community_tournament_service.py"
Cohesion: 0.07
Nodes (58): CommunityFileAsset, CommunityHostStatus, CommunityHostTier, CommunityHostVerification, CommunityTournament, CommunityTournamentRegistration, CommunityTournamentRegistrationStatus, CommunityTournamentStatus (+50 more)

### Community 6 - "tournament_engine_controller.py"
Cohesion: 0.08
Nodes (43): _event_flag(), get_event(), get_event_leaderboard(), get_event_provisional_results(), get_public_gamer_profile(), list_public_events(), _optional_request_user_id(), get (+35 more)

### Community 7 - "user_controller.py"
Cohesion: 0.09
Nodes (18): get_all_fcm(), get_user(), hash_coin_purchases(), _normalize_indian_phone(), Update (or create) user phone entry in contact_info. Production-safe checks: -…, register_fcm_token(), update_registered_phone(), user_purchase_pass() (+10 more)

### Community 8 - "community_tournaments"
Cohesion: 0.14
Nodes (24): community_audit_logs, community_file_assets, community_host_verifications, community_match_results, community_tournament_disputes, community_tournament_payouts, community_tournament_registrations, community_tournaments (+16 more)

### Community 9 - "review_controller.py"
Cohesion: 0.27
Nodes (16): _clean_text(), create_review(), edit_review(), _internal_authorized(), internal_list_reviews(), internal_respond_review(), internal_reviews_summary(), internal_update_review_status() (+8 more)

### Community 11 - "User APIs"
Cohesion: 0.08
Nodes (25): Admin Referee Result, Authenticated Tournament Detail, Cancel My Registration, Cancel Tournament, Captain-Submitted Result Alternative, Close Registration Early, Cloudinary Evidence Upload, Create Dispute (+17 more)

### Community 12 - "route"
Cohesion: 0.18
Nodes (24): get_extra_service(), get_extra_service_categories(), get_extra_service_menu_item(), get_extra_service_menus(), get_registered_phone_status(), get_user_available_passes_by_id(), get_user_hash_coins(), get_voucher_by_user() (+16 more)

### Community 13 - "community_dispute_chat_service.py"
Cohesion: 0.16
Nodes (21): CommunityMatchResultSubmission, match_team_ids(), _admin_user_ids(), CommunityDisputeChatError, _dispute_initiator(), _evidence_previews(), firebase_uid_for_user(), _match_details() (+13 more)

### Community 14 - "UserService"
Cohesion: 0.09
Nodes (15): declared_attr, PasswordManager, PhysicalAddress, Safely serialize physical address to dictionary with proper type handling, Idempotent finalization for post-signup side effects. Safe to run multiple…, Add physical address to user using relationship, Add contact info to user using relationship, Creates a new user and related entities in the database, with validations. (+7 more)

### Community 15 - "extensions.py"
Cohesion: 0.09
Nodes (11): BookingExtraService, ContactInfo, Safely serialize contact info to dictionary, DeletedUserCooldown, MatchParticipant, ReferralTracking, TournamentSeed, VerificationChecks (+3 more)

### Community 16 - "CommunityValidationError"
Cohesion: 0.18
Nodes (22): control_room(), create_manual_match(), host_results_overview(), list_announcements(), list_teams(), Operational result-tab payload for the tournament manager., _registration_for_user(), CommunityValidationError (+14 more)

### Community 17 - "passModels.py"
Cohesion: 0.12
Nodes (6): CafePass, PassRedemptionLog, PassType, Generate unique pass UID for hour-based passes, Validate pass configuration, UserPass

### Community 18 - "app/__init__.py"
Cohesion: 0.17
Nodes (10): Config, create_app(), notify_user(), Demo endpoint to create a notification + trigger FCM with invite-like payload.…, trigger_demo_notification(), load_key_from_file(), init_firebase(), Send an FCM notification and return structured status for async workers. (+2 more)

### Community 19 - "Phone Number APIs (hfg-user-onboard)"
Cohesion: 0.13
Nodes (14): 1) Check Registered Phone, 2) Update Registered Phone, Error Responses, Latency Notes (Production), Ownership / Source, Phone Number APIs (hfg-user-onboard), Request, Request Body (+6 more)

### Community 20 - "Unified Public Tournament APIs"
Cohesion: 0.14
Nodes (14): Backend Files, Frontend Rules, Gamer Profile, Get Gamer Profile, Get Provisional Results, Get Tournament Detail, Get Unified Leaderboard, Leaderboard (+6 more)

### Community 22 - "_run_notification_dispatch_job"
Cohesion: 0.16
Nodes (14): cron_trigger_daily_notifications(), preview_campaign_notification(), _run_notification_dispatch_job(), _upsert_notification_failure(), gemini_agent(), generate_notification(), is_within_time_window(), main() (+6 more)

### Community 23 - "_EmailText"
Cohesion: 0.20
Nodes (8): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., generate_referral_code(), send_email()

### Community 24 - "commit_community"
Cohesion: 0.12
Nodes (48): commit_community(), self_check_in(), _automatic_team_ready(), create_announcement(), create_team(), host_dashboard(), manage_team(), process_operational_deadlines() (+40 more)

### Community 25 - "_refund_or_cancel_registration"
Cohesion: 0.48
Nodes (5): _refund_or_cancel_registration(), CommunityRegistrationRefundTests, patch, registration(), tournament()

### Community 27 - "test_user_signup_api.py"
Cohesion: 0.13
Nodes (19): _clear_deleted_user_caches(), create_user(), delete_user_id(), _find_existing_user_fid_by_email(), _invalidate_fid_caches(), _is_valid_user_deletion_cron_request(), _merge_existing_user_by_email(), _purge_soft_deleted_user() (+11 more)

### Community 28 - "test_community_flow_pg.py"
Cohesion: 0.19
Nodes (15): FCMToken, app(), fixture, Run against a disposable PostgreSQL URL; each test uses an isolated schema., seed(), test_accepted_teammate_can_submit_legacy_result_and_review(), test_head_to_head_proposal_permission_tracks_pending_and_dispute(), test_http_player_routes_authorization_and_real_write_replay() (+7 more)

### Community 29 - "test_notification_campaign.py"
Cohesion: 0.53
Nodes (4): generator(), test_ai_failure_uses_configured_fallback(), test_invalid_ai_response_uses_configured_fallback(), test_saved_context_replaces_old_campaign()

### Community 30 - "Community Host Tournament Management E2E"
Cohesion: 0.22
Nodes (9): 3. Participant and Check-in Management, 5A. Organizer Reputation, Community Host Tournament Management E2E, Error Handling, Frontend Rules, Host Roster, Lifecycle, Player Registration (+1 more)

### Community 31 - "3B. Match Operations"
Cohesion: 0.20
Nodes (10): 3B. Match Operations, Admin Referee Resolution, Captain Result Agreement, Dispute Chat Provisioning, Generate Schedule and Bracket, Host Result Proposal and 15-Minute Review, Operate a Match, Read Matches (+2 more)

### Community 32 - "User"
Cohesion: 0.16
Nodes (4): Safely serialize user object to dictionary, User, patch, UserSignupApiTests

### Community 33 - "create_community_payment_attempt"
Cohesion: 0.29
Nodes (7): _bind_verified_payment_attempt(), create_community_payment_attempt(), _payment_attempt_receipt(), _payment_checkout_payload(), Keep the Razorpay receipt unique, stable, and within its 40-character limit., Create or reuse the one active Razorpay checkout for a registration. The public…, Attach a provider-verified payment to its registration exactly once.

### Community 34 - "Cloudinary Community Evidence Setup"
Cohesion: 0.22
Nodes (8): 1. Cloudinary Configuration, 2. Database Migration, 3. App Upload Flow, 4. Result and Dispute Usage, 5. Cleanup Cron, 6. Security Rules, 7. Troubleshooting, Cloudinary Community Evidence Setup

### Community 35 - "Community Tournament APIs (Frontend Handoff)"
Cohesion: 0.15
Nodes (13): Admin APIs, Community Tournament APIs (Frontend Handoff), Data Models, File Asset, Frontend Feature Scope, Frontend Validation Checklist, Host Verification, Registration (+5 more)

### Community 36 - "tournament_matches"
Cohesion: 0.58
Nodes (8): events, map_veto_actions, match_disputes, match_participants, match_result_submissions, tournament_matches, tournament_seeds, teams

### Community 37 - "Exception"
Cohesion: 0.17
Nodes (9): create_registration(), create_team(), get_event(), get_open_events(), get_results(), route, Exception, ProvisionalResults (+1 more)

### Community 41 - "_invalidate_user_microcache"
Cohesion: 0.16
Nodes (12): add_hash_coins(), add_wallet_balance(), claim_drop_crate(), create_voucher_for_referral_points(), _ensure_hash_wallet_row(), _invalidate_user_microcache(), mark_notification_read(), Example: Add hash coins to user and notify. { "amount": 500 } (+4 more)

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

### Community 47 - "Community tournament flow upgrade — 30 October 2026"
Cohesion: 0.17
Nodes (8): Changed behavior, Community tournament flow upgrade — 30 October 2026, Deployment and verification, Multi-team referee decision, New endpoints, Player screen bootstrap, Safe write retries, Team awards and finalization

### Community 48 - "3C. Control Room and Communication"
Cohesion: 0.40
Nodes (5): 3C. Control Room and Communication, Captured Payment Recovery and Duplicate Refunds, Host Registration Actions, Payment Retry Queue, Rules and Publish Readiness

### Community 49 - "community_player_flow_service.py"
Cohesion: 0.31
Nodes (9): eligible_participant(), check_in_blocker(), finalization_conditions(), my_matches(), my_tournament(), Player-facing aggregate reads and finalization previews for community UI., Team awards go to their confirmed captain's Hash wallet; never implicit splits., resolve_winner_payee() (+1 more)

### Community 50 - "1. Host Onboarding"
Cohesion: 0.50
Nodes (4): 1. Host Onboarding, Read Host Program, Read My Verification State, Submit or Resubmit Verification

### Community 51 - "6. Platform Admin Operations"
Cohesion: 0.50
Nodes (4): 6. Platform Admin Operations, Dispute Queue and Review, Payout Queue and Settlement, Review Host Verification

### Community 53 - "test_hash_coin_spend_pg.py"
Cohesion: 0.16
Nodes (17): parametrize, Atomic, priced HashCoin purchases; caller commits balance and ownership…, spend(), buy(), coins(), fixture, test_balance_and_receipt_rollback_together(), test_competing_purchases_do_not_overdraw() (+9 more)

### Community 54 - "HashCoin item purchases and app handoff"
Cohesion: 0.18
Nodes (9): 12 October update, Firebase team changes (not deployed or verified here), HashCoin item purchases and app handoff, Rollout, Spend contract, App behavior, Existing credit endpoint, HashCoin spend API (+1 more)

### Community 76 - "_build_auth_response_for_fid"
Cohesion: 0.33
Nodes (6): _build_auth_response_for_fid(), get_user_by_fid_auth(), Build the same payload contract as GET /users/fid/<fid>: {"user": ..., "token":…, encode_user(), Encode a user ID using RSA public key PEM string. Returns a base64-encoded…, Fetch only fields required by /users/fid auth response. Returns already-…

### Community 78 - "_ensure_notification_tracking_tables"
Cohesion: 0.43
Nodes (7): _ensure_notification_tracking_tables(), get_notification_dispatch_job(), _is_valid_cron_request(), list_notification_dispatch_failures(), notification_dispatch_failures_summary(), Shared-secret gate for cron endpoints. It fails closed when the secret is…, unblock_notification_dispatch_failure()

### Community 80 - "5. Winners and Payouts"
Cohesion: 0.67
Nodes (3): 5. Winners and Payouts, Host Payout Tracker, Submit Winners

## Knowledge Gaps
- **138 isolated node(s):** `BookingExtraService`, `EventStatus`, `MatchParticipant`, `TournamentSeed`, `community_audit_logs` (+133 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CommunityValidationError` connect `CommunityValidationError` to `community_tournament_controller.py`, `create_community_payment_attempt`, `community_tournament_control_service.py`, `create_tournament`, `event_participation_controller.py`, `community_tournament_service.py`, `User`, `payment_service.py`, `CommunityEsportsOperationTests`, `community_player_flow_service.py`, `commit_community`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `auth_required_self()` connect `community_tournament_controller.py` to `tournament_engine_controller.py`, `user_controller.py`, `review_controller.py`, `_invalidate_user_microcache`, `route`, `test_user_signup_api.py`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Why does `User` connect `User` to `community_tournament_control_service.py`, `event_participation_controller.py`, `community_tournament_service.py`, `user_controller.py`, `review_controller.py`, `community_dispute_chat_service.py`, `UserService`, `extensions.py`, `CommunityValidationError`, `test_user_signup_api.py`, `test_community_flow_pg.py`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `CommunityValidationError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityValidationError` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `CommunityConflictError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityConflictError` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `CommunityForbiddenError` (e.g. with `CommunityFileAsset` and `CommunityHostStatus`) actually correct?**
  _`CommunityForbiddenError` has 32 INFERRED edges - model-reasoned connections that need verification._
- **What connects `BookingExtraService`, `EventStatus`, `MatchParticipant` to the rest of the system?**
  _138 weakly-connected nodes found - possible documentation gaps or missing edges._