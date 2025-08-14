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
from models.vendor import Vendor
from models.cafePass import CafePass
from models.passType import PassType
from models.transaction import Transaction
from models.userPass import UserPass
from models.extraServiceCategory import ExtraServiceCategory
from models.extraServiceMenu import ExtraServiceMenu
# Add this line to your existing imports at the top of the file
from models.extraServiceMenuImage import ExtraServiceMenuImage


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

    user = db.session.query(User).filter_by(id=user_id).with_for_update().first()

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
    data = request.get_json()
    cafe_pass_id = data.get("cafe_pass_id")
    payment_id = data.get("payment_id")  
    payment_mode = data.get("payment_mode", "online")  # online, wallet, etc.

    if not cafe_pass_id:
        return jsonify({"message": "cafe_pass_id is required"}), 400

    try:
        start_date = datetime.utcnow().date()
        cafe_pass = CafePass.query.filter_by(id=cafe_pass_id, is_active=True).first_or_404()
        valid_to = start_date + timedelta(days=cafe_pass.days_valid)

        # ✅ vendor_id can be None for Hash Pass
        vendor_id = cafe_pass.vendor_id  # will be None for global passes

        # Create user pass
        user_pass = UserPass(
            user_id=user_id,
            cafe_pass_id=cafe_pass_id,
            valid_from=start_date,
            valid_to=valid_to,
            is_active=True
        )
        db.session.add(user_pass)

        # Fetch user for transaction details
        user = User.query.filter_by(id=user_id).first()
        user_name = user.name if user else ""

        # Create transaction  
        transaction = Transaction(
            booking_id=None,  
            vendor_id=vendor_id,  # ✅ None if Hash Pass
            user_id=user_id,
            booked_date=start_date,
            booking_date=start_date,
            booking_time=datetime.utcnow().time(),
            user_name=user_name,
            amount=cafe_pass.price,
            original_amount=cafe_pass.price,
            discounted_amount=0.0,
            mode_of_payment=payment_mode,
            booking_type="pass_purchase",
            settlement_status="pending",
            reference_id=payment_id
        )
        db.session.add(transaction)

        db.session.commit()

        return jsonify({
            "message": "Pass purchased successfully",
            "pass_type": "hash" if vendor_id is None else "vendor",
            "vendor_id": vendor_id,
            "valid_from": start_date.isoformat(),
            "valid_to": valid_to.isoformat()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error purchasing pass for user {user_id}: {e}")
        return jsonify({
            "error": "Failed to complete pass purchase",
            "details": str(e)
        }), 500

@user_blueprint.route('/users/<int:user_id>/transactions', methods=['GET'])
def user_transaction_history(user_id):
    try:
        all_txns = []

        # 1. Normal Transactions from Transaction table
        transactions = Transaction.query.filter_by(user_id=user_id).all()
        for t in transactions:
            all_txns.append({
                "id": f"txn_{t.id}",
                "date": t.booking_date.isoformat(),
                "time": t.booking_time.strftime("%H:%M:%S"),
                "amount": t.amount,
                "type": t.booking_type,  # 'booking', 'pass_purchase', etc.
                "mode": t.mode_of_payment,
                "status": t.settlement_status,
                "reference_id": t.reference_id
            })

        # 2. Wallet Transactions from HashWalletTransaction table
        wallet_txns = HashWalletTransaction.query.filter_by(user_id=user_id).all()
        for w in wallet_txns:
            all_txns.append({
                "id": f"wallet_{w.id}",
                "date": w.timestamp.date().isoformat(),
                "time": w.timestamp.time().strftime("%H:%M:%S"),
                "amount": w.amount,
                "type": f"wallet_{'credit' if w.amount > 0 else 'debit'}",
                "reference_id": w.reference_id
            })

        # Sort all by date and time (newest first)
        all_txns.sort(key=lambda x: (x['date'], x['time']), reverse=True)

        return jsonify({"transactions": all_txns}), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching transactions for user {user_id}: {e}")
        return jsonify({"error": "Failed to fetch transaction history", "details": str(e)}), 500


@user_blueprint.route("/user/<int:user_id>/available_passes", methods=["GET"])
def user_available_passes(user_id):
    today = datetime.utcnow().date()
    pass_type_filter = request.args.get('type', None)  # 'vendor', 'hash', or None

    # --- Get all passes the user has ever purchased (active or expired) ---
    user_passes_all = db.session.query(UserPass.cafe_pass_id).filter(
        UserPass.user_id == user_id
    ).all()
    bought_pass_ids = set(row[0] for row in user_passes_all)

    # Standard available passes query
    available_passes_query = CafePass.query.filter(
        CafePass.is_active == True
    )

    # Apply type filter
    if pass_type_filter == 'vendor':
        available_passes_query = available_passes_query.filter(CafePass.vendor_id.isnot(None))
    elif pass_type_filter == 'hash':
        available_passes_query = available_passes_query.filter(CafePass.vendor_id.is_(None))

    available_passes = available_passes_query.all()

    # Build result with is_bought info
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
            "vendor_name": p.vendor.cafe_name if p.vendor else "Hash Pass",
            "is_bought": p.id in bought_pass_ids  # ✅ True if user ever bought this pass
        })

    return jsonify(result), 200


@user_blueprint.route("/user/<int:user_id>/all_passes", methods=["GET"])
def user_all_passes(user_id):
    today = datetime.utcnow().date()

    # User's active passes
    user_passes = db.session.query(UserPass).filter(
        UserPass.user_id == user_id,
        UserPass.is_active == True,
        UserPass.valid_to >= today
    ).all()
    user_pass_map = {up.cafe_pass_id: up for up in user_passes}

    # All active passes
    all_active_passes = CafePass.query.filter(CafePass.is_active == True).all()

    result = []
    for p in all_active_passes:
        up = user_pass_map.get(p.id)
        result.append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "days_valid": p.days_valid,
            "description": p.description,
            "pass_type": p.pass_type.name if p.pass_type else None,
            "vendor_id": p.vendor_id,
            "vendor_name": p.vendor.cafe_name if p.vendor else "Hash Pass",
            "already_purchased": bool(up)
        })
    return jsonify(result), 200

@user_blueprint.route("/user/<int:user_id>/passes", methods=["GET"])
def user_passes(user_id):
    today = datetime.utcnow().date()
    user_passes = UserPass.query.join(CafePass).filter(
        UserPass.user_id == user_id,
        UserPass.is_active == True,
        UserPass.valid_to >= today
    ).all()

    result = [{
        "id": up.id,
        "cafe_pass_id": up.cafe_pass_id,
        "cafe_pass_name": up.cafe_pass.name,
        "vendor_id": up.cafe_pass.vendor_id,
        "valid_from": up.valid_from.isoformat(),
        "valid_to": up.valid_to.isoformat(),
        "pass_type": up.cafe_pass.pass_type.name if up.cafe_pass.pass_type else None
    } for up in user_passes]

    return jsonify(result), 200

@user_blueprint.route("/user/<int:user_id>/passes/history", methods=["GET"])
def user_passes_history(user_id):
    today = datetime.utcnow().date()
    expired_passes = UserPass.query.join(CafePass).filter(
        UserPass.user_id == user_id,
        ((UserPass.valid_to < today) | (UserPass.is_active == False))
    ).all()

    result = [{
        "id": up.id,
        "cafe_pass_id": up.cafe_pass_id,
        "cafe_pass_name": up.cafe_pass.name,
        "vendor_id": up.cafe_pass.vendor_id,
        "valid_from": up.valid_from.isoformat(),
        "valid_to": up.valid_to.isoformat(),
        "pass_type": up.cafe_pass.pass_type.name if up.cafe_pass.pass_type else None,
        "is_active": up.is_active
    } for up in expired_passes]

    return jsonify(result), 200

@user_blueprint.route("/passes/<int:pass_id>", methods=["GET"])
def pass_details(pass_id):
    cafe_pass = CafePass.query.filter_by(id=pass_id, is_active=True).first()
    if not cafe_pass:
        return jsonify({"message": "Pass not found"}), 404

    result = {
        "id": cafe_pass.id,
        "name": cafe_pass.name,
        "price": cafe_pass.price,
        "days_valid": cafe_pass.days_valid,
        "description": cafe_pass.description,
        "pass_type": cafe_pass.pass_type.name if cafe_pass.pass_type else None,
        "vendor_id": cafe_pass.vendor_id,
        "vendor_name": cafe_pass.vendor.cafe_name if cafe_pass.vendor else "Hash Pass"
    }
    return jsonify(result), 200

@user_blueprint.route("/vendor/<int:vendor_id>/extras/categories", methods=["GET"])
def get_extra_service_categories(vendor_id):
    categories = ExtraServiceCategory.query.filter_by(
        vendor_id=vendor_id,
        is_active=True
    ).all()

    result = [{
        "id": cat.id,
        "name": cat.name,
        "description": cat.description
    } for cat in categories]

    return jsonify(result), 200

@user_blueprint.route("/vendor/<int:vendor_id>/extras/category/<int:category_id>/menus", methods=["GET"])
def get_extra_service_menus(vendor_id, category_id):
    # Confirm category belongs to this vendor and is active
    category = ExtraServiceCategory.query.filter_by(
        id=category_id,
        vendor_id=vendor_id,
        is_active=True
    ).first_or_404()

    menus = ExtraServiceMenu.query.filter_by(
        category_id=category.id,
        is_active=True
    ).all()

    result = [{
        "id": menu.id,
        "name": menu.name,
        "price": menu.price,
        "description": menu.description
    } for menu in menus]

    return jsonify(result), 200

@user_blueprint.route("/vendor/<int:vendor_id>/extras/category/<int:category_id>/menu/<int:menu_id>", methods=["GET"])
def get_extra_service_menu_item(vendor_id, category_id, menu_id):
    # Validate category belongs to vendor and active
    category = ExtraServiceCategory.query.filter_by(
        id=category_id,
        vendor_id=vendor_id,
        is_active=True
    ).first_or_404()

    menu = ExtraServiceMenu.query.filter_by(
        id=menu_id,
        category_id=category.id,
        is_active=True
    ).first_or_404()

    result = {
        "id": menu.id,
        "name": menu.name,
        "price": menu.price,
        "description": menu.description
    }

    return jsonify(result), 200


@user_blueprint.route("/vendor/<int:vendor_id>/extraService", methods=["GET"])
def get_extra_service(vendor_id):
    """
    Get all extra service categories with their menu items for a specific vendor
    Returns categories with nested menus including image URLs
    """
    try:
        categories = ExtraServiceCategory.query.filter_by(
            vendor_id=vendor_id,
            is_active=True
        ).all()

        result = []
        for category in categories:
            # Get active menu items for this category
            menus = ExtraServiceMenu.query.filter_by(
                category_id=category.id,
                is_active=True
            ).all()

            # Build menu items array with image URLs
            menu_items = []
            for menu in menus:
                # Get primary image or first available image
                image_url = None
                menu_images = ExtraServiceMenuImage.query.filter_by(
                    menu_id=menu.id,
                    is_active=True
                ).order_by(ExtraServiceMenuImage.is_primary.desc()).all()
                
                if menu_images:
                    image_url = menu_images[0].image_url

                menu_items.append({
                    "id": menu.id,
                    "name": menu.name,
                    "price": menu.price,
                    "description": menu.description,
                    "image_url": image_url
                })

            # Add category with its menus
            result.append({
                "id": category.id,
                "name": category.name,
                "description": category.description,
                "menus": menu_items
            })

        return jsonify({"categories": result}), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching extra services for vendor {vendor_id}: {str(e)}")
        return jsonify({"error": "Failed to fetch extra services", "details": str(e)}), 500
