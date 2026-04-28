"""API Dependencies: resolves current user from tokens and handles authentication requirements."""


import logging
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db import models
from app.db.session import get_db

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def get_current_user_dev():
    """Return a dummy user for development environments"""

    class DummyUser:  # pylint: disable=too-few-public-methods
        """Dummy user for development environments"""

        user_id = 1

        @property
        def id(self):
            """Compatibility accessor for shadowed 'id' attribute."""
            return self.user_id

    return DummyUser()


def _resolve_raw_token(
    credentials: Optional[HTTPAuthorizationCredentials],
    token: Optional[str],
) -> Optional[str]:
    """Extract the raw JWT string from whichever source is present."""

    if credentials is not None:
        return credentials.credentials
    if token is not None:
        return token
    return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
):
    """Resolve the current user; raises HTTP 401 if no valid token is supplied."""

    raw_token = _resolve_raw_token(credentials, token)

    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_token(raw_token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    except Exception as exc:
        # pylint: disable=broad-exception-caught
        logger.exception("Unexpected error during token verification")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> Optional[Any]:
    """Like get_current_user but returns None instead of raising 401."""

    raw_token = _resolve_raw_token(credentials, token)
    if raw_token is None:
        return None

    try:
        payload = verify_token(raw_token)
        user_id = payload.get("user_id")
        if not user_id:
            return None
        return db.query(models.User).filter(models.User.id == user_id).first()
    except Exception:  # pylint: disable=broad-exception-caught
        return None
