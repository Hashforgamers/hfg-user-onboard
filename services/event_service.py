from models.events import Events
from models.teams import Team
from models.registrations import Registrations
from models.provisional_results import ProvisionalResults
from models.team_members import TeamMembers
from db.extensions import db
from flask import current_app

from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError


class EventService:
    def __init__(self):
        pass

    def get_events_by_status(self, status):
        # Fetch events by status
        try:
            events = Events.query.filter_by(status=status).all()
            return [event.to_dict() for event in events]
        except SQLAlchemyError as e:
            raise Exception(f"Database error: {str(e)}")

    def get_event_by_id(self, event_id):
        # Fetch event by ID
        try:
            event = Events.query.get(event_id)
            if event:
                return event.to_dict()
            return None
        except SQLAlchemyError as e:
            raise Exception(f"Database error: {str(e)}")

    def create_team(self, event_id, data):
        # Create a team for an event
        try:
            # Validate event exists
            event = Events.query.get(event_id)
            if not event:
                raise ValueError("Event not found")

            # Validate required fields
            required_fields = ["name", "created_by", "is_individual", "members"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")

            # Create team
            team = Team(
                events_id=event_id,
                name=data["name"],
                created_by=data["created_by"],
                is_individual=data["is_individual"],
                created_at=datetime.utcnow(),
            )

            current_app.logger.debug(
                f"Creating team: {team.name} for event ID: {event_id}"
            )

            db.session.add(team)
            db.session.flush()  # Get team ID before adding members

            # Add team members
            for member in data["members"]:
                team_member = TeamMembers(
                    team_id=team.id,
                    user_id=member["user_id"],
                    in_game_name=member.get("in_game_name"),
                    role=member.get("role"),
                )
                db.session.add(team_member)

            db.session.commit()
            return team.to_dict()

        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error: {str(e)}")

    def register_team(self, event_id, data):
        # Register a team for an event
        try:
            # Validate event exists and is open
            event = Events.query.get(event_id)
            if not event:
                raise ValueError("Event not found")

            if event.status != "registration_open":
                raise ValueError("Event registration is not open")

            # Check if team already registered
            existing = Registrations.query.filter_by(
                event_id=event_id, team_id=data["team_id"]
            ).first()

            if existing:
                raise ValueError("Team already registered for this event")

            # Validate required fields
            required_fields = ["team_id", "user_id"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")

            # Validate team exists
            team = Team.query.get(data["team_id"])
            if not team:
                raise ValueError("Team not found")

            # Create registration
            registration = Registrations(
                event_id=event_id,
                team_id=data["team_id"],
                user_id=data["user_id"],
                status="pending",
                payment_status="unpaid",
                created_at=datetime.utcnow(),
            )
            db.session.add(registration)
            db.session.commit()

            return registration.to_dict()

        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error: {str(e)}")

    def get_event_results(self, event_id):
        # Get results for an event with team and player details
        try:
            # Validate event exists
            event = Events.query.get(event_id)
            if not event:
                raise ValueError("Event not found")

            # Query results with joins for team information
            results = (
                db.session.query(ProvisionalResults, Team)
                .join(Team, ProvisionalResults.team_id == Team.id)
                .filter(ProvisionalResults.event_id == event_id)
                .order_by(ProvisionalResults.proposed_rank.asc())
                .all()
            )

            # Format results
            formatted_results = []
            for result, team in results:
                formatted_results.append(
                    {
                        "rank": result.rank,
                        "team": team.to_dict(),
                        "score": result.score,
                        "prize": result.prize,
                        "stats": result.stats,
                    }
                )

            return formatted_results

        except SQLAlchemyError as e:
            raise Exception(f"Database error: {str(e)}")
