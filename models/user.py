from sqlalchemy import Column, Integer, String, Date
from sqlalchemy.orm import relationship
from db.extensions import db

class User(db.Model):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    fid = Column(String(255), unique=True, nullable=False)
    avatar_path = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    gender = Column(String(50), nullable=True)
    dob = Column(Date, nullable=True)
    game_username = Column(String(255), unique=True, nullable=False)

    # Relationships
    physical_address = relationship(
        'PhysicalAddress',
        primaryjoin="and_(PhysicalAddress.parent_id==User.id, "
                    "PhysicalAddress.parent_type=='user')",
        uselist=False,
        cascade="all, delete-orphan"
    )
    contact_info = relationship(
        'ContactInfo',
        primaryjoin="and_(ContactInfo.parent_id==User.id, "
                    "ContactInfo.parent_type=='user')",
        uselist=False,
        cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "fid": self.fid,
            "avatar_path": self.avatar_path,
            "name": self.name,
            "gender": self.gender,
            "dob": self.dob.strftime('%d-%b-%Y') if self.dob else None,
            "gameUserName": self.game_username,
            "contact": {
                "physicalAddress": self.physical_address.to_dict() if self.physical_address else None,
                "electronicAddress": self.contact_info.to_dict() if self.contact_info else None,
            }
        }
