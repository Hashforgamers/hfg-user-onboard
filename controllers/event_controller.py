from flask import Blueprint, request, jsonify
from services.event_service import EventService

event_bp = Blueprint("events", __name__)
event_service = EventService()


@event_bp.route("/events", methods=["GET"])
def get_open_events():
    # Get all events with registration_open status
    status = request.args.get("status", "registration_open")
    try:
        events = event_service.get_events_by_status(status)
        return jsonify({"success": True, "data": events}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@event_bp.route("/events/<int:id>", methods=["GET"])
def get_event(id):
    # Get specific event by ID
    try:
        event = event_service.get_event_by_id(id)
        if event:
            return jsonify({"success": True, "data": event}), 200
        return jsonify({"success": False, "error": "Event not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@event_bp.route("/events/<int:id>/teams", methods=["POST"])
def create_team(id):
    # Create a new team for an event
    try:
        data = request.get_json()
        team = event_service.create_team(id, data)
        return jsonify({"success": True, "data": team}), 201
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@event_bp.route("/events/<int:id>/registrations", methods=["POST"])
def create_registration(id):
    # Register a team for an event
    try:
        data = request.get_json()
        registration = event_service.register_team(id, data)
        return jsonify({"success": True, "data": registration}), 201
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@event_bp.route("/events/<int:id>/results", methods=["GET"])
def get_results(id):
    # Get results for an event
    try:
        results = event_service.get_event_results(id)
        return jsonify({"success": True, "data": results}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
