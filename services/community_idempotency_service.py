"""Atomic replay for database-only community mutations (PostgreSQL)."""

import hashlib
import json
from functools import wraps
from flask import g, has_request_context, jsonify, make_response, request
from sqlalchemy import text
from db.extensions import db


def commit_community(session=None):
    session = session if session is not None else db.session
    # Keyed writes and their replay record commit together, including nested services.
    if has_request_context() and getattr(g, "community_atomic_write", False):
        session.flush()
    else:
        session.commit()


def request_fingerprint(method, path, body):
    return hashlib.sha256(
        json.dumps([method, path, body], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def idempotent_community(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        key = request.headers.get("Idempotency-Key")
        if key is None:
            return fn(*args, **kwargs)
        if not key.strip() or len(key) > 128:
            return (
                jsonify(
                    error="validation_error",
                    message="Idempotency-Key must be 1-128 nonblank characters",
                ),
                400,
            )
        body = request.get_json(silent=True)
        if request.data and body is None:
            return (
                jsonify(
                    error="validation_error",
                    message="Idempotent writes require valid JSON",
                ),
                400,
            )
        scope = f"user:{g.auth_user_id}:{request.method}:{request.path}:{key}"
        scope_hash = hashlib.sha256(scope.encode()).hexdigest()
        fingerprint = request_fingerprint(request.method, request.path, body)
        lock_id = int.from_bytes(
            hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True
        )
        try:
            # A transaction-scoped cross-worker lock prevents simultaneous first writes.
            db.session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
            )
            existing = (
                db.session.execute(
                    text(
                        "SELECT fingerprint, response_body, response_status FROM community_api_idempotency WHERE scope_hash = :scope"
                    ),
                    {"scope": scope_hash},
                )
                .mappings()
                .first()
            )
            if existing:
                db.session.rollback()
                if existing["fingerprint"] != fingerprint:
                    return (
                        jsonify(
                            error="conflict",
                            message="Idempotency-Key was already used with a different payload",
                        ),
                        409,
                    )
                response = make_response(
                    jsonify(existing["response_body"]), existing["response_status"]
                )
                response.headers["Idempotency-Replayed"] = "true"
                return response
            g.community_atomic_write = True
            response = make_response(fn(*args, **kwargs))
            if response.status_code >= 400:
                db.session.rollback()
                return response
            result = response.get_json()
            db.session.execute(
                text(
                    """INSERT INTO community_api_idempotency
                (scope_hash, fingerprint, response_body, response_status)
                VALUES (:scope, :fingerprint, CAST(:body AS jsonb), :status)"""
                ),
                {
                    "scope": scope_hash,
                    "fingerprint": fingerprint,
                    "body": json.dumps(result),
                    "status": response.status_code,
                },
            )
            db.session.commit()
            return response
        except Exception as exc:
            db.session.rollback()
            from controllers.community_tournament_controller import (
                _handle_service_error,
            )

            return _handle_service_error(exc)
        finally:
            g.community_atomic_write = False

    return wrapped
