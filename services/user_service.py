from datetime import datetime
from db.extensions import db
from models.user import User
from models.contactInfo import ContactInfo
from models.physicalAddress import PhysicalAddress
from flask import current_app
from .utils import generate_credentials, send_email, generate_referral_code
from werkzeug.security import generate_password_hash
from models.passwordManager import PasswordManager
from models.referralTracking import ReferralTracking
from models.voucher import Voucher
from models.hashWallet import HashWallet
from models.deletedUserCoolDownPeriod import DeletedUserCooldown
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload, load_only


class UserService:
    
    @staticmethod
    def create_user(data):
        """Creates a new user and related entities in the database, with validations."""
        try:
            current_app.logger.debug("Starting user creation process with data: %s", data)

            # Check if fid already exists (scalar lookup is faster than loading full row)
            if db.session.query(User.id).filter_by(fid=data['fid']).scalar():
                return {
                    "status": "error",
                    "state": "USER_EXISTS",
                    "message": "A user with this FID already exists.",
                    "details": {"fid": data['fid']}
                }

            # Check if email already exists
            email_to_check = data.get('contact', {}).get('electronicAddress', {}).get('emailId')
            if email_to_check:
                if db.session.query(ContactInfo.id).filter_by(email=email_to_check).scalar():
                    return {
                        "status": "error",
                        "state": "EMAIL_EXISTS",
                        "message": "This email is already in use.",
                        "details": {"email": email_to_check}
                    }

            # Check if username already exists
            if db.session.query(User.id).filter_by(game_username=data['gameUserName']).scalar():
                return {
                    "status": "error",
                    "state": "USERNAME_TAKEN",
                    "message": "This game username is already taken.",
                    "details": {"gameUserName": data['gameUserName']}
                }

            # Parse date of birth
            dob = datetime.strptime(data['dob'], '%d-%b-%Y') if data.get('dob') else None
            current_app.logger.debug("Parsed date of birth: %s", dob)

            referral_input = data.get('referral_code')
            current_app.logger.debug("Referral input: %s", referral_input)

            # Generate a unique referral code
            while True:
                code = generate_referral_code()
                current_app.logger.debug("Generated referral code: %s", code)
                if not User.query.filter_by(referral_code=code).first():
                    break
            current_app.logger.debug("Final referral code: %s", code)

            # Create the User object
            user = User(
                fid=data['fid'],
                avatar_path=data.get('avatar_path', ''),
                name=data.get('name', ''),
                gender=data.get('gender', ''),
                dob=dob,
                game_username=data['gameUserName'],
                parent_type="user",
                referral_code=code
            )
            current_app.logger.debug("Created User object: %s", user)

            # Add user to session first
            db.session.add(user)
            db.session.flush()  # Assigns user.id from DB without committing
            current_app.logger.debug("Flushed session, user id: %s", user.id)

            # Add related objects using the relationship (now user.id is available)
            UserService._add_physical_address(user, data.get('contact', {}).get('physicalAddress'))
            current_app.logger.debug("Added physical address for user")

            UserService._add_contact_info(user, data.get('contact', {}).get('electronicAddress'))
            current_app.logger.debug("Added contact info for user")

            if referral_input:
                referrer = User.query.filter_by(referral_code=referral_input).first()
                current_app.logger.debug("Found referrer: %s", referrer)
                if referrer and referrer.referral_code != code:  # Prevent self-referral
                    user.referred_by = referral_input
                    referrer.referral_rewards += 1
                    
                    # Flush again to ensure user.id is committed before creating referral tracking
                    db.session.flush()
                    
                    referral_track = ReferralTracking(
                        referrer_code=referrer.referral_code,
                        referred_user_id=user.id
                    )
                    db.session.add(referral_track)
                    current_app.logger.debug("Updated referrer rewards and added referral tracking")

            # Creation of Hash Wallet + PasswordManager in same transaction
            wallet = HashWallet(user_id=user.id, balance=0)
            db.session.add(wallet)
            current_app.logger.debug("Created and added HashWallet for user")

            _, password = generate_credentials()
            password_manager = PasswordManager(
                userid=user.id,
                password=password,
                parent_id=user.id,
                parent_type="user"
            )
            db.session.add(password_manager)
            current_app.logger.info("PasswordManager created for user ID: %s", user.id)

            db.session.commit()
            current_app.logger.debug("Committed transaction")

            return user

        except ValueError as ve:
            db.session.rollback()
            current_app.logger.warning("Validation error: %s", str(ve))
            raise Exception(f"Validation error: {str(ve)}")

        except Exception as e:
            db.session.rollback()
            current_app.logger.error("Failed to create user: %s", str(e))
            raise Exception(f"An unexpected error occurred while creating the user: {str(e)}")

    @staticmethod
    def _add_physical_address(user, physical_address_data):
        """Add physical address to user using relationship"""
        # If no address or incomplete address, fill with defaults
        if not physical_address_data:
            physical_address_data = {}

        physical_address = PhysicalAddress(
            address_type=physical_address_data.get('address_type', 'home'),
            addressLine1=physical_address_data.get('addressLine1', 'N/A'),
            addressLine2=physical_address_data.get('addressLine2', ''),
            pincode=physical_address_data.get('pincode', '000000'),
            state=physical_address_data.get('State', 'N/A'),
            country=physical_address_data.get('Country', 'N/A'),
            is_active=physical_address_data.get('is_active', True),
            parent_id=user.id,
            parent_type="user"
        )
        # Use relationship assignment - this automatically adds to session
        user.physical_address = physical_address

    @staticmethod
    def _add_contact_info(user, electronic_address_data):
        """Add contact info to user using relationship"""
        if not electronic_address_data:
            electronic_address_data = {}
            
        contact_info = ContactInfo(
            phone=electronic_address_data.get('mobileNo', ''),
            email=electronic_address_data.get('emailId', ''),
            parent_id=user.id,
            parent_type="user"
        )
        # Use relationship assignment - this automatically adds to session
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

            # Send email notification (commented out as per your code)
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
    def get_user(user_id):
        """Fetch a user by ID with eager loading of relationships"""
        user = User.query.options(
            joinedload(User.physical_address),
            joinedload(User.contact_info),
            selectinload(User.vouchers)
        ).filter_by(id=user_id).first()
        return user

    @staticmethod
    def get_user_by_fid(fid):
        """Fetch a user by FID for auth flow (read-only and low-latency)."""
        return User.query.options(
            load_only(
                User.id,
                User.fid,
                User.avatar_path,
                User.name,
                User.gender,
                User.dob,
                User.game_username,
                User.referral_code,
                User.referral_rewards,
                User.created_at,
                User.updated_at,
            ),
            joinedload(User.physical_address),
            joinedload(User.contact_info),
            selectinload(User.vouchers).load_only(
                Voucher.code,
                Voucher.discount_percentage,
                Voucher.is_active,
                Voucher.created_at,
            ),
        ).filter_by(fid=fid).first()

    @staticmethod
    def get_user_vouchers(user_id):
        """Get all vouchers for a user"""
        return Voucher.query.filter(Voucher.user_id == user_id).all()

    @staticmethod
    def is_in_cooldown(email, phone):
        """Check if email or phone is in cooldown period"""
        now = datetime.utcnow()
        cooldown = DeletedUserCooldown.query.filter(
            or_(DeletedUserCooldown.email == email, DeletedUserCooldown.phone == phone),
            DeletedUserCooldown.expires_at > now
        ).first()
        return cooldown is not None
