from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db


class PhysicalAddress(db.Model):
    __tablename__ = 'physical_address'

    id = Column(Integer, primary_key=True)
    address_type = Column(String(50), nullable=False)
    addressLine1 = Column(String(255), nullable=False)
    addressLine2 = Column(String(255), nullable=True)
    pincode = Column(String(10), nullable=False)
    state = Column(String(100), nullable=False)
    country = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)

    # Foreign Key to user
    parent_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    parent_type = Column(String(50), nullable=False, default='user')

    # Relationship to user
    user = relationship(
        'User',
        back_populates='physical_address',
        foreign_keys=[parent_id]
    )

    def to_dict(self):
        """Safely serialize physical address to dictionary with proper type handling"""
        return {
            "address_type": str(self.address_type) if self.address_type else "home",
            "addressLine1": str(self.addressLine1) if self.addressLine1 else "",
            "addressLine2": str(self.addressLine2) if self.addressLine2 else "",
            "pincode": str(self.pincode) if self.pincode else "",
            "State": str(self.state) if self.state else "",
            "Country": str(self.country) if self.country else "",
            "is_active": bool(self.is_active) if self.is_active is not None else True
        }
