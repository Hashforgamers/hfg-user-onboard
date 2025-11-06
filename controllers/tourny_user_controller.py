from flask import Blueprint, request, jsonify
from services.tourny_user_service import UserService

user_controller = Blueprint("user_controller", __name__)


@user_controller.route("/events", methods=["GET"])
def get_events_by_status():
    """
    Controller for GET /events?status=registration_open
    Endpoint to retrieve events with optional status filter
    """
    status = request.args.get("status")
    events = UserService.get_events_by_status(status)
    return jsonify(events), 200


@user_controller.route("/events/<int:event_id>", methods=["GET"])
def get_event_by_id(event_id):
    """
    Controller for GET /events/{id}
    Endpoint to retrieve a specific event by ID
    """
    event = UserService.get_event_by_id(event_id)

    if not event:
        return jsonify({"error": "Event not found"}), 404

    return jsonify(event), 200


@user_controller.route("/events/<int:event_id>/teams", methods=["POST"])
def create_team(event_id):
    """
    Controller for POST /events/{id}/teams
    Endpoint to create a new team for an event
    """
    data = request.get_json()
    team, error = UserService.create_team(event_id, data)

    if error:
        return jsonify({"error": error}), 404

    return jsonify(team), 201


@user_controller.route("/events/<int:event_id>/registrations", methods=["POST"])
def create_registration(event_id):
    """
    Controller for POST /events/{id}/registrations
    Endpoint to create a new registration for an event
    """
    data = request.get_json()
    registration, error = UserService.create_registration(event_id, data)

    if error:
        return jsonify({"error": error}), 404

    return jsonify(registration), 201


@user_controller.route("/registrations/<int:registration_id>/waiver", methods=["POST"])
def sign_waiver(registration_id):
    """
    Controller for POST /registrations/{id}/waiver
    Endpoint to sign the waiver for a registration
    """
    result, error = UserService.sign_waiver(registration_id)

    if error:
        return jsonify({"error": error}), 404

    return jsonify(result), 200


# TODO: Implement payment processing endpoint


@user_controller.route("/events/<int:event_id>/results", methods=["GET"])
def get_event_results(event_id):
    """
    Controller for GET /events/{id}/results
    Endpoint to retrieve results/winners for an event
    """
    results = UserService.get_event_results(event_id)

    if not results:
        return jsonify({"error": "Event not found"}), 404

    return jsonify(results), 200
