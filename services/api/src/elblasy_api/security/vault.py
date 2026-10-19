"""Encrypted secret storage for Odoo credentials (Fernet, rotation via MultiFernet)."""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class VaultError(Exception):
    pass


class SecretVault:
    def __init__(self, keys: str) -> None:
        raw = [k.strip() for k in keys.split(",") if k.strip()]
        if not raw:
            raise VaultError("no encryption key configured (ELBLASY_SECRET_KEYS)")
        try:
            self._fernet = MultiFernet([Fernet(k) for k in raw])
        except ValueError as exc:
            raise VaultError("invalid encryption key format") from exc

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken as exc:
            raise VaultError("secret cannot be decrypted") from exc

    def rotate(self, token: bytes) -> bytes:
        """Re-encrypt with the primary key."""
        return self._fernet.rotate(token)
