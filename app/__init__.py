from flask import Flask, g, make_response, request
from flask_cors import CORS
from controllers.user_controller import user_blueprint
from controllers.review_controller import review_blueprint
from controllers.event_public_controller import event_public_bp
from controllers.event_participation_controller import event_participation_bp
from db.extensions import db, migrate, mail
from .config import Config
from services.firebase_service import init_firebase
import logging
import os
import time
import uuid

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.json.sort_keys = False
    app.json.compact = True

    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=False,
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    app.register_blueprint(user_blueprint, url_prefix='/api')
    app.register_blueprint(review_blueprint, url_prefix='/api')
    app.register_blueprint(event_public_bp)
    app.register_blueprint(event_participation_bp)

    def _is_public_cacheable_path(path: str) -> bool:
        return (
            path.startswith("/api/users/fid/")
            or (path.startswith("/api/vendors/") and "/reviews" in path)
            or path.startswith("/api/events/public")
            or path.startswith("/api/events/") and (
                path.endswith("/leaderboard") or path.count("/") == 4
            )
        )

    @app.before_request
    def _start_request_timer():
        g.request_start_ts = time.perf_counter()
        incoming_request_id = (
            request.headers.get("X-Request-Id")
            or request.headers.get("X-Correlation-Id")
        )
        g.request_id = incoming_request_id or str(uuid.uuid4())

    # Set up Firebase inside app context
    with app.app_context():
        init_firebase()

    # Logging config
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    @app.after_request
    def _apply_response_hardening(response):
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Request-Id, X-Correlation-Id"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

        if app.config.get("API_ENABLE_TIMING_HEADERS", True):
            start_ts = getattr(g, "request_start_ts", None)
            if start_ts is not None:
                elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
                slow_ms = int(app.config.get("API_SLOW_REQUEST_MS", 120) or 120)
                if elapsed_ms >= slow_ms:
                    app.logger.warning(
                        "slow_request request_id=%s method=%s path=%s status=%s elapsed_ms=%.2f",
                        getattr(g, "request_id", "-"),
                        request.method,
                        request.path,
                        response.status_code,
                        elapsed_ms,
                    )

        if "Cache-Control" not in response.headers and request.method == "GET" and response.status_code == 200:
            has_auth_header = bool(request.headers.get("Authorization"))
            if not has_auth_header and _is_public_cacheable_path(request.path):
                response.headers["Cache-Control"] = app.config.get(
                    "API_PUBLIC_CACHE_CONTROL",
                    "public, max-age=15, stale-while-revalidate=30",
                )
            else:
                response.headers["Cache-Control"] = app.config.get("API_PRIVATE_CACHE_CONTROL", "no-store")
        return response

    @app.route("/api", methods=["OPTIONS"])
    @app.route("/api/<path:_path>", methods=["OPTIONS"])
    def api_preflight(_path=None):
        response = make_response("", 204)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Request-Id, X-Correlation-Id"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "86400"
        return response

    return app
