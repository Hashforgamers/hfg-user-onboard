"""
Request authentication for the Hash website gateway (hfg-new-landing-page).

The website's server (never the browser) signs every call to /api/web/* with
HMAC-SHA256 over a canonical string:

    METHOD \n PATH \n UNIX_TS \n NONCE \n sha256_hex(raw_body)

Headers: X-HFG-Gateway-Key, X-HFG-Gateway-Ts, X-HFG-Gateway-Nonce,
X-HFG-Gateway-Signature. Secrets come from WEB_GATEWAY_HMAC_SECRETS as
"keyid:secret[,keyid2:secret2]" so keys can be rotated without downtime.
Missing configuration fails closed (503).
"""
import functools
import hashlib
import hmac
import os
import threading
import time

from flask import current_app, jsonify, request

MAX_SKEW_SECONDS = 60
_NONCE_TTL_SECONDS = 2 * MAX_SKEW_SECONDS + 30
_NONCE_MAX = 50_000
_nonces = {}
_nonce_lock = threading.Lock()


def _secrets():
    raw = (current_app.config.get("WEB_GATEWAY_HMAC_SECRETS")
           or os.getenv("WEB_GATEWAY_HMAC_SECRETS") or "")
    out = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key_id, _, secret = entry.partition(":")
        if secret and len(secret) >= 32:
            out[key_id.strip()] = secret.strip()
    return out


def _claim_nonce(key):
    now = time.time()
    with _nonce_lock:
        if len(_nonces) > _NONCE_MAX:
            for k in [k for k, exp in _nonces.items() if exp <= now]:
                _nonces.pop(k, None)
        exp = _nonces.get(key)
        if exp and exp > now:
            return False
        _nonces[key] = now + _NONCE_TTL_SECONDS
        return True


def canonical_string(method, path, ts, nonce, body_bytes):
    return "\n".join([
        method.upper(),
        path,
        str(ts),
        nonce,
        hashlib.sha256(body_bytes or b"").hexdigest(),
    ])


def sign(secret, method, path, ts, nonce, body_bytes):
    return hmac.new(
        secret.encode(), canonical_string(method, path, ts, nonce, body_bytes).encode(), hashlib.sha256
    ).hexdigest()


def gateway_signed(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        secrets = _secrets()
        if not secrets:
            current_app.logger.error("WEB_GATEWAY_HMAC_SECRETS not configured; refusing web gateway call")
            return jsonify(message="Service unavailable"), 503

        key_id = (request.headers.get("X-HFG-Gateway-Key") or "").strip()
        ts_raw = (request.headers.get("X-HFG-Gateway-Ts") or "").strip()
        nonce = (request.headers.get("X-HFG-Gateway-Nonce") or "").strip()
        signature = (request.headers.get("X-HFG-Gateway-Signature") or "").strip().lower()
        secret = secrets.get(key_id)
        if not secret or not ts_raw.isdigit() or not (16 <= len(nonce) <= 64) or len(signature) != 64:
            return jsonify(message="Unauthorized"), 401
        if abs(time.time() - int(ts_raw)) > MAX_SKEW_SECONDS:
            return jsonify(message="Unauthorized"), 401

        expected = sign(secret, request.method, request.path, ts_raw, nonce, request.get_data(cache=True))
        if not hmac.compare_digest(expected, signature):
            current_app.logger.warning("web gateway signature mismatch key=%s", key_id)
            return jsonify(message="Unauthorized"), 401
        # Checked after the signature so unauthenticated callers can't burn nonces.
        if not _claim_nonce(f"{key_id}:{nonce}"):
            return jsonify(message="Duplicate request"), 409
        return fn(*args, **kwargs)

    return wrapper
