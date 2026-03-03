import hashlib
import secrets

from django.conf import settings


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        (plaintext_key, prefix, hashed_key)
    """
    length = getattr(settings, "API_KEY_LENGTH", 40)
    prefix_length = getattr(settings, "API_KEY_PREFIX_LENGTH", 8)

    plaintext = secrets.token_hex(length // 2)
    prefix = plaintext[:prefix_length]
    hashed = hash_api_key(plaintext)
    return plaintext, prefix, hashed


def hash_api_key(plaintext: str) -> str:
    """SHA-256 hash of an API key."""
    return hashlib.sha256(plaintext.encode()).hexdigest()
