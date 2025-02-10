# app/utils.py

import string
import random
from flask_mail import Message
from db.extensions import mail
from flask import current_app
from datetime import datetime
import re
from flask import current_app


def generate_credentials(length=8):
    letters = string.ascii_letters
    digits = string.digits
    username = ''.join(random.choice(letters) for i in range(6))
    password = ''.join(random.choice(letters + digits) for i in range(length))
    return username, password

def send_email(subject, recipients, body):
    current_app.logger.info(f"subject: {subject}, recipients: {recipients}, body:{body}")
    msg = Message(subject, recipients=recipients)
    msg.body = body
    current_app.logger.info(f"msg: {msg}")
    mail.send(msg)
    current_app.logger.info(f"Mail Sent Succussfully")
    
