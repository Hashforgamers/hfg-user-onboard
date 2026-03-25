import random
import string
from flask import current_app
from flask_mail import Message
from db.extensions import mail
from services.email_template import build_hfg_email_html

def generate_referral_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

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
    msg.html = build_hfg_email_html(subject=subject, body_text=body)
    current_app.logger.info(f"msg: {msg}")
    mail.send(msg)
    current_app.logger.info(f"Mail Sent Succussfully")
    
