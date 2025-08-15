from sqlalchemy import Column, Integer, String, Date, Sequence, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db
from models.voucher import Voucher

class User(db.Model):
    __tablename__ = 'users'

    id = Column(Integer, Sequence('users_id_seq', start=1001, increment=1),primary_key=True)
    fid = Column(String(255), unique=True, nullable=False)
    avatar_path = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    gender = Column(String(50), nullable=True)
    dob = Column(Date, nullable=True)
    game_username = Column(String(255), unique=True, nullable=False)

    # Adding the parent_type column explicitly
    parent_type = Column(String(50), nullable=False, default='user')

   # Relationship to PhysicalAddress
    physical_address = relationship(
        'PhysicalAddress',
        back_populates='user',
        uselist=False,  # One-to-one relationship
        cascade="all, delete-orphan"
    )

    # Relationship to ContactInfo
    contact_info = relationship(
        'ContactInfo',
        back_populates='user',
        uselist=False,  # One-to-one relationship
        cascade="all, delete-orphan"
    )

    # One-to-One relationship with PasswordManager
    # PasswordManager relationship
    password = relationship(
        'PasswordManager',
        primaryjoin="and_(foreign(PasswordManager.parent_id) == User.id, PasswordManager.parent_type == 'user')",
        back_populates='user',
        uselist=False,
        cascade="all, delete-orphan"
    )

    referral_code = Column(String(10), unique=True)
    referred_by = Column(String(10), ForeignKey('users.referral_code'), nullable=True)
    referral_rewards = Column(Integer, default=0)

    # Newly Added relation
    fcm_tokens = relationship('FCMToken', back_populates='user', cascade="all, delete-orphan")

    __mapper_args__ = {
        'polymorphic_identity': 'user',
        'polymorphic_on': parent_type,  # Ensure polymorphic_on points to parent_type
    }

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
            },
            "referralCode": self.referral_code,
            "referralRewards": self.referral_rewards,
            "vouchers": [
                {
                    "code": v.code,
                    "discountPercentage": v.discount_percentage,
                    "isActive": v.is_active,
                    "createdAt": v.created_at.strftime('%d-%b-%Y %H:%M')
                } for v in self.vouchers
            ]
        }
