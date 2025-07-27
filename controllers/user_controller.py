from flask import request, jsonify, Blueprint, current_app
from services.user_service import UserService
from models.userHashCoin import UserHashCoin
from services.referral_service import create_voucher_if_eligible
from services.firebase_service import notify_user_all_tokens
from db.extensions import db
from models.hashWallet import HashWallet
from models.fcmToken import FCMToken
from models.user import User
from models.hashWalletTransaction import HashWalletTransaction
from services.firebase_service import send_notification
from models.cafePass import CafePass
from models.passType import PassType
from models.userPass import UserPass
from datetime import datetime, timedelta
from flask import jsonify

user_blueprint = Blueprint('user', __name__)

@user_blueprint.route("/notify-user", methods=["POST"])
def notify_user():
    token = request.json["token"]  # Lookup token in DB ideally
    title = request.json.get("title", "Notification")
    message = request.json.get("message", "You have a new message!")
    send_notification(token, title, message)
    return jsonify({"status": "Notification sent"})

@user_blueprint.route('/users', methods=['POST'])
def create_user():
    current_app.logger.debug(f"Started Processing User Onboard Request {request.json} ")
    data = request.json
    try:
        user = UserService.create_user(data)
        return jsonify({"message": "User created successfully", "user": user.to_dict()}), 201
    except Exception as e:
        return jsonify({"message": str(e)}), 400

@user_blueprint.route('/users/<int:user_id>/register-fcm-token', methods=['POST'])
def register_fcm_token(user_id):
    data = request.json
    token = data.get('token')
    platform = data.get('platform')

    if not token:
        return jsonify({'message': 'FCM token is required'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'message': 'User not found'}), 404

    existing = FCMToken.query.filter_by(token=token).first()
    if not existing:
        new_token = FCMToken(user_id=user.id, token=token, platform=platform)
        db.session.add(new_token)
        db.session.commit()
    else:
        existing.platform = platform
        db.session.commit()

    return jsonify({'message': 'FCM token registered'}), 200

@user_blueprint.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = UserService.get_user(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404

    return jsonify({"user": user.to_dict()})

@user_blueprint.route('/users/fid/<string:user_fid>', methods=['GET'])
def get_user_by_fid(user_fid):
    try:
        user = UserService.get_user_by_fid(user_fid)
        if not user:
            return jsonify({"message": "User not found"}), 404

        return jsonify({"user": user.to_dict()}), 200
    except Exception as e:
        current_app.logger.error(f"Internal error fetching user: {e}")
        return jsonify({"message": "Internal server error"}), 500

@user_blueprint.route('/users/<int:user_id>/create-voucher', methods=['POST'])
def create_voucher_for_referral_points(user_id):
    try:
        voucher = create_voucher_if_eligible(user_id)
        # --- FCM Notification on voucher creation ---
        user = User.query.get(user_id)
        if user:
            notify_user_all_tokens(
                user,
                "Voucher Created!",
                f"You have earned a voucher: {voucher.code} for {voucher.discount_percentage}% off! Check your rewards."
            )
        # ---
        return jsonify({
            "message": "Voucher created successfully",
            "voucher": {
                "code": voucher.code,
                "discount": voucher.discount_percentage
            }
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@user_blueprint.route('/users/<int:user_id>/voucher', methods=['GET'])
def get_voucher_by_user(user_id):
    try:
        vouchers = UserService.get_user_vouchers(user_id)
        return jsonify({
            "vouchers": [v.to_dict() for v in vouchers],
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@user_blueprint.route('/users/<int:user_id>/hash-coins', methods=['GET'])
def get_user_hash_coins(user_id):
    try:
        user_hash_coin = db.session.query(UserHashCoin).filter_by(user_id=user_id).first()

        if not user_hash_coin:
            return jsonify({
                "user_id": user_id,
                "hash_coins": 0,
                "message": "No hash coins found for this user"
            }), 200

        return jsonify({
            "user_id": user_id,
            "hash_coins": user_hash_coin.hash_coins
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@user_blueprint.route('/users/<int:user_id>/hash-coins', methods=['POST'])
def add_hash_coins(user_id):
    """
    Example: Add hash coins to user and notify.
    {
        "amount": 500
    }
    """
    data = request.json
    amount = data.get('amount')
    if not amount or not isinstance(amount, int) or amount <= 0:
        return jsonify({"message": "Amount must be a positive integer"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'message': 'User not found'}), 404

    try:
        user_hash_coin = db.session.query(UserHashCoin).filter_by(user_id=user_id).first()
        if not user_hash_coin:
            user_hash_coin = UserHashCoin(user_id=user_id, hash_coins=amount)
            db.session.add(user_hash_coin)
        else:
            user_hash_coin.hash_coins += amount

        db.session.commit()

        # --- FCM Notification on Hash Coins addition ---
        notify_user_all_tokens(
            user,
            "Congrats!",
            f"You have received {amount} Hash Coins. Total Hash Coins: {user_hash_coin.hash_coins}."
        )
        # ---
        return jsonify({
            "user_id": user_id,
            "new_hash_coins": user_hash_coin.hash_coins,
            "message": f"{amount} Hash Coins credited"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@user_blueprint.route('/users/<int:user_id>/wallet', methods=['GET'])
def get_wallet_balance(user_id):
    wallet = HashWallet.query.filter_by(user_id=user_id).first()
    if not wallet:
        return jsonify({"message": "Wallet not found"}), 404
    return jsonify({"user_id": wallet.user_id, "balance": wallet.balance})

@user_blueprint.route('/users/<int:user_id>/wallet', methods=['POST'])
def add_wallet_balance(user_id):
    data = request.json
    amount = data.get('amount')
    txn_type = data.get('type', 'top-up')  # default to 'top-up'
    reference_id = data.get('reference_id')

    if amount is None or not isinstance(amount, int) or amount <= 0:
        return jsonify({"message": "Amount must be a positive integer"}), 400

    wallet = HashWallet.query.filter_by(user_id=user_id).first()
    if not wallet:
        return jsonify({"message": "Wallet not found"}), 404

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404

    try:
        wallet.balance += amount

        txn = HashWalletTransaction(
            user_id=user_id,
            amount=amount,
            type=txn_type,
            reference_id=reference_id
        )

        db.session.add(txn)
        db.session.commit()

        # --- FCM Notification on wallet top-up/payment ---
        notify_user_all_tokens(
            user,
            "Payment Successful",
            f"Your wallet has been topped up with {amount} coins. New balance: {wallet.balance}."
        )
        # ---

        return jsonify({"message": "Wallet updated", "new_balance": wallet.balance})
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to update wallet", "error": str(e)}), 500

@user_blueprint.route("/user/<int:user_id>/purchase_pass", methods=["POST"])
def user_purchase_pass(user_id):
    data = request.json
    cafe_pass_id = data.get("cafe_pass_id")
    payment_id = data.get("payment_id")  # <-- extract payment_id from frontend/client

    if not cafe_pass_id:
        return jsonify({"message": "cafe_pass_id is required"}), 400

    try:
        start_date = datetime.utcnow().date()
        cafe_pass = CafePass.query.filter_by(id=cafe_pass_id, is_active=True).first_or_404()
        valid_to = start_date + timedelta(days=cafe_pass.days_valid)

        # Create UserPass record
        user_pass = UserPass(
            user_id=user_id,
            cafe_pass_id=cafe_pass_id,
            valid_from=start_date,
            valid_to=valid_to,
            is_active=True
        )
        db.session.add(user_pass)

        # Optionally, fetch user for user_name
        user = User.query.filter_by(id=user_id).first()
        user_name = user.name if user else ""

        # Create Transaction record for pass purchase
        transaction = Transaction(
            booking_id=None,  # No booking linked here
            vendor_id=cafe_pass.vendor_id,
            user_id=user_id,
            booked_date=start_date,
            booking_date=start_date,
            booking_time=datetime.utcnow().time(),
            user_name=user_name,
            amount=cafe_pass.price,
            original_amount=cafe_pass.price,
            discounted_amount=0.0,
            mode_of_payment=data.get("payment_mode", "online"),
            booking_type="pass_purchase",
            settlement_status="pending",
            reference_id=payment_id  # <-- save payment_id!
        )
        db.session.add(transaction)

        db.session.commit()
        return jsonify({"message": "Pass purchased", "valid_to": valid_to.isoformat()})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error purchasing pass for user {user_id}: {e}")
        return jsonify({"error": "Failed to complete pass purchase", "details": str(e)}), 500


@user_blueprint.route("/user/<int:user_id>/passes", methods=["GET"])
def list_user_passes(user_id):
    today = datetime.utcnow().date()
    passes = UserPass.query.join(CafePass).filter(
        UserPass.user_id==user_id,
        UserPass.is_active==True,
        UserPass.valid_to>=today
    ).all()
    return jsonify([
        {
            "id": up.id,
            "cafe_pass_id": up.cafe_pass_id,
            "cafe_pass_name": up.cafe_pass.name,
            "vendor_id": up.cafe_pass.vendor_id,
            "valid_from": up.valid_from.isoformat(),
            "valid_to": up.valid_to.isoformat(),
            "pass_type": up.cafe_pass.pass_type.name if up.cafe_pass.pass_type else None
        } for up in passes
    ])

@user_blueprint.route("/user/<int:user_id>/available_passes", methods=["GET"])
def user_available_passes(user_id):
    today = datetime.utcnow().date()

    # 1. Find all passes the user currently owns that are still valid and active
    active_user_passes = db.session.query(UserPass.cafe_pass_id)\
        .filter(
            UserPass.user_id == user_id,
            UserPass.is_active == True,
            UserPass.valid_to >= today
        ).all()
    owned_pass_ids = set([row[0] for row in active_user_passes])

    # 2. List all active passes (global and vendor) not already owned by user
    available_passes = CafePass.query \
        .filter(CafePass.is_active == True) \
        .filter(~CafePass.id.in_(owned_pass_ids)) \
        .all()

    # 3. Format response
    result = []
    for p in available_passes:
        result.append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "days_valid": p.days_valid,
            "description": p.description,
            "pass_type": p.pass_type.name if p.pass_type else None,
            "vendor_id": p.vendor_id,
            "vendor_name": p.vendor.cafe_name if p.vendor else "Hash Pass",  # Or leave null for platform pass
        })

    return jsonify(result), 200

