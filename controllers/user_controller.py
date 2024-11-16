from flask import Blueprint, request, jsonify
from services.user_service import UserService

user_blueprint = Blueprint('user', __name__)

@user_blueprint.route('/api/auth/login', methods=['POST'])
def login_user():
    try:
        id_token = request.json.get('id_token')
        user, message = UserService.login_or_create_user(id_token)
        
        if user:
            return jsonify({
                'message': message,
                'user': user.to_dict()
            }), 200
        return jsonify({'error': message}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@user_blueprint.route('/api/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = UserService.get_user_by_id(user_id)
    if user:
        return jsonify(user), 200
    return jsonify({'error': 'User not found'}), 404
