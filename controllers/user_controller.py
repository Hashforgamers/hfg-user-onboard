from flask import request, jsonify, Blueprint
from services.user_service import UserService

user_blueprint = Blueprint('user', __name__)

@user_blueprint.route('/users', methods=['POST'])
def create_user():
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
