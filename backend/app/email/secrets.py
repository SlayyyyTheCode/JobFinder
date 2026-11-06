"""Token encryption. Fernet key lives in the OS credential store (Windows Credential Manager),
separate from the database (spec §15.2)."""
import logging

from cryptography.fernet import Fernet

from ..config import get_settings

log = logging.getLogger("jobpilot.secrets")
SERVICE, KEY_NAME = "JobPilot", "token-encryption-key"
_fernet: Fernet | None = None


def _key() -> bytes:
    try:
        import keyring
        k = keyring.get_password(SERVICE, KEY_NAME)
        if not k:
            k = Fernet.generate_key().decode()
            keyring.set_password(SERVICE, KEY_NAME, k)
        return k.encode()
    except Exception as e:  # noqa: BLE001 — no keyring backend available
        log.warning("OS keyring unavailable (%s); falling back to key file in data dir", e)
        p = get_settings().data_dir / ".token.key"
        if not p.exists():
            p.write_bytes(Fernet.generate_key())
        return p.read_bytes()


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def encrypt(s: str) -> str:
    return fernet().encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return fernet().decrypt(s.encode()).decode() if s else ""
