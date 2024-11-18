import logging
from flask import Flask
from controllers.user_controller import user_blueprint
from db.extensions import db
from .config import Config
import os

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    app.register_blueprint(user_blueprint, url_prefix='/api')  # Prefixing all routes with /api

    # Configure logging
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    return app
