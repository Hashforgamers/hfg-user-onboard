from datetime import datetime, timedelta
from db.extensions import db
from models.user import User
from models.contactInfo import ContactInfo
from models.physicalAddress import PhysicalAddress
from flask import current_app
from .utils import generate_credentials, send_email, generate_referral_code
from werkzeug.security import generate_password_hash
from models.passwordManager import PasswordManager
from models.referralTracking import ReferralTracking
from models.voucher import Voucher  # Import your Voucher model
from models.hashWallet import HashWallet

class UserService:
    
    @staticmethod
    def create_user(data):
        """Creates a new user and related entities in the database, with validations."""
        try:
            # Check if fid, email, or game_username already exists
            if User.query.filter_by(fid=data['fid']).first():
                raise ValueError("A user with this FID already exists.")

            if ContactInfo.query.filter_by(email=data['contact']['electronicAddress'].get('emailId')).first():
                raise ValueError("This email is already in use.")

            if User.query.filter_by(game_username=data['gameUserName']).first():
                raise ValueError("This game username is already taken.")

            # Parse date of birth if provided
            dob = datetime.strptime(data['dob'], '%d-%b-%Y') if data.get('dob') else None

            referral_input = data.get('referral_code')

            # Generate a unique referral code
            while True:
                code = generate_referral_code()
                if not User.query.filter_by(referral_code=code).first():
                    break

            # Create the User object
            user = User(
                fid=data['fid'],
                avatar_path=data.get('avatar_path'),
                name=data['name'],
                gender=data.get('gender'),
                dob=dob,
                game_username=data['gameUserName'],
                parent_type="user",
                referral_code=code
            )

            # Add related objects
            UserService._add_physical_address(user, data['contact'].get('physicalAddress'))
            UserService._add_contact_info(user, data['contact'].get('electronicAddress'))

            if referral_input:
                referrer = User.query.filter_by(referral_code=referral_input).first()
                if referrer and referrer.referral_code != code:  # Prevent self-referral
                    user.referred_by = referral_input
                    # Optionally reward both
                    referrer.referral_rewards += 1
                    db.session.add(ReferralTracking(referrer_code=referrer.referral_code, referred_user_id=user.id))

            db.session.add(user)
            db.session.flush()  # Assigns user.id from DB without committing

            # CReation of Hash Wallet
            wallet = HashWallet(user_id=user.id, balance=0)
            db.session.add(wallet)

            db.session.commit()

            # Generate credentials and notify the user
            UserService.generate_credentials_and_notify(user)

            return user

        except ValueError as ve:
            current_app.logger.warning(f"Validation error: {str(ve)}")
            raise Exception(f"Validation error: {str(ve)}")

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to create user: {str(e)}")
            raise Exception("An unexpected error occurred while creating the user.")

    @staticmethod
    def _add_physical_address(user, physical_address_data):
        if physical_address_data:
            physical_address = PhysicalAddress(
                address_type=physical_address_data['address_type'],
                addressLine1=physical_address_data['addressLine1'],
                addressLine2=physical_address_data.get('addressLine2'),
                pincode=physical_address_data['pincode'],
                state=physical_address_data['State'],
                country=physical_address_data['Country'],
                is_active=physical_address_data['is_active'],
                parent_id=user.id,
                parent_type="user"
            )
            user.physical_address = physical_address

    @staticmethod
    def _add_contact_info(user, electronic_address_data):
        if electronic_address_data:
            contact_info = ContactInfo(
                phone=electronic_address_data.get('mobileNo'),
                email=electronic_address_data.get('emailId'),
                parent_id=user.id,
                parent_type="user"
            )
            user.contact_info = contact_info

    @staticmethod
    def generate_credentials_and_notify(user):
        """Generates credentials for the user and sends a notification email."""
        try:
            username, password = generate_credentials()
            hashed_password = password

            password_manager = PasswordManager(
                userid=user.id,
                password=hashed_password,
                parent_id=user.id,
                parent_type="user"
            )
            db.session.add(password_manager)

            # Log credential creation
            current_app.logger.info(f"PasswordManager created for user ID: {user.id}")

            db.session.commit()

            # Send email notification
            current_app.logger.info(f"Mail generation started to user: {user.name}")
            # send_email(
            #     subject='Your Account Credentials',
            #     recipients=[user.contact_info.email],
            #     body=(
            #         f"Hello {user.name},\n\n"
            #         f"Your account has been created.\nUsername: {username}\nPassword: {password}\n\n"
            #     )
            # )
            # current_app.logger.info(f"Credentials sent to user: {user.name}")

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to generate credentials and notify user: {str(e)}")
            raise Exception("Failed to generate credentials and notify user.")

    @staticmethod
    def get_user_by_fid(fid):
        """Fetch a user by FID and expire old vouchers (older than 1 month)."""
        try:
            user = User.query.filter_by(fid=fid).first()
            if not user:
                raise ValueError(f"No user found with FID: {fid}")

            # Expire user's vouchers older than 1 month
            one_month_ago = datetime.utcnow() - timedelta(days=30)
            expired_vouchers = Voucher.query.filter(
                Voucher.user_id == user.id,
                Voucher.is_active == True,
                Voucher.created_at < one_month_ago
            ).all()

            for voucher in expired_vouchers:
                voucher.is_active = False

            if expired_vouchers:
                db.session.commit()

            return user

        except Exception as e:
            current_app.logger.error(f"Error fetching user by FID {fid}: {str(e)}")
            raise Exception("Failed to fetch user.")

    @staticmethod
    def get_user_vouchers(user_id):
        return Voucher.query.filter(Voucher.user_id == user_id).all()