from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db


class ContactInfo(db.Model):
    __tablename__ = 'contact_info'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)

    # Foreign Key to User
    parent_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    parent_type = Column(String(50), nullable=False, default='user')

    # Relationship to User
    user = relationship("User", back_populates="contact_info", foreign_keys=[parent_id])

    def to_dict(self):
        """Safely serialize contact info to dictionary"""
        return {
            "mobileNo": str(self.phone) if self.phone else "",
            "emailId": str(self.email) if self.email else ""
        }
