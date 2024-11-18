from datetime import datetime
from db.extensions import db
from models.user import User
from models.contactInfo import ContactInfo
from models.physicalAddress import PhysicalAddress

class UserService:

    @staticmethod
    def create_user(data):
        try:
            # Parse the user details
            dob = datetime.strptime(data['dob'], '%d-%b-%Y') if data.get('dob') else None

            user = User(
                fid=data['fid'],
                avatar_path=data.get('avatar_path'),
                name=data['name'],
                gender=data.get('gender'),
                dob=dob,
                game_username=data['gameUserName']
            )

            # Add Physical Address
            if 'physicalAddress' in data['contact']:
                physical_address = data['contact']['physicalAddress']
                user.physical_address = PhysicalAddress(
                    address_type=physical_address['address_type'],
                    addressLine1=physical_address['addressLine1'],
                    addressLine2=physical_address.get('addressLine2'),
                    pincode=physical_address['pincode'],
                    state=physical_address['State'],
                    country=physical_address['Country'],
                    is_active=physical_address['is_active']
                )

            # Add Electronic Address
            if 'electronicAddress' in data['contact']:
                electronic_address = data['contact']['electronicAddress']
                user.contact_info = ContactInfo(
                    phone=electronic_address.get('mobileNo'),
                    email=electronic_address.get('emailId')
                )

            # Save the user in the database
            db.session.add(user)
            db.session.commit()

            return user

        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to create user: {str(e)}")

    @staticmethod
    def get_user(user_id):
        user = User.query.get(user_id)
        if not user:
            return None
        return user
