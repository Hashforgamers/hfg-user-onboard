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
from sqlalchemy import or_, func
from sqlalchemy import text
from sqlalchemy.orm import joinedload, selectinload, load_only
from sqlalchemy.exc import IntegrityError
from concurrent.futures import ThreadPoolExecutor

_USER_POST_CREATE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="user-post-create")


class UserService:

    @staticmethod
    def _referral_code_from_user_id(user_id: int) -> str:
        chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        value = int(user_id)
        if value <= 0:
            return "U0"
        encoded = []
        while value:
            value, remainder = divmod(value, 36)
            encoded.append(chars[remainder])
        return "U" + "".join(reversed(encoded))
    
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
            email_to_check = data.get('contact', {}).get('electronicAddress', {}).get('emailId')
            normalized_email = str(email_to_check or "").strip().lower()
            has_email = bool(normalized_email)

            # Fast duplicate check in a single DB roundtrip for fid + username (+ email ownership when provided).
            duplicate_row = db.session.execute(text("""
                SELECT
                    EXISTS(SELECT 1 FROM users WHERE fid = :fid) AS fid_exists,
                    EXISTS(SELECT 1 FROM users WHERE game_username = :game_username) AS username_exists,
                    CASE
                        WHEN :has_email = FALSE THEN FALSE
                        ELSE EXISTS(
                            SELECT 1
                            FROM users u
                            JOIN contact_info c
                              ON c.parent_id = u.id
                             AND c.parent_type = 'user'
                            WHERE lower(c.email) = :email
                        )
                    END AS email_exists
            """), {
                "fid": fid_value,
                "game_username": game_username,
                "email": normalized_email,
                "has_email": has_email,
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
            if has_email:
                if duplicate_row and duplicate_row.get("email_exists"):
                    return {
                        "status": "error",
                        "state": "EMAIL_EXISTS",
                        "message": "This email is already in use.",
                        "details": {"email": normalized_email}
                    }
                phone_to_check = data.get('contact', {}).get('electronicAddress', {}).get('mobileNo')
                if UserService.is_in_cooldown(email_to_check, phone_to_check):
                    return {
                        "status": "error",
                        "state": "COOLDOWN_ACTIVE",
                        "message": "This account identifier is in cooldown period.",
                        "details": {"email": email_to_check}
                    }
                # Clean stale/orphan contact rows that reference non-existent users so they do not
                # cause perpetual EMAIL_EXISTS loops in signup flows.
                if bool(current_app.config.get("USER_CREATE_CLEAN_STALE_CONTACTS", False)):
                    stale_rows = (
                        db.session.query(ContactInfo.id)
                        .outerjoin(User, User.id == ContactInfo.parent_id)
                        .filter(
                            ContactInfo.parent_type == "user",
                            func.lower(ContactInfo.email) == normalized_email,
                            User.id.is_(None),
                        )
                        .all()
                    )
                    if stale_rows:
                        stale_ids = [int(r[0]) for r in stale_rows if r and r[0] is not None]
                        if stale_ids:
                            db.session.query(ContactInfo).filter(ContactInfo.id.in_(stale_ids)).delete(synchronize_session=False)
                            db.session.flush()
                            current_app.logger.warning(
                                "create_user cleaned stale user contact rows for email=%s count=%s",
                                normalized_email,
                                len(stale_ids),
                            )
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

            # Create the User object
            user = User(
                fid=data['fid'],
                avatar_path=data.get('avatar_path', ''),
                name=data.get('name', ''),
                gender=data.get('gender', ''),
                dob=dob,
                game_username=data['gameUserName'],
                parent_type="user",
                referral_code=None
            )
            # Add user to session first
            db.session.add(user)
            db.session.flush()  # Assigns user.id from DB without committing
            code = UserService._referral_code_from_user_id(int(user.id))
            user.referral_code = code
            mark("referral_code_generation")
            mark("user_insert_flush")

            # Add related objects using the relationship (now user.id is available)
            UserService._add_physical_address(user, data.get('contact', {}).get('physicalAddress'))
            UserService._add_contact_info(user, data.get('contact', {}).get('electronicAddress'))
            mark("contact_address_attach")

            # Keep the hot signup request minimal: defer side effects (wallet/password/referral)
            # to background finalization.
            mark("referral_link")
            mark("wallet_password_attach")
            db.session.commit()
            mark("commit")

            if bool(current_app.config.get("USER_CREATE_ASYNC_FINALIZE_ENABLED", True)):
                UserService.enqueue_post_create_finalize(
                    user_id=int(user.id),
                    own_referral_code=str(code),
                    referral_input=referral_input,
                    app_obj=current_app._get_current_object(),
                )
            else:
                UserService.finalize_user_post_create(
                    user_id=int(user.id),
                    own_referral_code=str(code),
                    referral_input=referral_input,
                )

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
    def enqueue_post_create_finalize(user_id: int, own_referral_code: str, referral_input: str = None, app_obj=None):
        app = app_obj
        if app is None:
            try:
                app = current_app._get_current_object()
            except Exception:
                app = None
        if app is None:
            return

        def _runner():
            with app.app_context():
                UserService.finalize_user_post_create(
                    user_id=int(user_id),
                    own_referral_code=str(own_referral_code or ""),
                    referral_input=str(referral_input or "").strip() or None,
                )

        _USER_POST_CREATE_EXECUTOR.submit(_runner)

    @staticmethod
    def finalize_user_post_create(user_id: int, own_referral_code: str, referral_input: str = None):
        """
        Idempotent finalization for post-signup side effects.
        Safe to run multiple times.
        """
        try:
            user = User.query.filter_by(id=int(user_id)).with_for_update().first()
            if not user:
                return

            # Ensure hash wallet exists.
            wallet_exists = db.session.query(HashWallet.id).filter_by(user_id=int(user_id)).scalar()
            if not wallet_exists:
                db.session.add(HashWallet(user_id=int(user_id), balance=0))

            # Ensure password manager exists.
            pm_exists = db.session.query(PasswordManager.id).filter_by(userid=str(user_id)).scalar()
            if not pm_exists:
                _, password = generate_credentials()
                db.session.add(
                    PasswordManager(
                        userid=str(user_id),
                        password=password,
                        parent_id=int(user_id),
                        parent_type="user",
                    )
                )

            # Apply referral linkage once.
            referral_input_norm = str(referral_input or "").strip()
            own_ref_norm = str(own_referral_code or "").strip()
            if referral_input_norm and not user.referred_by and referral_input_norm != own_ref_norm:
                referrer = User.query.filter_by(referral_code=referral_input_norm).with_for_update().first()
                if referrer and referrer.referral_code != own_ref_norm:
                    existing_track = db.session.query(ReferralTracking.id).filter_by(referred_user_id=int(user_id)).scalar()
                    user.referred_by = referral_input_norm
                    if not existing_track:
                        referrer.referral_rewards = int(referrer.referral_rewards or 0) + 1
                        db.session.add(
                            ReferralTracking(
                                referrer_code=referrer.referral_code,
                                referred_user_id=int(user_id),
                            )
                        )

            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning(
                "finalize_user_post_create failed user_id=%s err=%s",
                user_id,
                exc,
            )

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
        cooldown_days_cfg = current_app.config.get("USER_DELETION_COOLDOWN_DAYS", 30)
        cooldown_days = max(0, int(30 if cooldown_days_cfg is None else cooldown_days_cfg))
        if cooldown_days <= 0:
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
