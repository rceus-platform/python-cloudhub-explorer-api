"""Core Security Module.

Responsibilities:
- Generate and verify JWT tokens for user sessions
- Handle token expiration and cryptographic signatures
- Provide centralized security utilities

Boundaries:
- Does not handle password hashing (delegated to auth route)
- Does not handle database user lookups (delegated to dependencies)
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings

# Security configuration (loaded from environment)
SECRET_KEY = (
    settings.SITE_PASSCODE
)  # Reusing site passcode as secret key or should use a dedicated ENV
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week


def create_access_token(data: dict[str, Any]) -> str:
    """Generate a signed JWT token with an expiration timestamp."""

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict[str, Any]:
    """Verify a JWT signature and return the decoded payload; raises 401 if invalid."""

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
