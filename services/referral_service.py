# services/referral_service.py

from models.user import User
from models.voucher import Voucher
from db.extensions import db
import random
import string

def create_voucher_if_eligible(user_id, required_points=100):
    user = User.query.get(user_id)
    if not user:
        raise Exception("User not found")

    if user.referral_rewards < required_points:
        raise Exception("Not enough referral points to generate voucher")

    # Generate voucher code
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    voucher = Voucher(
        code=code,
        user_id=user.id,
        discount_percentage=100,
        is_active=True
    )

    # Deduct points
    user.referral_rewards -= required_points

    # Save both changes
    db.session.add(voucher)
    db.session.add(user)
    db.session.commit()

    return voucher
