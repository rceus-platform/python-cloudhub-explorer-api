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
from passlib.context import CryptContext

from app.core.config import settings

# Security configuration (loaded from environment)
SECRET_KEY = (
    settings.SECRET_KEY or settings.SITE_PASSCODE
)  # Preferred SECRET_KEY, fallback to SITE_PASSCODE for simple setups
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""

    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 characters)")
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain text password against a stored hash."""

    return pwd_context.verify(plain, hashed)


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
