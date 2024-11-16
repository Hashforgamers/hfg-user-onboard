from db.extensions import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    last_login = db.Column(db.DateTime)

    def __init__(self, email, name=None):
        self.email = email
        self.name = name
        self.last_login = datetime.utcnow()

    def update_last_login(self):
        self.last_login = datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'last_login': self.last_login
        }
