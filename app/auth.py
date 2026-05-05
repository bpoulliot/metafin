from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import logging
import os
import secrets
import time

log = logging.getLogger(__name__)

_TOKEN_EXPIRY_SECS = 30 * 86400  # 30 days


def _session_key(secret: str, password_hash: str) -> str:
    # Fold the first 16 chars of the bcrypt hash into the signing key so that
    # changing the password automatically invalidates all existing sessions.
    return f"{secret}:{password_hash[:16]}" if password_hash else secret


# ---------------------------------------------------------------------------
# Password hashing — bcrypt preferred, sha256 fallback
# ---------------------------------------------------------------------------
try:
    import bcrypt as _bcrypt

    def hash_password(pw: str) -> str:
        return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt(rounds=12)).decode()

    def verify_password(pw: str, hashed: str) -> bool:
        try:
            return _bcrypt.checkpw(pw.encode(), hashed.encode())
        except Exception:
            return False

except ImportError:
    log.warning("bcrypt not available — using sha256 (install bcrypt for stronger hashing)")

    def hash_password(pw: str) -> str:  # type: ignore[misc]
        return "sha256:" + hashlib.sha256(pw.encode()).hexdigest()

    def verify_password(pw: str, hashed: str) -> bool:  # type: ignore[misc]
        if hashed.startswith("sha256:"):
            return secrets.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), hashed[7:])
        return False


# ---------------------------------------------------------------------------
# Stateless HMAC session tokens — survive container restarts
# ---------------------------------------------------------------------------


def _sign(payload: str, secret: str) -> str:
    return _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session(username: str, secret: str, password_hash: str = "") -> str:
    """Return a signed, time-limited session token."""
    key = _session_key(secret, password_hash)
    expires = int(time.time()) + _TOKEN_EXPIRY_SECS
    payload = f"{username}:{expires}"
    sig = _sign(payload, key)
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def get_session_user(token: str, secret: str, password_hash: str = "") -> str | None:
    """Verify token signature and expiry; return username or None."""
    key = _session_key(secret, password_hash)
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        # Format: <username>:<expires>:<sig> — split from right to handle colons in usernames
        last = decoded.rfind(":")
        if last < 0:
            return None
        sig = decoded[last + 1 :]
        rest = decoded[:last]
        sep = rest.rfind(":")
        if sep < 0:
            return None
        username = rest[:sep]
        expires_str = rest[sep + 1 :]
        if time.time() > int(expires_str):
            return None
        expected = _sign(f"{username}:{expires_str}", key)
        if not secrets.compare_digest(sig, expected):
            return None
        return username
    except Exception:
        return None


def delete_session(token: str) -> None:
    """No-op — stateless tokens are invalidated by deleting the cookie."""


# ---------------------------------------------------------------------------
# First-run bootstrap
# ---------------------------------------------------------------------------


def bootstrap(cfg_auth, save_fn) -> None:
    """
    Ensure a signing secret and admin account exist.
    Priority: existing values in config > METAFIN_USERNAME/PASSWORD env vars > auto-generated.
    """
    changed = False

    if not cfg_auth.secret_key:
        cfg_auth.secret_key = secrets.token_hex(32)
        changed = True

    if not cfg_auth.password_hash:
        username = os.environ.get("METAFIN_USERNAME", "") or cfg_auth.username or "admin"
        password = os.environ.get("METAFIN_PASSWORD", "")

        if not password:
            password = secrets.token_urlsafe(12)
            log.warning("=" * 60)
            log.warning("METAFIN FIRST RUN — auto-generated credentials:")
            log.warning("  Username : %s", username)
            log.warning("  Password : %s", password)
            log.warning("  Change these in Settings or set METAFIN_USERNAME / METAFIN_PASSWORD env vars")
            log.warning("=" * 60)

        cfg_auth.username = username
        cfg_auth.password_hash = hash_password(password)
        changed = True

    if changed:
        save_fn(cfg_auth)
