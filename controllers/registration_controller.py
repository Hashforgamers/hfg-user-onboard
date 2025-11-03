from flask import Blueprint, request, jsonify
from services.registration_services import RegistrationService

registration_bp = Blueprint("registrations", __name__)
registration_service = RegistrationService()


@registration_bp.route("/registrations/<int:id>/waiver", methods=["POST"])
def submit_waiver(id):
    """Submit waiver for a registration"""
    try:
        data = request.get_json()
        waiver = registration_service.submit_waiver(id, data)
        return jsonify({"success": True, "data": waiver}), 201
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
