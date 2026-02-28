from flask import request, jsonify, Blueprint, current_app, g
from sqlalchemy import text
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
from models.paymentTransactionMapping import PaymentTransactionMapping
from models.physicalAddress import PhysicalAddress
from models.contactInfo import ContactInfo
from models.deletedUserCoolDownPeriod import DeletedUserCooldown
from models.team import Team
from models.teamMember import TeamMember
from models.referralTracking import ReferralTracking
from models.notification import Notification

from models.voucher import Voucher

from services.security import encode_user, auth_required_self

import jwt

from datetime import datetime, timedelta
import time
import uuid

user_blueprint = Blueprint('user', __name__)
_USER_FID_CACHE = {}
_USER_FID_CACHE_MAX_SIZE = 10000
_USER_CACHE = {}
_USER_CACHE_MAX_SIZE = 10000
_USER_SEARCH_CACHE = {}
_USER_SEARCH_CACHE_MAX_SIZE = 20000

@user_blueprint.route("/notify-user", methods=["POST"])
def notify_user():
    token = request.json["token"]  # Lookup token in DB ideally
    title = request.json.get("title", "Notification")
    message = request.json.get("message", "You have a new message!")
    send_notification(token, title, message)
    return jsonify({"status": "Notification sent"})

@user_blueprint.route('/users', methods=['POST'])
def create_user():
    data = request.get_json(silent=True) or {}
    required_fields = ("fid", "gameUserName")
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        return jsonify({
            "message": "Validation error",
            "details": f"Missing required fields: {', '.join(missing)}"
        }), 400

    try:
        current_app.logger.info("Create user request started for fid=%s", data.get("fid"))
        result = UserService.create_user(data)

        if isinstance(result, dict) and result.get('status') == 'error':
            state = result.get("state")
            status_code = 409 if state in {"USER_EXISTS", "EMAIL_EXISTS", "USERNAME_TAKEN"} else 400
            return jsonify(result), status_code

        if len(_USER_CACHE) >= _USER_CACHE_MAX_SIZE:
            _USER_CACHE.pop(next(iter(_USER_CACHE)))
        _USER_CACHE[result.id] = {
            "payload": result.to_dict(),
            "expires_at": time.time() + int(current_app.config.get("USER_CACHE_TTL_SEC", 15)),
        }

        return jsonify({"message": "User created successfully", "user": result.to_dict()}), 201
    except Exception:
        current_app.logger.exception("Create user failed for fid=%s", data.get("fid"))
        return jsonify({"message": "Internal server error"}), 500


@user_blueprint.route('/users/register-fcm-token', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def register_fcm_token():
    user_id = g.auth_user_id
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or "").strip()
    platform = (data.get('platform') or "").strip().lower() or "unknown"
    allowed_platforms = {"android", "ios", "web", "unknown"}

    if not token:
        return jsonify({'message': 'FCM token is required'}), 400
    if len(token) > 512:
        return jsonify({'message': 'FCM token is too long'}), 400
    if platform not in allowed_platforms:
        return jsonify({'message': 'Invalid platform'}), 400

    try:
        db.session.execute(text("""
            INSERT INTO fcm_tokens (user_id, token, platform, created_at)
            VALUES (:user_id, :token, :platform, NOW())
            ON CONFLICT (token)
            DO UPDATE SET
                user_id = EXCLUDED.user_id,
                platform = EXCLUDED.platform
        """), {"user_id": user_id, "token": token, "platform": platform})
        db.session.commit()
        return jsonify({'message': 'FCM token registered'}), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to register FCM token for user_id=%s", user_id)
        return jsonify({"message": "Internal server error"}), 500

@user_blueprint.route('/users', methods=['DELETE'])
@auth_required_self(decrypt_user=True)
def delete_user_id():
    user_id = g.auth_user_id
    try:
        user_row = db.session.execute(text("""
            SELECT u.id, u.referred_by, c.email, c.phone
            FROM users u
            LEFT JOIN contact_info c
                ON c.parent_id = u.id AND c.parent_type = 'user'
            WHERE u.id = :user_id
            LIMIT 1
        """), {"user_id": user_id}).mappings().first()
        if not user_row:
            return jsonify({"message": "User not found"}), 404

        db.session.execute(text("""
            INSERT INTO deleted_user_cooldown (email, phone, referred_by, created_at, expires_at)
            VALUES (
                COALESCE(:email, ''),
                COALESCE(:phone, ''),
                :referred_by,
                NOW(),
                NOW() + INTERVAL '30 days'
            )
        """), {
            "email": user_row.get("email"),
            "phone": user_row.get("phone"),
            "referred_by": user_row.get("referred_by"),
        })

        db.session.execute(text("""
            DELETE FROM payment_transaction_mappings WHERE transaction_id IN (
                SELECT id FROM transactions WHERE user_id = :user_id OR
                    (reference_id IN (SELECT id::text FROM user_passes WHERE user_id = :user_id) AND booking_type = 'pass_purchase')
            );
            DELETE FROM pass_redemption_logs
            WHERE user_id = :user_id
               OR user_pass_id IN (SELECT id FROM user_passes WHERE user_id = :user_id);
            DELETE FROM team_invites WHERE inviter_user_id = :user_id OR invited_user_id = :user_id;
            DELETE FROM team_members WHERE user_id = :user_id;
            DELETE FROM teams WHERE created_by_user = :user_id;
            DELETE FROM referral_tracking WHERE referred_user_id = :user_id;
            DELETE FROM notifications WHERE user_id = :user_id;
            DELETE FROM user_hash_coins WHERE user_id = :user_id;
            DELETE FROM fcm_tokens WHERE user_id = :user_id;
            DELETE FROM vouchers WHERE user_id = :user_id;
            DELETE FROM transactions WHERE user_id = :user_id OR
                (reference_id IN (SELECT id::text FROM user_passes WHERE user_id = :user_id) AND booking_type = 'pass_purchase');
            DELETE FROM user_passes WHERE user_id = :user_id;
            DELETE FROM physical_address WHERE parent_id = :user_id AND parent_type = 'user';
            DELETE FROM contact_info WHERE parent_id = :user_id AND parent_type = 'user';
            DELETE FROM hash_wallet_transactions WHERE user_id = :user_id;
            DELETE FROM hash_wallets WHERE user_id = :user_id;
            DELETE FROM users WHERE id = :user_id;
        """), {"user_id": user_id})

        db.session.commit()
        _USER_CACHE.pop(user_id, None)
        _USER_FID_CACHE.clear()

        return jsonify({"message": "User deleted successfully"}), 200

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error deleting user %s", user_id)
        return jsonify({
            "message": "Failed to delete user",
            "error": "internal_server_error"
        }), 500

@user_blueprint.route('/users', methods=['GET'])
@auth_required_self(decrypt_user=True)
def get_user():
    user_id = g.auth_user_id
    try:
        cache_ttl_sec = int(current_app.config.get("USER_CACHE_TTL_SEC", 15))
        cached = _USER_CACHE.get(user_id)
        now_ts = time.time()
        if cached and cached["expires_at"] > now_ts:
            return jsonify({"user": cached["payload"]}), 200

        user = UserService.get_user(user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

        user_payload = user.to_dict()
        if len(_USER_CACHE) >= _USER_CACHE_MAX_SIZE:
            _USER_CACHE.pop(next(iter(_USER_CACHE)))
        _USER_CACHE[user_id] = {
            "payload": user_payload,
            "expires_at": now_ts + cache_ttl_sec,
        }
        return jsonify({"user": user_payload}), 200
    except Exception:
        current_app.logger.exception("Get user failed for user_id=%s", user_id)
        return jsonify({"message": "Internal server error"}), 500

@user_blueprint.route('/users/fid/<string:user_fid>', methods=['GET'])
def get_user_by_fid_auth(user_fid):
    try:
        started = time.perf_counter()
        user_fid = (user_fid or "").strip()
        if not user_fid:
            return jsonify({'message': 'user_fid is required'}), 400
        if len(user_fid) > 255:
            return jsonify({'message': 'user_fid is too long'}), 400

        cache_ttl_sec = int(current_app.config.get("USER_FID_CACHE_TTL_SEC", 30))
        cached = _USER_FID_CACHE.get(user_fid)
        now_ts = time.time()
        if cached and cached["expires_at"] > now_ts:
            user_payload = cached["payload"]
        else:
            user_payload = UserService.get_user_auth_payload_by_fid(user_fid)
            if not user_payload:
                return jsonify({'message': 'User not found'}), 404
            if len(_USER_FID_CACHE) >= _USER_FID_CACHE_MAX_SIZE:
                _USER_FID_CACHE.pop(next(iter(_USER_FID_CACHE)))
            _USER_FID_CACHE[user_fid] = {
                "payload": user_payload,
                "expires_at": now_ts + cache_ttl_sec,
            }

        token_ttl_hours = int(current_app.config.get("USER_FID_AUTH_TOKEN_TTL_HOURS", 2))
        now_utc = datetime.utcnow()
        encoded_user_id = encode_user(
            user_payload["id"],
            current_app.config['ENCRYPT_PUBLIC_KEY']
        )

        payload = {
            # Keep both keys to preserve compatibility with existing consumers.
            'uid': encoded_user_id,
            'uuid': encoded_user_id,
            'iat': now_utc,
            'created_at': now_utc.isoformat(),
            'exp': now_utc + timedelta(hours=token_ttl_hours)
        }
        jwt_secret = current_app.config.get('JWT_SECRET_KEY') or current_app.config.get('SECRET_KEY')
        if not jwt_secret:
            current_app.logger.error("JWT secret missing for fid auth endpoint")
            return jsonify({'message': 'Internal server error'}), 500

        custom_jwt = jwt.encode(payload, jwt_secret, algorithm="HS256")

        response = jsonify({'user': user_payload, 'token': custom_jwt})
        response.headers['Authorization'] = f'Bearer {custom_jwt}'
        response.headers['Cache-Control'] = 'no-store'
        current_app.logger.info(
            "GET /users/fid completed in %.2f ms for fid=%s",
            (time.perf_counter() - started) * 1000,
            user_fid,
        )
        return response, 200

    except Exception:
        current_app.logger.exception('Internal error fetching user by fid')
        return jsonify({'message': 'Internal server error'}), 500


@user_blueprint.route('/users/search', methods=['GET'])
@auth_required_self(decrypt_user=True)
def search_users():
    """
    Fast incremental user search for invite flows.
    Query params:
      - q | search | username | email
      - limit (default 20, max 50)
      - page (default 1)
    """
    try:
        q = (
            request.args.get("q")
            or request.args.get("search")
            or request.args.get("username")
            or request.args.get("email")
            or ""
        ).strip()

        if not q:
            return jsonify({"users": [], "count": 0, "page": 1, "limit": 20, "query": q, "has_more": False}), 200

        limit = request.args.get("limit", default=20, type=int)
        page = request.args.get("page", default=1, type=int)
        include_count = request.args.get("include_count", default="false").lower() == "true"
        if limit <= 0 or limit > 50:
            return jsonify({"message": "limit must be between 1 and 50"}), 400
        if page <= 0:
            return jsonify({"message": "page must be >= 1"}), 400
        if len(q) > 64:
            return jsonify({"message": "query too long"}), 400

        # Fast path: game username prefix search (index-friendly).
        # For typeahead, this avoids expensive lower()/count scans on each keystroke.
        offset = (page - 1) * limit
        auth_user_id = g.auth_user_id
        now_ts = time.time()
        cache_ttl_sec = int(current_app.config.get("USER_SEARCH_CACHE_TTL_SEC", 10))
        cache_key = f"{auth_user_id}|{q}|{limit}|{page}|{int(include_count)}"
        cached = _USER_SEARCH_CACHE.get(cache_key)
        if cached and cached["expires_at"] > now_ts:
            return jsonify(cached["payload"]), 200

        q_prefix = q
        q_prefix_hi = f"{q_prefix}\uffff"
        fetch_limit = limit + 1

        rows = db.session.execute(text("""
            SELECT
                u.id,
                u.name,
                u.game_username,
                u.avatar_path,
                u.fid
            FROM users u
            WHERE u.parent_type = 'user'
              AND u.id <> :auth_user_id
              AND u.game_username >= :q_prefix
              AND u.game_username < :q_prefix_hi
            ORDER BY u.game_username ASC
            LIMIT :fetch_limit OFFSET :offset
        """), {
            "auth_user_id": auth_user_id,
            "q_prefix": q_prefix,
            "q_prefix_hi": q_prefix_hi,
            "fetch_limit": fetch_limit,
            "offset": offset
        }).mappings().all()

        # Fallback for case-insensitive behavior if fast case-sensitive pass is empty.
        if not rows:
            pattern_prefix_ci = f"{q.lower()}%"
            rows = db.session.execute(text("""
                SELECT
                    u.id,
                    u.name,
                    u.game_username,
                    u.avatar_path,
                    u.fid
                FROM users u
                WHERE u.parent_type = 'user'
                  AND u.id <> :auth_user_id
                  AND lower(u.game_username) LIKE :pattern_prefix_ci
                ORDER BY u.game_username ASC
                LIMIT :fetch_limit OFFSET :offset
            """), {
                "auth_user_id": auth_user_id,
                "pattern_prefix_ci": pattern_prefix_ci,
                "fetch_limit": fetch_limit,
                "offset": offset
            }).mappings().all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        payload = {
            "query": q,
            "page": page,
            "limit": limit,
            "has_more": has_more,
            "users": [
                {
                    "id": row["id"],
                    "name": row["name"] or "",
                    "gameUserName": row["game_username"] or "",
                    "avatar_path": row["avatar_path"] or "",
                    "fid": row["fid"] or "",
                }
                for row in rows
            ]
        }

        # Count is optional because COUNT(*) is expensive under high QPS typeahead.
        if include_count:
            pattern_prefix_ci = f"{q.lower()}%"
            total_count = db.session.execute(text("""
                SELECT COUNT(1)
                FROM users u
                WHERE u.parent_type = 'user'
                  AND u.id <> :auth_user_id
                  AND lower(u.game_username) LIKE :pattern_prefix_ci
            """), {
                "auth_user_id": auth_user_id,
                "pattern_prefix_ci": pattern_prefix_ci,
            }).scalar() or 0
            payload["count"] = int(total_count)
        else:
            payload["count"] = None

        if len(_USER_SEARCH_CACHE) >= _USER_SEARCH_CACHE_MAX_SIZE:
            _USER_SEARCH_CACHE.pop(next(iter(_USER_SEARCH_CACHE)))
        _USER_SEARCH_CACHE[cache_key] = {
            "payload": payload,
            "expires_at": now_ts + cache_ttl_sec,
        }

        return jsonify(payload), 200
    except Exception:
        current_app.logger.exception("User search failed")
        return jsonify({"message": "Internal server error"}), 500

@user_blueprint.route('/users/create-voucher', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def create_voucher_for_referral_points():
    user_id = g.auth_user_id 
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

@user_blueprint.route('/users/voucher', methods=['GET'])
@auth_required_self(decrypt_user=True) 
def get_voucher_by_user():
    user_id = g.auth_user_id 
    try:
        vouchers = UserService.get_user_vouchers(user_id)
        return jsonify({
            "vouchers": [v.to_dict() for v in vouchers],
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@user_blueprint.route('/users/hash-coins', methods=['GET'])
@auth_required_self(decrypt_user=True) 
def get_user_hash_coins():
    user_id = g.auth_user_id 
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

@user_blueprint.route('/users/hash-coins', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def add_hash_coins():
    """
    Example: Add hash coins to user and notify.
    {
        "amount": 500
    }
    """
    user_id = g.auth_user_id 
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

@user_blueprint.route("/users/wallet", methods=["GET"])
@auth_required_self(decrypt_user=True)  # set to False if sub is not encrypted
def get_wallet_balance_auth():
    user_id = g.auth_user_id  # injected by the decorator
    wallet = HashWallet.query.filter_by(user_id=user_id).first()
    if not wallet:
        return jsonify({"message": "Wallet not found"}), 404
    return jsonify({"balance": wallet.balance}), 200

@user_blueprint.route('/users/wallet', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def add_wallet_balance():
    user_id = g.auth_user_id 
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

@user_blueprint.route("/user/purchase_pass", methods=["POST"])
@auth_required_self(decrypt_user=True) 
def user_purchase_pass():
    user_id = g.auth_user_id 
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

@user_blueprint.route('/users/transactions', methods=['GET'])
@auth_required_self(decrypt_user=True) 
def user_transaction_history():
    user_id = g.auth_user_id 
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

@user_blueprint.route("/user/available_passes", methods=["GET"])
@auth_required_self(decrypt_user=True) 
def user_available_passes():
    user_id = g.auth_user_id 
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

    # Build result with is_bought info + vendor images + HOUR-BASED PASS DETAILS ✅
    result = []
    for p in available_passes:
        vendor_images = []
        if p.vendor:  # only vendor passes have vendor images
            vendor_images = [{"id": img.id, "url": img.url} for img in p.vendor.images]

        pass_data = {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "days_valid": p.days_valid,
            "description": p.description,
            "pass_type": p.pass_type.name if p.pass_type else None,
            "vendor_id": p.vendor_id,
            "vendor_name": p.vendor.cafe_name if p.vendor else "Hash Pass",
            "vendor_images": vendor_images,
            "is_bought": p.id in bought_pass_ids,
            
            # ✅ ADDED: Hour-based pass details
            "pass_mode": p.pass_mode,  # 'date_based' or 'hour_based'
            "total_hours": float(p.total_hours) if p.total_hours else None,
            "hour_calculation_mode": p.hour_calculation_mode,  # 'actual_duration' or 'vendor_config'
            "hours_per_slot": float(p.hours_per_slot) if p.hours_per_slot else None
        }
        
        result.append(pass_data)

    return jsonify(result), 200


@user_blueprint.route("/user/all_passes", methods=["GET"])
@auth_required_self(decrypt_user=True) 
def user_all_passes():
    user_id = g.auth_user_id 
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

@user_blueprint.route("/user/passes", methods=["GET"])
@auth_required_self(decrypt_user=True)
def user_passes():
    user_id = g.auth_user_id 
    today = datetime.utcnow().date()

    user_passes = UserPass.query.join(CafePass).filter(
        UserPass.user_id == user_id,
        UserPass.is_active == True,
        UserPass.valid_to >= today
    ).all()

    result = []
    for up in user_passes:
        cafe_pass = up.cafe_pass

        vendor_images = []
        if cafe_pass.vendor:  # only for vendor passes
            vendor_images = [{"id": img.id, "url": img.url} for img in cafe_pass.vendor.images]

        result.append({
            "id": up.id,
            "cafe_pass_id": cafe_pass.id,
            "cafe_pass_name": cafe_pass.name,
            "vendor_id": cafe_pass.vendor_id,
            "vendor_name": cafe_pass.vendor.cafe_name if cafe_pass.vendor else "Hash Pass",
            "vendor_images": vendor_images,  # ✅ added vendor images
            "valid_from": up.valid_from.isoformat(),
            "valid_to": up.valid_to.isoformat(),
            "pass_type": cafe_pass.pass_type.name if cafe_pass.pass_type else None
        })

    return jsonify(result), 200

@user_blueprint.route("/user/passes/history", methods=["GET"])
@auth_required_self(decrypt_user=True)
def user_passes_history():
    user_id = g.auth_user_id 
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

@user_blueprint.route("/getAllFCMToken", methods=["GET"])
def get_all_fcm():
    try:
        # Fetch all tokens with related user data
        tokens = (
            db.session.query(FCMToken, User)
            .join(User, FCMToken.user_id == User.id)
            .all()
        )

        result = [
            {
                "token": fcm.token,
                "platform": fcm.platform,
                "created_at": fcm.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "user": {
                    "name": user.name,
                    "gender": user.gender
                }
            }
            for fcm, user in tokens
        ]

        return jsonify({"success": True, "data": result}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@user_blueprint.route('/user/<int:user_id>/available_passes', methods=['GET'])
def get_user_available_passes_by_id(user_id):
    """
    Get available passes for a specific user by user_id.
    Includes hour-based pass details.
    Query params: ?type=hash|vendor
    """
    try:
        today = datetime.utcnow().date()
        pass_type_filter = request.args.get('type', None)  # 'vendor', 'hash', or None

        # Check if user exists
        user = User.query.get(user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

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

        # Build result with hour-based pass details ✅
        result = []
        for p in available_passes:
            vendor_images = []
            if p.vendor:  # only vendor passes have vendor images
                vendor_images = [{"id": img.id, "url": img.url} for img in p.vendor.images]

            pass_data = {
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "days_valid": p.days_valid,
                "description": p.description,
                "pass_type": p.pass_type.name if p.pass_type else None,
                "vendor_id": p.vendor_id,
                "vendor_name": p.vendor.cafe_name if p.vendor else "Hash Pass",
                "vendor_images": vendor_images,
                "is_bought": p.id in bought_pass_ids,
                
                # ✅ Hour-based pass details
                "pass_mode": p.pass_mode,  # 'date_based' or 'hour_based'
                "total_hours": float(p.total_hours) if p.total_hours else None,
                "hour_calculation_mode": p.hour_calculation_mode,  # 'actual_duration' or 'vendor_config'
                "hours_per_slot": float(p.hours_per_slot) if p.hours_per_slot else None
            }
            
            result.append(pass_data)

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching available passes for user {user_id}: {str(e)}")
        return jsonify({"error": "Failed to fetch available passes", "details": str(e)}), 500


@user_blueprint.route('/users/notifications', methods=['GET'])
@auth_required_self(decrypt_user=True)
def list_user_notifications():
    user_id = g.auth_user_id
    try:
        limit = request.args.get("limit", default=50, type=int)
        unread_only = request.args.get("unread_only", default="false").lower() == "true"
        if limit <= 0 or limit > 200:
            return jsonify({"message": "limit must be between 1 and 200"}), 400

        q = Notification.query.filter(Notification.user_id == user_id)
        if unread_only:
            q = q.filter(Notification.is_read == False)

        items = q.order_by(Notification.created_at.desc()).limit(limit).all()
        unread_count = Notification.query.filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).count()

        return jsonify({
            "notifications": [n.to_dict() for n in items],
            "unread_count": unread_count
        }), 200
    except Exception:
        current_app.logger.exception("Failed to list notifications for user_id=%s", user_id)
        return jsonify({"message": "Internal server error"}), 500


@user_blueprint.route('/users/notifications/<uuid:notification_id>/read', methods=['PATCH'])
@auth_required_self(decrypt_user=True)
def mark_notification_read(notification_id):
    user_id = g.auth_user_id
    try:
        notif = Notification.query.filter(
            Notification.id == notification_id,
            Notification.user_id == user_id
        ).first()
        if not notif:
            return jsonify({"message": "Notification not found"}), 404

        if not notif.is_read:
            notif.is_read = True
            db.session.commit()

        return jsonify({"message": "Notification marked as read", "notification_id": str(notif.id)}), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to mark notification read for user_id=%s", user_id)
        return jsonify({"message": "Internal server error"}), 500


@user_blueprint.route('/users/notifications/demo', methods=['POST'])
@auth_required_self(decrypt_user=True)
def trigger_demo_notification():
    """
    Demo endpoint to create a notification + trigger FCM with invite-like payload.
    """
    user_id = g.auth_user_id
    data = request.get_json(silent=True) or {}
    invite_status = (data.get("invite_status") or "pending").strip().lower()
    if invite_status not in {"pending", "accepted", "rejected"}:
        return jsonify({"message": "invite_status must be one of pending|accepted|rejected"}), 400

    try:
        reference_id = str(data.get("reference_id") or uuid.uuid4())
        event_id = str(data.get("event_id") or uuid.uuid4())
        invite_id = str(data.get("invite_id") or uuid.uuid4())
        title = (data.get("title") or "Demo Team Invite").strip()
        message = (data.get("message") or f"Demo invite status: {invite_status}").strip()

        notification = Notification(
            user_id=user_id,
            type="demo_notification",
            reference_id=reference_id,
            title=title,
            message=message,
            is_read=False,
        )
        db.session.add(notification)
        db.session.commit()

        fcm_payload = {
            "type": "new_notification",
            "notification_id": str(notification.id),
            "reference_id": reference_id,
            "event_id": event_id,
            "invite_id": invite_id,
            "invite_status": invite_status,
        }

        tokens = db.session.query(FCMToken.token).filter(FCMToken.user_id == user_id).all()
        sent_count = 0
        for token_row in tokens:
            send_notification(
                token=token_row[0],
                title=title,
                body=message,
                data=fcm_payload,
            )
            sent_count += 1

        return jsonify({
            "ok": True,
            "notification": notification.to_dict(),
            "fcm_payload": fcm_payload,
            "devices_targeted": sent_count
        }), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to trigger demo notification for user_id=%s", user_id)
        return jsonify({"message": "Internal server error"}), 500
