"""
Login endpoints for the Hash website, called only by the website's server
(signed with services.web_gateway). They return exactly the same payloads as
the app endpoints (GET /api/users/fid/<fid>, POST /api/users), so the website
and the app share one account model, but the caller must prove the identity
with a Firebase ID token that is verified here with the Admin SDK, including
revocation, instead of passing a bare fid.
"""
import time

from firebase_admin import auth as firebase_auth
from flask import Blueprint, current_app, jsonify, request

from services.web_gateway import gateway_signed

web_gateway_bp = Blueprint("web_gateway", __name__)

MAX_AUTH_AGE_SECONDS = 15 * 60


class _AuthError(Exception):
    pass


def _verify_id_token(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 4096:
        raise _AuthError("id_token is required")
    try:
        claims = firebase_auth.verify_id_token(raw, check_revoked=True, clock_skew_seconds=10)
    except firebase_auth.RevokedIdTokenError:
        raise _AuthError("Session revoked")
    except firebase_auth.UserDisabledError:
        raise _AuthError("Account disabled")
    except Exception:
        raise _AuthError("Invalid id_token")
    auth_time = int(claims.get("auth_time") or 0)
    if time.time() - auth_time > MAX_AUTH_AGE_SECONDS:
        raise _AuthError("Sign-in is too old")
    return claims


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@web_gateway_bp.route("/web/auth/session", methods=["POST"])
@gateway_signed
def web_auth_session():
    from controllers.user_controller import _build_auth_response_for_fid

    data = _json_body()
    if data is None:
        return jsonify(message="A JSON object is required"), 400
    try:
        claims = _verify_id_token(data.get("id_token"))
    except _AuthError as error:
        return jsonify(message=str(error)), 401

    payload, token, err = _build_auth_response_for_fid(claims["uid"])
    if err == "User not found":
        response = jsonify(message="User not found", needs_signup=True)
        response.headers["Cache-Control"] = "no-store"
        return response, 404
    if not payload or not token:
        return jsonify(message="Internal server error"), 500
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@web_gateway_bp.route("/web/auth/signup", methods=["POST"])
@gateway_signed
def web_auth_signup():
    from controllers.user_controller import create_user

    data = _json_body()
    if data is None:
        return jsonify(message="A JSON object is required"), 400
    try:
        claims = _verify_id_token(data.get("id_token"))
    except _AuthError as error:
        return jsonify(message=str(error)), 401

    profile = data.get("profile")
    if not isinstance(profile, dict):
        return jsonify(message="profile is required"), 400
    profile = dict(profile)
    # Identity comes from the verified token, never from the request body.
    profile["fid"] = claims["uid"]
    contact = profile.get("contact") if isinstance(profile.get("contact"), dict) else {}
    electronic = contact.get("electronicAddress") if isinstance(contact.get("electronicAddress"), dict) else {}
    if claims.get("phone_number"):
        electronic["mobileNo"] = claims["phone_number"]
    if claims.get("email") and claims.get("email_verified") and not electronic.get("emailId"):
        electronic["emailId"] = claims["email"]
    contact["electronicAddress"] = electronic
    profile["contact"] = contact

    # Reuse the existing signup view unchanged (validation, referral, wallet,
    # cooldown and recovery rules all stay in one place).
    with current_app.test_request_context(
        "/api/users",
        method="POST",
        json=profile,
        headers={"X-Request-Id": request.headers.get("X-Request-Id", "")},
    ):
        return create_user()
