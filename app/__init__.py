from flask import Flask
from controllers.user_controller import user_blueprint
from controllers.event_public_controller import event_public_bp
from controllers.event_participation_controller import event_participation_bp
from db.extensions import db, migrate, mail
from .config import Config
from services.firebase_service import init_firebase
import logging
import os

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    app.register_blueprint(user_blueprint, url_prefix='/api')
    app.register_blueprint(event_public_bp)
    app.register_blueprint(event_participation_bp)

    # Set up Firebase inside app context
    with app.app_context():
        init_firebase()

    # Logging config
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    return app
