"""Tests for the website gateway login endpoints (no DB / Firebase needed)."""
import hashlib
import hmac
import json
import secrets
import sys
import time
import types

import pytest
from flask import Flask, jsonify, request

SECRET = "s" * 40


# ---- stubs for firebase_admin.auth and the app's user controller ----------
class _Revoked(Exception):
    pass


class _Disabled(Exception):
    pass


TOKENS = {}


def _verify_id_token(token, check_revoked=False, clock_skew_seconds=0):
    assert check_revoked is True
    if token == "revoked":
        raise _Revoked()
    if token not in TOKENS:
        raise ValueError("bad token")
    return TOKENS[token]


fake_auth = types.SimpleNamespace(
    verify_id_token=_verify_id_token, RevokedIdTokenError=_Revoked, UserDisabledError=_Disabled
)
firebase_admin = types.ModuleType("firebase_admin")
firebase_admin.auth = fake_auth
sys.modules.setdefault("firebase_admin", firebase_admin)
sys.modules["firebase_admin"].auth = fake_auth

USERS = {"fid-1": {"id": 7, "name": "P"}}
SIGNUPS = []


def _build_auth_response_for_fid(fid, user_payload=None):
    user = USERS.get(fid)
    if not user:
        return None, None, "User not found"
    return {"user": user, "token": "jwt-for-%s" % user["id"]}, "jwt-for-%s" % user["id"], None


def create_user():
    SIGNUPS.append(request.get_json())
    return jsonify(message="created"), 201


uc = types.ModuleType("controllers.user_controller")
uc._build_auth_response_for_fid = _build_auth_response_for_fid
uc.create_user = create_user
sys.modules["controllers.user_controller"] = uc

from controllers.web_gateway_controller import web_gateway_bp  # noqa: E402
from services import web_gateway  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("WEB_GATEWAY_HMAC_SECRETS", "web-1:" + SECRET)
    web_gateway._nonces.clear()
    app = Flask(__name__)
    app.register_blueprint(web_gateway_bp, url_prefix="/api")
    return app.test_client()


def signed(client, path, body, *, secret=SECRET, ts=None, nonce=None, key="web-1", tamper=False):
    raw = json.dumps(body).encode()
    ts = str(ts or int(time.time()))
    nonce = nonce or secrets.token_urlsafe(16)
    canonical = "\n".join(["POST", path, ts, nonce, hashlib.sha256(raw).hexdigest()])
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    if tamper:
        raw = raw.replace(b"}", b',"x":1}')
    return client.post(path, data=raw, content_type="application/json", headers={
        "X-HFG-Gateway-Key": key, "X-HFG-Gateway-Ts": ts, "X-HFG-Gateway-Nonce": nonce, "X-HFG-Gateway-Signature": sig,
    })


def fresh(uid, **extra):
    token = "tok-" + secrets.token_hex(4)
    TOKENS[token] = {"uid": uid, "auth_time": int(time.time()) - 5, **extra}
    return token


def test_session_returns_app_payload(client):
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-1")})
    assert r.status_code == 200
    assert r.get_json() == {"user": {"id": 7, "name": "P"}, "token": "jwt-for-7"}
    assert r.headers["Cache-Control"] == "no-store"


def test_unknown_user_needs_signup(client):
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-new")})
    assert r.status_code == 404 and r.get_json()["needs_signup"] is True


def test_unsigned_request_rejected(client):
    r = client.post("/api/web/auth/session", json={"id_token": fresh("fid-1")})
    assert r.status_code == 401


def test_wrong_secret_rejected(client):
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-1")}, secret="x" * 40)
    assert r.status_code == 401


def test_tampered_body_rejected(client):
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-1")}, tamper=True)
    assert r.status_code == 401


def test_stale_timestamp_rejected(client):
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-1")}, ts=int(time.time()) - 600)
    assert r.status_code == 401


def test_replayed_nonce_rejected(client):
    token = fresh("fid-1")
    assert signed(client, "/api/web/auth/session", {"id_token": token}, nonce="n" * 22).status_code == 200
    assert signed(client, "/api/web/auth/session", {"id_token": token}, nonce="n" * 22).status_code == 409


def test_unconfigured_fails_closed(client, monkeypatch):
    monkeypatch.setenv("WEB_GATEWAY_HMAC_SECRETS", "")
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-1")})
    assert r.status_code == 503


def test_invalid_revoked_and_stale_tokens_rejected(client):
    assert signed(client, "/api/web/auth/session", {"id_token": "nope"}).status_code == 401
    assert signed(client, "/api/web/auth/session", {"id_token": "revoked"}).status_code == 401
    old = "tok-old"
    TOKENS[old] = {"uid": "fid-1", "auth_time": int(time.time()) - 3600}
    assert signed(client, "/api/web/auth/session", {"id_token": old}).status_code == 401


def test_signup_forces_identity_from_token(client):
    SIGNUPS.clear()
    token = fresh("fid-real", phone_number="+919999999999", email="a@b.co", email_verified=True)
    body = {
        "id_token": token,
        "profile": {
            "fid": "someone-elses-fid",
            "gameUserName": "gamer",
            "contact": {"electronicAddress": {"mobileNo": "+910000000000", "emailId": ""}},
        },
    }
    r = signed(client, "/api/web/auth/signup", body)
    assert r.status_code == 201
    sent = SIGNUPS[-1]
    assert sent["fid"] == "fid-real"
    assert sent["contact"]["electronicAddress"]["mobileNo"] == "+919999999999"
    assert sent["contact"]["electronicAddress"]["emailId"] == "a@b.co"


def test_key_rotation_accepts_secondary_key(client, monkeypatch):
    monkeypatch.setenv("WEB_GATEWAY_HMAC_SECRETS", "web-2:" + "n" * 40 + ",web-1:" + SECRET)
    r = signed(client, "/api/web/auth/session", {"id_token": fresh("fid-1")}, key="web-1")
    assert r.status_code == 200
