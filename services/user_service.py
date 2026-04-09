from datetime import datetime
import time
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
from sqlalchemy import text
from sqlalchemy.orm import joinedload, selectinload, load_only
from sqlalchemy.exc import IntegrityError


class UserService:
    
    @staticmethod
    def create_user(data):
        """Creates a new user and related entities in the database, with validations."""
        try:
            timing_enabled = bool(current_app.config.get("USER_CREATE_TIMING_LOGS", True))
            t0 = time.perf_counter()
            t_last = t0
            timing_steps = []

            def mark(step_name):
                nonlocal t_last
                if not timing_enabled:
                    return
                now = time.perf_counter()
                timing_steps.append((step_name, (now - t_last) * 1000))
                t_last = now

            fid_value = data['fid']
            game_username = data['gameUserName']

            # Fast duplicate check in a single DB roundtrip for fid + username.
            duplicate_row = db.session.execute(text("""
                SELECT
                    EXISTS(SELECT 1 FROM users WHERE fid = :fid) AS fid_exists,
                    EXISTS(SELECT 1 FROM users WHERE game_username = :game_username) AS username_exists
            """), {
                "fid": fid_value,
                "game_username": game_username,
            }).mappings().first()
            mark("duplicate_check")

            if duplicate_row and duplicate_row.get("fid_exists"):
                return {
                    "status": "error",
                    "state": "USER_EXISTS",
                    "message": "A user with this FID already exists.",
                    "details": {"fid": fid_value}
                }

            # Check if email already exists
            email_to_check = data.get('contact', {}).get('electronicAddress', {}).get('emailId')
            if email_to_check:
                phone_to_check = data.get('contact', {}).get('electronicAddress', {}).get('mobileNo')
                if UserService.is_in_cooldown(email_to_check, phone_to_check):
                    return {
                        "status": "error",
                        "state": "COOLDOWN_ACTIVE",
                        "message": "This account identifier is in cooldown period.",
                        "details": {"email": email_to_check}
                    }
                if db.session.query(ContactInfo.id).filter_by(email=email_to_check).scalar():
                    return {
                        "status": "error",
                        "state": "EMAIL_EXISTS",
                        "message": "This email is already in use.",
                        "details": {"email": email_to_check}
                    }
            mark("email_check")

            # Check if username already exists
            if duplicate_row and duplicate_row.get("username_exists"):
                return {
                    "status": "error",
                    "state": "USERNAME_TAKEN",
                    "message": "This game username is already taken.",
                    "details": {"gameUserName": game_username}
                }

            # Parse date of birth
            dob = datetime.strptime(data['dob'], '%d-%b-%Y') if data.get('dob') else None
            referral_input = data.get('referral_code')
            mark("dob_parse")

            # Generate a unique referral code
            attempts = 0
            while True:
                attempts += 1
                if attempts > 20:
                    raise Exception("Unable to generate unique referral code")
                code = generate_referral_code()
                if not db.session.query(User.id).filter_by(referral_code=code).scalar():
                    break
            mark("referral_code_generation")

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
            # Add user to session first
            db.session.add(user)
            db.session.flush()  # Assigns user.id from DB without committing
            mark("user_insert_flush")

            # Add related objects using the relationship (now user.id is available)
            UserService._add_physical_address(user, data.get('contact', {}).get('physicalAddress'))
            UserService._add_contact_info(user, data.get('contact', {}).get('electronicAddress'))
            mark("contact_address_attach")

            if referral_input:
                referrer = User.query.filter_by(referral_code=referral_input).first()
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
            mark("referral_link")

            # Creation of Hash Wallet + PasswordManager in same transaction
            wallet = HashWallet(user_id=user.id, balance=0)
            db.session.add(wallet)

            _, password = generate_credentials()
            password_manager = PasswordManager(
                userid=user.id,
                password=password,
                parent_id=user.id,
                parent_type="user"
            )
            db.session.add(password_manager)
            mark("wallet_password_attach")

            db.session.commit()
            mark("commit")

            if timing_enabled:
                total_ms = (time.perf_counter() - t0) * 1000
                breakdown = ", ".join(f"{name}={value:.2f}ms" for name, value in timing_steps)
                current_app.logger.info(
                    "create_user_timing fid=%s user_id=%s total=%.2fms steps=[%s]",
                    fid_value,
                    user.id,
                    total_ms,
                    breakdown,
                )

            return user

        except ValueError as ve:
            db.session.rollback()
            current_app.logger.warning("Validation error: %s", str(ve))
            raise Exception(f"Validation error: {str(ve)}")

        except IntegrityError as ie:
            db.session.rollback()
            message = str(getattr(ie, "orig", ie)).lower()
            if "users_fid_key" in message or "fid" in message:
                return {
                    "status": "error",
                    "state": "USER_EXISTS",
                    "message": "A user with this FID already exists.",
                    "details": {"fid": data.get("fid")}
                }
            if "users_game_username_key" in message or "game_username" in message:
                return {
                    "status": "error",
                    "state": "USERNAME_TAKEN",
                    "message": "This game username is already taken.",
                    "details": {"gameUserName": data.get("gameUserName")}
                }
            if "contact_info" in message and "email" in message:
                return {
                    "status": "error",
                    "state": "EMAIL_EXISTS",
                    "message": "This email is already in use.",
                    "details": {"email": data.get("contact", {}).get("electronicAddress", {}).get("emailId")}
                }
            current_app.logger.error("Integrity error while creating user: %s", message)
            raise Exception("User creation failed due to integrity constraints.")

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
    def get_user_auth_payload_by_fid(fid):
        """
        Fetch only fields required by /users/fid auth response.
        Returns already-serialized payload to avoid ORM hydration overhead.
        """
        row = (
            db.session.query(
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
                PhysicalAddress.address_type,
                PhysicalAddress.addressLine1,
                PhysicalAddress.addressLine2,
                PhysicalAddress.pincode,
                PhysicalAddress.state,
                PhysicalAddress.country,
                PhysicalAddress.is_active,
                ContactInfo.phone,
                ContactInfo.email,
            )
            .outerjoin(
                PhysicalAddress,
                (PhysicalAddress.parent_id == User.id) & (PhysicalAddress.parent_type == "user"),
            )
            .outerjoin(
                ContactInfo,
                (ContactInfo.parent_id == User.id) & (ContactInfo.parent_type == "user"),
            )
            .filter(User.fid == fid)
            .first()
        )

        if not row:
            return None

        vouchers = (
            db.session.query(
                Voucher.code,
                Voucher.discount_percentage,
                Voucher.is_active,
                Voucher.created_at,
            )
            .filter(Voucher.user_id == row.id)
            .all()
        )

        return {
            "avatar_path": row.avatar_path or "",
            "id": row.id or "",
            "name": row.name or "",
            "gender": row.gender or "",
            "dob": row.dob.strftime('%d-%b-%Y') if row.dob else None,
            "gameUserName": row.game_username or "",
            "contact": {
                "physicalAddress": {
                    "address_type": str(row.address_type) if row.address_type else "home",
                    "addressLine1": str(row.addressLine1) if row.addressLine1 else "",
                    "addressLine2": str(row.addressLine2) if row.addressLine2 else "",
                    "pincode": str(row.pincode) if row.pincode else "",
                    "State": str(row.state) if row.state else "",
                    "Country": str(row.country) if row.country else "",
                    "is_active": bool(row.is_active) if row.is_active is not None else True,
                } if row.address_type or row.addressLine1 or row.pincode or row.state or row.country else {},
                "electronicAddress": {
                    "mobileNo": str(row.phone) if row.phone else "",
                    "emailId": str(row.email) if row.email else "",
                } if row.phone or row.email else {},
            },
            "referralCode": row.referral_code or "",
            "referralRewards": row.referral_rewards or 0,
            "vouchers": [
                {
                    "code": v.code,
                    "discountPercentage": v.discount_percentage,
                    "isActive": v.is_active,
                    "createdAt": v.created_at.strftime('%d-%b-%Y %H:%M') if v.created_at else "",
                }
                for v in vouchers
            ],
            "createdAt": row.created_at.strftime('%d-%b-%Y %H:%M') if row.created_at else None,
            "updatedAt": row.updated_at.strftime('%d-%b-%Y %H:%M') if row.updated_at else None,
        }

    @staticmethod
    def get_user_vouchers(user_id):
        """Get all vouchers for a user"""
        return Voucher.query.filter(Voucher.user_id == user_id).all()

    @staticmethod
    def is_in_cooldown(email, phone):
        """Check if email or phone is in cooldown period"""
        if not email and not phone:
            return False
        now = datetime.utcnow()
        predicates = []
        if email:
            predicates.append(DeletedUserCooldown.email == email)
        if phone:
            predicates.append(DeletedUserCooldown.phone == phone)
        cooldown = DeletedUserCooldown.query.filter(
            or_(*predicates),
            DeletedUserCooldown.expires_at > now
        ).first()
        return cooldown is not None
