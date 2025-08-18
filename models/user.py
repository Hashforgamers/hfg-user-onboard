from sqlalchemy import Column, Integer, String, Date, DateTime, Sequence, ForeignKey, text, and_
from sqlalchemy.orm import relationship, foreign
from db.extensions import db
from models.voucher import Voucher

class User(db.Model):
    __tablename__ = 'users'

    id = Column(Integer, Sequence('users_id_seq', start=1001, increment=1), primary_key=True)
    fid = Column(String(255), unique=True, nullable=False)
    avatar_path = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    gender = Column(String(50), nullable=True)
    dob = Column(Date, nullable=True)
    game_username = Column(String(255), unique=True, nullable=False)
    parent_type = Column(String(50), nullable=False, default='user')

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('Asia/Kolkata', now())"),
        onupdate=text("TIMEZONE('Asia/Kolkata', now())"),
        nullable=False
    )

    # Relationships
    physical_address = relationship(
        'PhysicalAddress',
        back_populates='user',
        uselist=False,
        cascade="all, delete-orphan"
    )

    contact_info = relationship(
        'ContactInfo',
        primaryjoin="and_(foreign(ContactInfo.parent_id) == User.id, ContactInfo.parent_type == 'user')",
        back_populates='user',
        uselist=False,
        cascade="all, delete-orphan"
    )

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
    fcm_tokens = relationship('FCMToken', back_populates='user', cascade="all, delete-orphan")

    __mapper_args__ = {
        'polymorphic_identity': 'user',
        'polymorphic_on': parent_type,
    }

    def to_dict(self):
        return {
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
            ],
            "createdAt": self.created_at.strftime('%d-%b-%Y %H:%M') if self.created_at else None,
            "updatedAt": self.updated_at.strftime('%d-%b-%Y %H:%M') if self.updated_at else None
        }
