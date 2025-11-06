from models.events import Events
from models.teams import Team
from models.registrations import Registrations
from models.provisional_results import ProvisionalResults
from models.team_members import TeamMembers
from models.winners import Winners
from db.extensions import db

from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError


class UserService:
    """Service layer for User Service endpoints"""

    @staticmethod
    def get_events_by_status(status=None):
        """
        Business logic for GET /events?status=registration_open
        Retrieves events filtered by status
        """
        if status:
            events = Events.query.filter_by(status=status).all()
        else:
            events = Events.query.all()

        result = []
        for event in events:
            result.append(
                {
                    "id": event.id,
                    "title": event.title,
                    "description": event.description,
                    "start_at": event.start_at.isoformat() if event.start_at else None,
                    "end_at": event.end_at.isoformat() if event.end_at else None,
                    "registration_fee": float(event.registration_fee)
                    if event.registration_fee
                    else None,
                    "currency": event.currency,
                    "registration_deadline": event.registration_deadline.isoformat()
                    if event.registration_deadline
                    else None,
                    "capacity_team": event.capacity_team,
                    "capacity_player": event.capacity_player,
                    "min_team_size": event.min_team_size,
                    "max_team_size": event.max_team_size,
                    "show_solo": event.show_solo,
                    "status": event.status,
                    "visibility": event.visibility,
                }
            )

        return result

    @staticmethod
    def get_event_by_id(event_id):
        """
        Business logic for GET /events/{id}
        Retrieves a single event by ID
        """
        event = Events.query.get(event_id)

        if not event:
            return None

        return {
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "start_at": event.start_at.isoformat() if event.start_at else None,
            "end_at": event.end_at.isoformat() if event.end_at else None,
            "registration_fee": float(event.registration_fee)
            if event.registration_fee
            else None,
            "currency": event.currency,
            "registration_deadline": event.registration_deadline.isoformat()
            if event.registration_deadline
            else None,
            "capacity_team": event.capacity_team,
            "capacity_player": event.capacity_player,
            "min_team_size": event.min_team_size,
            "max_team_size": event.max_team_size,
            "show_solo": event.show_solo,
            "qr_code_url": event.qr_code_url,
            "status": event.status,
            "visibility": event.visibility,
            "show_individual": event.show_individual,
            "vendor_id": event.vendor_id,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        }

    @staticmethod
    def create_team(event_id, data):
        """
        Business logic for POST /events/{id}/teams
        Creates a new team for an event
        """
        event = Events.query.get(event_id)

        if not event:
            return None, "Event not found"

        new_team = Team(
            event_id=event_id,
            name=data.get("name"),
            is_individual=data.get("is_individual", False),
            created_by_user=data.get("created_by_user"),
        )

        db.session.add(new_team)
        db.session.commit()

        # Add team members if provided
        if "members" in data:
            for member in data["members"]:
                team_member = TeamMembers(
                    team_id=new_team.id,
                    user_id=member["user_id"],
                    role=member.get("role", "member"),
                )
                db.session.add(team_member)
            db.session.commit()

        return {
            "id": new_team.id,
            "event_id": new_team.event_id,
            "name": new_team.name,
            "is_individual": new_team.is_individual,
            "created_at": new_team.created_at.isoformat(),
        }, None

    @staticmethod
    def create_registration(event_id, data):
        """
        Business logic for POST /events/{id}/registrations
        Creates a new registration for an event
        """
        event = Events.query.get(event_id)

        if not event:
            return None, "Events not found"

        new_registration = Registrations(
            event_id=event_id,
            team_id=data.get("team_id"),
            contact_name=data.get("contact_name"),
            contact_phone=data.get("contact_phone"),
            contact_email=data.get("contact_email"),
            waiver_signed=data.get("waiver_signed", False),
            payment_status=data.get("payment_status", "pending"),
            status=data.get("status", "pending"),
            notes=data.get("notes"),
        )

        db.session.add(new_registration)
        db.session.commit()

        return {
            "id": new_registration.id,
            "event_id": new_registration.event_id,
            "team_id": new_registration.team_id,
            "contact_name": new_registration.contact_name,
            "contact_phone": new_registration.contact_phone,
            "contact_email": new_registration.contact_email,
            "waiver_signed": new_registration.waiver_signed,
            "payment_status": new_registration.payment_status,
            "status": new_registration.status,
            "created_at": new_registration.created_at.isoformat(),
        }, None

    @staticmethod
    def sign_waiver(registration_id):
        """
        Business logic for POST /registrations/{id}/waiver
        Signs the waiver for a registration
        """
        registration = Registrations.query.get(registration_id)

        if not registration:
            return None, "Registration not found"

        registration.waiver_signed = True
        db.session.commit()

        return {
            "id": registration.id,
            "waiver_signed": registration.waiver_signed,
            "message": "Waiver signed successfully",
        }, None

    # TODO: Implement payment processing logic

    @staticmethod
    def get_event_results(event_id):
        """
        Business logic for GET /events/{id}/results
        Retrieves the results/winners for an event
        """
        event = Events.query.get(event_id)

        if not event:
            return None

        winners = (
            Winners.query.filter_by(event_id=event_id).order_by(Winners.rank).all()
        )

        result = []
        for winner in winners:
            team = Team.query.get(winner.team_id)
            result.append(
                {
                    "rank": winner.rank,
                    "team_id": winner.team_id,
                    "team_name": team.name if team else None,
                    "verified_snapshot": winner.verified_snapshot,
                    "published_at": winner.published_at.isoformat()
                    if winner.published_at
                    else None,
                }
            )

        return {"event_id": event_id, "results": result}
