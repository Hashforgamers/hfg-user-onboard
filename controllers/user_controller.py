from flask import request, jsonify, Blueprint, current_app
from services.user_service import UserService
from models.userHashCoin import UserHashCoin
from services.referral_service import create_voucher_if_eligible
from db.extensions import db
from models.hashWallet import HashWallet
from models.hashWalletTransaction import HashWalletTransaction

user_blueprint = Blueprint('user', __name__)

@user_blueprint.route('/users', methods=['POST'])
def create_user():
    current_app.logger.debug(f"Started Processing User Onboard Request {request.json} ")
    data = request.json
    try:
        user = UserService.create_user(data)
        return jsonify({"message": "User created successfully", "user": user.to_dict()}), 201
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@user_blueprint.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = UserService.get_user(user_id)

    if not user:
        return jsonify({"message": "User not found"}), 404

    return jsonify({"user": user.to_dict()})

@user_blueprint.route('/users/fid/<string:user_fid>', methods=['GET'])
def get_user_by_fid(user_fid):
    user = UserService.get_user_by_fid(user_fid)

    if not user:
        return jsonify({"message": "User not found"}), 404

    return jsonify({"user": user.to_dict()})

@user_blueprint.route('/users/<int:user_id>/create-voucher', methods=['POST'])
def create_voucher_for_referral_points(user_id):
    try:
        voucher = create_voucher_if_eligible(user_id)
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
        return jsonify({"message": "Wallet updated", "new_balance": wallet.balance})
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to update wallet", "error": str(e)}), 500

