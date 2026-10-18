# app/core/security.py
"""Password hashing and JWTs (short-lived access tokens, rotated refresh tokens).

No database or FastAPI imports here, so this module can be unit tested on its
own. The route guards that use it live in app/api/deps.py; refresh sessions
are recorded by app/services/auth_service.py.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional, Tuple

import bcrypt
import jwt

from app.core.config import config

logger = logging.getLogger(__name__)

TokenType = Literal["access", "refresh", "media"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: Optional[str]) -> bool:
    """False (never an exception) for an empty or malformed hash."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _encode(claims: Dict[str, Any], typ: TokenType, lifetime: timedelta, jti: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {**claims, "typ": typ, "iat": now, "exp": now + lifetime, "jti": jti or uuid.uuid4().hex}
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def create_access_token(user_id: int, role: str, token_version: int = 1) -> str:
    """The bearer token. `tv` must match app_user.token_version, so bumping it
    (sign out everywhere, password change, deactivation) revokes every access
    token at once; see app/api/deps.py."""
    return _encode(
        {"sub": str(user_id), "role": role, "tv": token_version},
        "access",
        timedelta(minutes=config.access_token_expire_minutes),
    )


def create_refresh_token(user_id: int) -> Tuple[str, str]:
    """Identity only. Returns (token, jti); the caller records the jti in
    refresh_session so the token can be rotated and revoked."""
    jti = uuid.uuid4().hex
    token = _encode({"sub": str(user_id)}, "refresh", timedelta(days=config.refresh_token_expire_days), jti)
    return token, jti


def create_media_token(user_id: int, scope: str, resource_id: int, minutes: int) -> str:
    """A short-lived token for one resource, for URLs a browser opens without
    an Authorization header (a WebSocket, an <img>). Scope and resource are
    checked by decode_media_token, so a token for one camera opens nothing else."""
    return _encode(
        {"sub": str(user_id), "scope": scope, "rid": resource_id}, "media", timedelta(minutes=minutes)
    )


def decode_media_token(token: str, scope: str, resource_id: int) -> Optional[Dict[str, Any]]:
    payload = decode_token(token, "media")
    if not payload or payload.get("scope") != scope or payload.get("rid") != resource_id:
        return None
    return payload


def decode_token(token: str, expected: TokenType = "access") -> Optional[Dict[str, Any]]:
    """The token's claims, or None for anything invalid: expired, bad
    signature, garbage, the wrong token type, or a missing/non-numeric subject."""
    if not token or not isinstance(token, str):
        return None
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
    except jwt.PyJWTError as e:
        logger.debug("Rejected token: %s", e)
        return None
    if payload.get("typ") != expected or not payload.get("jti"):
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.isdigit():
        return None
    return payload
