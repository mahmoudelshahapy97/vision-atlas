# app/core/security.py
"""Bearer-token check shared by every /v1 route."""

import hmac
from typing import Optional

from fastapi import Header, HTTPException, status

from app.core.config import config


def require_token(authorization: Optional[str] = Header(None)) -> None:
    if not config.models_token:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), config.models_token.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or wrong model server token.")
