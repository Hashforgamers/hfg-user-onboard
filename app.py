from flask import Flask
from db.extensions import db
from controllers.user_controller import user_blueprint

app = Flask(__name__)

# Configurations for DB and Firebase
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['GOOGLE_APPLICATION_CREDENTIALS'] = 'path/to/firebase-admin-sdk.json'

db.init_app(app)

# Register blueprints
app.register_blueprint(user_blueprint)

if __name__ == '__main__':
    app.run(debug=True)
