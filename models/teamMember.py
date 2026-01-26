from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.extensions import db

class TeamMember(db.Model):
    __tablename__ = 'team_members'
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    role = Column(String(32), default='member', nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    team = relationship('Team', back_populates='members')
