import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_PREFIX = "enc:v1:"
HASHED_KEY_PREFIX = "hmac:v1:"


class SecretCipher:
    """Encrypt reversible upstream credentials with the application secret."""

    def __init__(self, application_secret: str):
        key = base64.urlsafe_b64encode(hashlib.sha256(application_secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_PREFIX}{token}"

    def decrypt(self, stored_value: str) -> tuple[str, bool]:
        """Return plaintext and whether the legacy value needs encryption."""
        if not stored_value.startswith(ENCRYPTED_PREFIX):
            return stored_value, True

        token = stored_value.removeprefix(ENCRYPTED_PREFIX)
        try:
            plaintext = self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(
                "Unable to decrypt an upstream credential. MCP_POOL_SECRET_KEY may have changed."
            ) from exc
        return plaintext, False


def hash_client_api_key(raw_key: str, application_secret: str) -> str:
    digest = hmac.new(
        application_secret.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{HASHED_KEY_PREFIX}{digest}"


def client_api_key_hint(raw_key: str) -> str:
    if len(raw_key) <= 12:
        return "****"
    return f"{raw_key[:8]}...{raw_key[-4:]}"
