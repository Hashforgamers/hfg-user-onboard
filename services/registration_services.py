from models.registrations import Registrations
from db.extensions import db
from models.teams import Team
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError


class RegistrationService:
    def __init__(self):
        pass

    def submit_waiver(self, registration_id, data):
        # Submit waiver for a registration
        try:
            # Validate registration exists
            registration = Registrations.query.get(registration_id)
            if not registration:
                raise ValueError("Registration not found")

            # Check if waiver already signed
            if registration.waiver_signed:
                raise ValueError("Waiver already signed for this registration")

            # Validate required fields
            required_fields = ["accepted", "signed_by"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")

            if not data["accepted"]:
                raise ValueError("Waiver must be accepted")

            # Update registration
            registration.waiver_signed = True
            registration.notes = (
                registration.notes or ""
            ) + f"\nWaiver signed by {data['signed_by']} at {datetime.utcnow()}"

            # If payment is not required and waiver is signed, confirm registration
            if registration.payment_status == "not_required":
                registration.status = "confirmed"

            db.session.commit()

            return {
                "registration_id": registration.id,
                "waiver_signed": True,
                "signed_by": data["signed_by"],
                "status": registration.status,
            }

        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error: {str(e)}")

    def get_registration_by_id(self, registration_id):
        # Fetch registration by ID with team and event details
        try:
            registration = (
                db.session.query(Registrations)
                .filter(Registrations.id == registration_id)
                .first()
            )

            if registration:
                return registration.to_dict()
            return None
        except SQLAlchemyError as e:
            raise Exception(f"Database error: {str(e)}")

    def get_registrations_by_event(self, event_id, status=None):
        # Get all registrations for an event, optionally filtered by status
        try:
            query = db.session.query(Registrations).filter(
                Registrations.event_id == event_id
            )

            if status:
                query = query.filter(Registrations.status == status)

            registrations = query.order_by(Registrations.created_at.asc()).all()

            return [reg.to_dict() for reg in registrations]
        except SQLAlchemyError as e:
            raise Exception(f"Database error: {str(e)}")

    def update_registration_status(self, registration_id, status):
        # Update registration status (for admin use)
        try:
            registration = Registrations.query.get(registration_id)
            if not registration:
                raise ValueError("Registration not found")

            valid_statuses = ["pending", "confirmed", "cancelled", "rejected"]
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )

            registration.status = status
            db.session.commit()

            return registration.to_dict()
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error: {str(e)}")
