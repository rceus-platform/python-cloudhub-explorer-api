"""Core Dependencies Module.

Responsibilities:
- Provide FastAPI dependencies for user authentication
- Resolve current user from JWT tokens in headers or query parameters
- Handle authenticated and optional-authentication scenarios

Boundaries:
- Does not handle token generation (delegated to core.security)
- Does not handle raw database queries (delegated to models/db)
"""

from typing import Any
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db import models
from app.db.session import get_db

security = HTTPBearer(auto_error=False)


def get_current_user_dev() -> Any:
    """Mock user dependency for local development and testing."""

    class DummyUser:
        """Dummy user object for development purposes."""

        id = 1

    return DummyUser()


def _resolve_raw_token(
    credentials: HTTPAuthorizationCredentials | None,
    token: str | None,
) -> str | None:
    """Extract the raw JWT string from either the Authorization header or query string."""

    if credentials is not None:
        return credentials.credentials
    if token is not None:
        return token
    return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str | None = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> models.User:
    """Strict dependency requiring a valid JWT; raises 401 if missing or invalid."""

    raw_token = _resolve_raw_token(credentials, token)

    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(raw_token)
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str | None = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> models.User | None:
    """Optional dependency that returns None instead of raising 401 if unauthenticated."""

    raw_token = _resolve_raw_token(credentials, token)
    if raw_token is None:
        return None

    try:
        payload = verify_token(raw_token)
        user_id = payload.get("user_id")
        if not user_id:
            return None
        return db.query(models.User).filter(models.User.id == user_id).first()
    except HTTPException:
        return None
