from functools import wraps
from threading import Lock
import time

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from services.community_tournament_service import (
    CommunityConflictError,
    CommunityForbiddenError,
    CommunityValidationError,
    cancel_registration,
    cancel_tournament,
    close_registration,
    create_dispute,
    create_file_asset,
    create_tournament,
    get_tournament,
    host_program_config,
    list_admin_disputes,
    list_admin_host_verifications,
    list_admin_payouts,
    list_pending_community_payments,
    list_host_disputes,
    list_host_payouts,
    list_host_registrations,
    list_host_results,
    list_tournaments,
    manage_registration,
    my_tournaments,
    register_for_tournament,
    process_pending_community_payments,
    review_dispute,
    review_host_verification,
    review_payout,
    submit_host_verification,
    submit_match_result,
    submit_winners,
    update_tournament,
    verify_match_result,
)
from services.community_tournament_control_service import (
    admin_resolve_match_result,
    control_room,
    create_announcement,
    create_manual_match,
    create_result_proposal,
    create_team,
    create_tournament_review,
    generate_matches,
    host_dashboard,
    list_announcements,
    list_audit_log,
    list_matches,
    list_private_matches,
    list_teams,
    leaderboard,
    manage_match,
    manage_team,
    replace_team_roster,
    public_host_profile,
    process_operational_deadlines,
    rule_template,
    respond_team_invitation,
    accept_result_proposal,
    dispute_result_proposal,
    start_tournament,
    submit_captain_result,
    tournament_readiness,
)
from services.security import auth_required_self
from models.communityTournament import CommunityHostVerification


community_tournament_bp = Blueprint("community_tournaments", __name__, url_prefix="/api/v1/community")

_COMMUNITY_PUBLIC_CACHE = {}
_COMMUNITY_PUBLIC_CACHE_LOCK = Lock()


def _community_cache_response(namespace, producer, ttl_sec=None, authenticated_user_id=None):
    """Cache public or user-scoped read payloads briefly; writes invalidate it."""
    if request.args.get("invite_code"):
        return jsonify(producer())
    if request.headers.get("Authorization") and authenticated_user_id is None:
        return jsonify(producer())
    ttl = int(
        current_app.config.get("COMMUNITY_PUBLIC_CACHE_TTL_SEC", 5)
        if ttl_sec is None else ttl_sec
    )
    if ttl <= 0:
        return jsonify(producer())
    scope = f"user:{int(authenticated_user_id)}" if authenticated_user_id is not None else "public"
    key = f"{scope}:{namespace}:{request.full_path}"
    now = time.monotonic()
    with _COMMUNITY_PUBLIC_CACHE_LOCK:
        cached = _COMMUNITY_PUBLIC_CACHE.get(key)
        if cached and cached["expires_at"] > now:
            return jsonify(cached["payload"])
    payload = producer()
    with _COMMUNITY_PUBLIC_CACHE_LOCK:
        if len(_COMMUNITY_PUBLIC_CACHE) >= int(current_app.config.get("API_MICROCACHE_MAX_ITEMS", 50000)):
            _COMMUNITY_PUBLIC_CACHE.pop(next(iter(_COMMUNITY_PUBLIC_CACHE)), None)
        _COMMUNITY_PUBLIC_CACHE[key] = {"payload": payload, "expires_at": now + ttl}
    return jsonify(payload)


def _community_public_cache_response(namespace, producer, ttl_sec=None):
    return _community_cache_response(namespace, producer, ttl_sec)


@community_tournament_bp.after_request
def _invalidate_community_public_cache_after_write(response):
    if request.method != "GET" and response.status_code < 400:
        with _COMMUNITY_PUBLIC_CACHE_LOCK:
            _COMMUNITY_PUBLIC_CACHE.clear()
    return response


def _body():
    return request.get_json(silent=True) or {}


def _error(message, status=400, code=None):
    return jsonify({"error": code or "bad_request", "message": message}), status


def _admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        configured = current_app.config.get("COMMUNITY_ADMIN_TOKEN")
        provided = request.headers.get("X-Admin-Token")
        if not configured or provided != configured:
            return _error("Admin authorization required", 403, "forbidden")
        try:
            g.admin_id = int(request.headers.get("X-Admin-Id") or 0) or None
        except ValueError:
            g.admin_id = None
        return fn(*args, **kwargs)
    return wrapper


def _payment_cron_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        configured = current_app.config.get("COMMUNITY_PAYMENT_CRON_TOKEN")
        provided = request.headers.get("X-Community-Payment-Cron-Token")
        if not configured or provided != configured:
            return _error("Payment cron authorization required", 403, "forbidden")
        return fn(*args, **kwargs)
    return wrapper


def _handle_service_error(exc):
    if isinstance(exc, CommunityForbiddenError):
        return _error(str(exc), 403, "forbidden")
    if isinstance(exc, CommunityConflictError):
        return _error(str(exc), 409, "conflict")
    if isinstance(exc, CommunityValidationError):
        return _error(str(exc), 400, "validation_error")
    if isinstance(exc, SQLAlchemyError):
        current_app.logger.exception("community tournament database error")
        return _error("Database error", 500, "database_error")
    current_app.logger.exception("community tournament error")
    return _error("Internal server error", 500, "internal_error")


@community_tournament_bp.get("/health")
def community_health():
    return jsonify({"ok": True, "module": "community_tournaments", "version": "v1"}), 200


@community_tournament_bp.get("/hosts/program")
def get_host_program():
    return _community_public_cache_response("host-program", host_program_config), 200


@community_tournament_bp.get("/tournaments")
def list_community_tournaments():
    try:
        return _community_public_cache_response("tournaments", lambda: list_tournaments(request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>")
@auth_required_self(decrypt_user=True)
def get_community_tournament(tournament_id):
    try:
        return jsonify(get_tournament(tournament_id, g.auth_user_id, request.args.get("invite_code"))), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/public/<uuid:tournament_id>")
def get_public_community_tournament(tournament_id):
    try:
        return _community_public_cache_response(
            f"tournament:{tournament_id}",
            lambda: get_tournament(tournament_id, invite_code=request.args.get("invite_code")),
        ), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/public/<uuid:tournament_id>/status")
def get_public_community_tournament_status(tournament_id):
    try:
        def payload():
            tournament = get_tournament(tournament_id, invite_code=request.args.get("invite_code"))
            return {
                "id": tournament["id"],
                "title": tournament["title"],
                "status": tournament["status"],
                "registration_start_at": tournament["registration_start_at"],
                "registration_end_at": tournament["registration_end_at"],
                "tournament_start_at": tournament["tournament_start_at"],
                "tournament_end_at": tournament["tournament_end_at"],
                "registered_players_count": tournament["registered_players_count"],
                "max_players": tournament["max_players"],
            }
        return _community_public_cache_response(
            f"tournament-status:{tournament_id}",
            payload,
            current_app.config.get("COMMUNITY_PUBLIC_STATUS_CACHE_TTL_SEC", 2),
        ), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/hosts/verification")
@auth_required_self(decrypt_user=True)
def submit_host_verification_request():
    try:
        verification = submit_host_verification(g.auth_user_id, _body())
        return jsonify(verification.to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/hosts/me/verification")
@auth_required_self(decrypt_user=True)
def get_my_host_verification():
    verification = CommunityHostVerification.query.filter_by(user_id=g.auth_user_id).first()
    return jsonify(verification.to_dict() if verification else None), 200


@community_tournament_bp.patch("/admin/hosts/<uuid:verification_id>/verification")
@_admin_required
def admin_review_host_verification(verification_id):
    try:
        verification = review_host_verification(verification_id, _body(), g.admin_id)
        return jsonify(verification.to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/admin/hosts/verifications")
@_admin_required
def admin_list_host_verifications():
    try:
        return jsonify(list_admin_host_verifications(request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments")
@auth_required_self(decrypt_user=True)
def create_community_tournament():
    try:
        tournament = create_tournament(g.auth_user_id, _body())
        return jsonify(tournament.to_dict(include_room_details=True)), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/tournaments/<uuid:tournament_id>")
@auth_required_self(decrypt_user=True)
def update_community_tournament(tournament_id):
    try:
        tournament = update_tournament(g.auth_user_id, tournament_id, _body())
        return jsonify(tournament.to_dict(include_room_details=True)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/cancel")
@auth_required_self(decrypt_user=True)
def cancel_community_tournament(tournament_id):
    try:
        tournament = cancel_tournament(g.auth_user_id, tournament_id, (_body()).get("reason"))
        return jsonify(tournament.to_dict(include_room_details=True)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/me/tournaments")
@auth_required_self(decrypt_user=True)
def list_my_community_tournaments():
    role = (request.args.get("role") or "joined").strip().lower()
    if role not in {"joined", "hosted"}:
        return _error("role must be joined or hosted", 400, "validation_error")
    try:
        return jsonify({"items": my_tournaments(g.auth_user_id, role)}), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/registrations")
@auth_required_self(decrypt_user=True)
def register_community_tournament(tournament_id):
    try:
        body = _body()
        registration = register_for_tournament(
            g.auth_user_id,
            tournament_id,
            payment_reference=body.get("payment_reference") or body.get("razorpay_payment_id"),
            payment_order_id=body.get("razorpay_order_id") or body.get("payment_order_id"),
            invite_code=body.get("invite_code"),
        )
        return jsonify(registration.to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.delete("/tournaments/<uuid:tournament_id>/registrations/me")
@auth_required_self(decrypt_user=True)
def cancel_my_community_registration(tournament_id):
    try:
        registration = cancel_registration(g.auth_user_id, tournament_id)
        return jsonify(registration.to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/registrations/close")
@auth_required_self(decrypt_user=True)
def close_community_tournament_registration(tournament_id):
    try:
        tournament = close_registration(g.auth_user_id, tournament_id)
        return jsonify(tournament.to_dict(include_room_details=True)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/start")
@auth_required_self(decrypt_user=True)
def start_community_tournament(tournament_id):
    try:
        tournament = start_tournament(g.auth_user_id, tournament_id)
        return jsonify(tournament.to_dict(include_room_details=True)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/registrations")
@auth_required_self(decrypt_user=True)
def list_managed_community_registrations(tournament_id):
    try:
        return jsonify(list_host_registrations(g.auth_user_id, tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/admin/payments/pending")
@_admin_required
def admin_list_pending_community_payments():
    try:
        return jsonify(list_pending_community_payments(request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/internal/payments/process-pending")
@_payment_cron_required
def process_pending_community_payment_queue():
    try:
        return jsonify(process_pending_community_payments((_body()).get("limit", 50))), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/tournaments/<uuid:tournament_id>/registrations/<uuid:registration_id>")
@auth_required_self(decrypt_user=True)
def manage_community_registration(tournament_id, registration_id):
    try:
        return jsonify(manage_registration(g.auth_user_id, tournament_id, registration_id, _body())), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/results")
@auth_required_self(decrypt_user=True)
def submit_community_result(tournament_id):
    try:
        result = submit_match_result(g.auth_user_id, tournament_id, _body())
        return jsonify(result.to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/tournaments/<uuid:tournament_id>/results/<uuid:result_id>")
@auth_required_self(decrypt_user=True)
def verify_community_result(tournament_id, result_id):
    try:
        result = verify_match_result(g.auth_user_id, tournament_id, result_id, _body())
        return jsonify(result.to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/results")
@auth_required_self(decrypt_user=True)
def list_managed_community_results(tournament_id):
    try:
        return jsonify(list_host_results(g.auth_user_id, tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/winners")
@auth_required_self(decrypt_user=True)
def submit_community_winners(tournament_id):
    try:
        payouts = submit_winners(g.auth_user_id, tournament_id, (_body()).get("winners") or [])
        return jsonify({"items": [payout.to_dict() for payout in payouts]}), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/payouts")
@auth_required_self(decrypt_user=True)
def list_managed_community_payouts(tournament_id):
    try:
        return jsonify(list_host_payouts(g.auth_user_id, tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/disputes")
@auth_required_self(decrypt_user=True)
def create_community_dispute(tournament_id):
    try:
        dispute = create_dispute(g.auth_user_id, tournament_id, _body())
        return jsonify(dispute.to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/disputes")
@auth_required_self(decrypt_user=True)
def list_managed_community_disputes(tournament_id):
    try:
        return jsonify(list_host_disputes(g.auth_user_id, tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/admin/disputes/<uuid:dispute_id>")
@_admin_required
def admin_review_community_dispute(dispute_id):
    try:
        dispute = review_dispute(dispute_id, _body(), g.admin_id)
        return jsonify(dispute.to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/admin/tournaments/<uuid:tournament_id>/disputes")
@_admin_required
def admin_list_community_disputes(tournament_id):
    try:
        return jsonify(list_admin_disputes(tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/admin/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/resolve-result")
@_admin_required
def admin_resolve_community_match_result(tournament_id, match_id):
    if not g.admin_id:
        return _error("X-Admin-Id is required for an admin result", 400, "validation_error")
    try:
        return jsonify(admin_resolve_match_result(g.admin_id, tournament_id, match_id, _body())), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/admin/tournaments/<uuid:tournament_id>/payouts")
@_admin_required
def admin_list_community_payouts(tournament_id):
    try:
        return jsonify(list_admin_payouts(tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/admin/tournaments/<uuid:tournament_id>/payouts/<uuid:payout_id>")
@_admin_required
def admin_review_community_payout(tournament_id, payout_id):
    try:
        payout = review_payout(tournament_id, payout_id, _body(), g.admin_id)
        return jsonify(payout.to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/files")
@auth_required_self(decrypt_user=True)
def create_community_file_asset():
    try:
        asset = create_file_asset(g.auth_user_id, _body())
        return jsonify(asset.to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/hosts/me/dashboard")
@auth_required_self(decrypt_user=True)
def get_community_host_dashboard():
    try:
        return jsonify(host_dashboard(g.auth_user_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/control-room")
@auth_required_self(decrypt_user=True)
def get_community_control_room(tournament_id):
    try:
        return jsonify(control_room(g.auth_user_id, tournament_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/teams")
@auth_required_self(decrypt_user=True)
def create_community_team(tournament_id):
    try:
        return jsonify(create_team(g.auth_user_id, tournament_id, _body())), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.put("/tournaments/<uuid:tournament_id>/teams/<uuid:team_id>/roster")
@auth_required_self(decrypt_user=True)
def replace_community_team_roster(tournament_id, team_id):
    try:
        return jsonify(replace_team_roster(g.auth_user_id, tournament_id, team_id, _body())), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/teams/<uuid:team_id>/invitation")
@auth_required_self(decrypt_user=True)
def respond_community_team_invitation(tournament_id, team_id):
    try:
        return jsonify(respond_team_invitation(g.auth_user_id, tournament_id, team_id, _body())), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/teams")
@auth_required_self(decrypt_user=True)
def list_community_teams(tournament_id):
    try:
        return jsonify(list_teams(tournament_id, request.args, g.auth_user_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/public/<uuid:tournament_id>/teams")
def list_public_community_teams(tournament_id):
    try:
        return _community_public_cache_response(
            f"teams:{tournament_id}",
            lambda: list_teams(tournament_id, request.args),
        ), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/tournaments/<uuid:tournament_id>/teams/<uuid:team_id>")
@auth_required_self(decrypt_user=True)
def manage_community_team(tournament_id, team_id):
    try:
        return jsonify(manage_team(g.auth_user_id, tournament_id, team_id, _body())), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/matches/generate")
@auth_required_self(decrypt_user=True)
def generate_community_matches(tournament_id):
    try:
        return jsonify(generate_matches(g.auth_user_id, tournament_id)), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/matches")
@auth_required_self(decrypt_user=True)
def create_manual_community_match(tournament_id):
    try:
        return jsonify(create_manual_match(g.auth_user_id, tournament_id, _body())), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/matches")
def list_community_matches(tournament_id):
    try:
        return _community_public_cache_response(
            f"matches:{tournament_id}",
            lambda: list_matches(tournament_id, request.args),
        ), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/matches/private")
@auth_required_self(decrypt_user=True)
def list_private_community_matches(tournament_id):
    try:
        return _community_cache_response(
            f"private-matches:{tournament_id}",
            lambda: list_private_matches(g.auth_user_id, tournament_id, request.args),
            ttl_sec=2,
            authenticated_user_id=g.auth_user_id,
        ), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/leaderboard")
def get_community_leaderboard(tournament_id):
    try:
        return _community_public_cache_response(
            f"leaderboard:{tournament_id}",
            lambda: leaderboard(tournament_id, request.args.get("invite_code")),
        ), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.patch("/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>")
@auth_required_self(decrypt_user=True)
def manage_community_match(tournament_id, match_id):
    try:
        return jsonify(manage_match(g.auth_user_id, tournament_id, match_id, _body())), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result-proposals")
@auth_required_self(decrypt_user=True)
def create_community_result_proposal(tournament_id, match_id):
    try:
        return jsonify(create_result_proposal(g.auth_user_id, tournament_id, match_id, _body()).to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result-proposals/<uuid:proposal_id>/accept")
@auth_required_self(decrypt_user=True)
def accept_community_result_proposal(tournament_id, match_id, proposal_id):
    try:
        return jsonify(accept_result_proposal(g.auth_user_id, tournament_id, match_id, proposal_id).to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result-proposals/<uuid:proposal_id>/dispute")
@auth_required_self(decrypt_user=True)
def dispute_community_result_proposal(tournament_id, match_id, proposal_id):
    try:
        return jsonify(dispute_result_proposal(g.auth_user_id, tournament_id, match_id, proposal_id, _body()).to_dict()), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result-submissions")
@auth_required_self(decrypt_user=True)
def submit_community_captain_result(tournament_id, match_id):
    try:
        return jsonify(submit_captain_result(g.auth_user_id, tournament_id, match_id, _body())), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/announcements")
@auth_required_self(decrypt_user=True)
def create_community_announcement(tournament_id):
    try:
        return jsonify(create_announcement(g.auth_user_id, tournament_id, _body()).to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/announcements")
@auth_required_self(decrypt_user=True)
def list_community_announcements(tournament_id):
    try:
        return jsonify(list_announcements(tournament_id, g.auth_user_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/audit-log")
@auth_required_self(decrypt_user=True)
def list_community_audit_log(tournament_id):
    try:
        return jsonify(list_audit_log(g.auth_user_id, tournament_id, request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/rules/template")
def get_community_rule_template():
    return _community_public_cache_response(
        "rule-template",
        lambda: rule_template(request.args.get("game")),
        60,
    ), 200


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/readiness")
@auth_required_self(decrypt_user=True)
def get_community_tournament_readiness(tournament_id):
    try:
        return jsonify(tournament_readiness(g.auth_user_id, tournament_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/tournaments/<uuid:tournament_id>/reviews")
@auth_required_self(decrypt_user=True)
def create_community_tournament_review(tournament_id):
    try:
        return jsonify(create_tournament_review(g.auth_user_id, tournament_id, _body()).to_dict()), 201
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/hosts/<int:host_user_id>/profile")
def get_public_community_host_profile(host_user_id):
    try:
        return jsonify(public_host_profile(host_user_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.post("/internal/operations/process-deadlines")
@_payment_cron_required
def process_community_operational_deadlines():
    try:
        return jsonify(process_operational_deadlines((_body()).get("limit", 50))), 200
    except Exception as exc:
        return _handle_service_error(exc)
