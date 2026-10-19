import pytest
from cryptography.fernet import Fernet

from elblasy_api.security.vault import SecretVault, VaultError


def test_roundtrip_and_ciphertext_differs():
    v = SecretVault(Fernet.generate_key().decode())
    tok = v.encrypt("api-key")
    assert b"api-key" not in tok and v.decrypt(tok) == "api-key"


def test_rotation_keeps_old_tokens_readable():
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    tok = SecretVault(old).encrypt("s")
    v = SecretVault(f"{new},{old}")
    assert v.decrypt(tok) == "s"
    rotated = v.rotate(tok)
    assert SecretVault(new).decrypt(rotated) == "s"


def test_missing_or_wrong_key_fails():
    with pytest.raises(VaultError):
        SecretVault("")
    tok = SecretVault(Fernet.generate_key().decode()).encrypt("s")
    with pytest.raises(VaultError):
        SecretVault(Fernet.generate_key().decode()).decrypt(tok)
