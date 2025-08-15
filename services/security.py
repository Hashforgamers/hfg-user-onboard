from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64

def encode_user(user_id: str, private_key_pem: str, public_key_pem: str) -> str:
    """
    Encode a user ID using RSA public key PEM string.
    Returns a base64-encoded string.
    """
    public_key = serialization.load_pem_public_key(public_key_pem.encode())

    encrypted = public_key.encrypt(
        str(user_id).encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    return base64.urlsafe_b64encode(encrypted).decode()


def decode_user(encoded_user: str, private_key_pem: str) -> str:
    """
    Decode the encrypted user ID using RSA private key PEM string.
    """
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)

    encrypted_bytes = base64.urlsafe_b64decode(encoded_user.encode())

    decrypted = private_key.decrypt(
        encrypted_bytes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    return decrypted.decode()
