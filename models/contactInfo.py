from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

class ContactInfo(db.Model):
    __tablename__ = 'contact_info'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)

    # Polymorphic fields
    parent_id = Column(Integer, nullable=False)
    parent_type = Column(String(50), nullable=False)

    # Polymorphic relationships
    user = relationship("User", primaryjoin="and_(ContactInfo.parent_id==User.id, "
                                            "ContactInfo.parent_type=='user')", back_populates="contact_info")

    __mapper_args__ = {
        'polymorphic_identity': 'contact_info',
        'polymorphic_on': parent_type
    }

    def to_dict(self):
        return {
            "mobileNo": self.phone,
            "emailId": self.email,
        }
