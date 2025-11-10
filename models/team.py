from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from db.extensions import db

class Team(db.Model):
    __tablename__ = 'teams'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True),
                      ForeignKey('events.id', ondelete='CASCADE'),
                      nullable=False,
                      index=True)

    # matches DB exactly
    team_name = Column(String(255), nullable=False)

    is_individual = Column(Boolean, default=False, nullable=False)
    created_by_user = Column(BigInteger,
                             ForeignKey('users.id', ondelete='RESTRICT'),
                             nullable=False)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(),
                        nullable=False)

    event = relationship('Event', back_populates='teams')
    members = relationship('TeamMember',
                           back_populates='team',
                           cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint('team_name', name='teams_team_name_key'),
        db.UniqueConstraint('event_id', 'name', name='uq_team_event_name'),
    )

