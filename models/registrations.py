from sqlalchemy import UUID, Column, Integer, String, DateTime, text
from sqlalchemy.orm import relationship
from db.extensions import db


class Registrations(db.Model):
    __tablename__ = "registrations"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contact_name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(20), nullable=False)
    team_id = Column(UUID(as_uuid=True), nullable=False)
    event_id = Column(UUID(as_uuid=True), nullable=False)
    waiver_signed = Column(Integer, nullable=False, default=0)  # 0 for no, 1 for yes
    payment_status = Column(
        String(50), nullable=False, default="pending"
    )  # pending, completed, failed
    status = Column(String(50), nullable=False, default="active")  # active, cancelled
    notes = Column(String(500), nullable=True)

    # Timestamps

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False,
    )

    # relationships
    team = relationship("Team", foreign_keys=[team_id], back_populates="registrations")

    event = relationship(
        "Event", foreign_keys=[event_id], back_populates="registrations"
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "team_id": str(self.team_id),
            "event_id": str(self.event_id),
            "waiver_signed": self.waiver_signed,
            "payment_status": self.payment_status,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }
