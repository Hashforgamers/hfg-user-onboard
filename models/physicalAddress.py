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
    parent_type = Column(String(50), nullable=False, default='user')  # 'user' to be used here

    # Relationship to user
    user = relationship(
        'User',
        back_populates='physical_address',
        uselist=False,
        cascade="all, delete-orphan",
        single_parent=True  # Ensure only one PhysicalAddress can be linked to a user at a time
    )

    def to_dict(self):
        return {
            "address_type": self.address_type,
            "addressLine1": self.addressLine1,
            "addressLine2": self.addressLine2,
            "pincode": self.pincode,
            "State": self.state,
            "Country": self.country,
            "is_active": self.is_active,
        }
