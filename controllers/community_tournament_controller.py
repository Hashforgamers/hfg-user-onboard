from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from services.community_tournament_service import (
    CommunityConflictError,
    CommunityForbiddenError,
    CommunityValidationError,
    cancel_registration,
    cancel_tournament,
    create_dispute,
    create_file_asset,
    create_tournament,
    get_tournament,
    host_program_config,
    list_admin_disputes,
    list_admin_host_verifications,
    list_admin_payouts,
    list_host_disputes,
    list_host_payouts,
    list_host_registrations,
    list_host_results,
    list_tournaments,
    manage_registration,
    my_tournaments,
    register_for_tournament,
    review_dispute,
    review_host_verification,
    review_payout,
    submit_host_verification,
    submit_match_result,
    submit_winners,
    update_tournament,
    verify_match_result,
)
from services.security import auth_required_self
from models.communityTournament import CommunityHostVerification


community_tournament_bp = Blueprint("community_tournaments", __name__, url_prefix="/api/v1/community")


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
    return jsonify(host_program_config()), 200


@community_tournament_bp.get("/tournaments")
def list_community_tournaments():
    try:
        return jsonify(list_tournaments(request.args)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>")
@auth_required_self(decrypt_user=True)
def get_community_tournament(tournament_id):
    try:
        return jsonify(get_tournament(tournament_id, g.auth_user_id)), 200
    except Exception as exc:
        return _handle_service_error(exc)


@community_tournament_bp.get("/tournaments/public/<uuid:tournament_id>")
def get_public_community_tournament(tournament_id):
    try:
        return jsonify(get_tournament(tournament_id)), 200
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
        registration = register_for_tournament(
            g.auth_user_id,
            tournament_id,
            payment_reference=(_body()).get("payment_reference"),
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


@community_tournament_bp.get("/tournaments/<uuid:tournament_id>/registrations")
@auth_required_self(decrypt_user=True)
def list_managed_community_registrations(tournament_id):
    try:
        return jsonify(list_host_registrations(g.auth_user_id, tournament_id, request.args)), 200
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
