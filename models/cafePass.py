# models/cafePass.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, Numeric
from sqlalchemy.orm import relationship
from app.extension.extensions import db
from app.models.passType import PassType 

class CafePass(db.Model):
    __tablename__ = 'cafe_passes'
    
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=True, index=True)
    pass_type_id = Column(Integer, ForeignKey('pass_types.id'))
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String(255))
    is_active = Column(Boolean, default=True, index=True)
    
    # Date-based pass fields
    days_valid = Column(Integer, nullable=True)
    
    # Hour-based pass fields (NEW)
    pass_mode = Column(String(20), nullable=False, default='date_based', index=True)
    # Values: 'date_based' or 'hour_based'
    
    total_hours = Column(Numeric(precision=10, scale=2), nullable=True)
    # Total hours in the package (e.g., 10.00 for 10-hour pass)
    
    hour_calculation_mode = Column(String(20), nullable=True)
    # Values: 'actual_duration' or 'vendor_config'
    
    hours_per_slot = Column(Numeric(precision=5, scale=2), nullable=True)
    # Used when hour_calculation_mode = 'vendor_config'
    # E.g., vendor sets 30-min slot = 1 hour charge
    
    # Relationships
    pass_type = relationship('PassType')
    vendor = relationship('Vendor')
    
    def __repr__(self):
        return f"<CafePass id={self.id} name={self.name} mode={self.pass_mode}>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'vendor_id': self.vendor_id,
            'pass_type_id': self.pass_type_id,
            'name': self.name,
            'price': self.price,
            'description': self.description,
            'is_active': self.is_active,
            'pass_mode': self.pass_mode,
            'days_valid': self.days_valid,
            'total_hours': float(self.total_hours) if self.total_hours else None,
            'hour_calculation_mode': self.hour_calculation_mode,
            'hours_per_slot': float(self.hours_per_slot) if self.hours_per_slot else None
        }
