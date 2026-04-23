"""
Authentication API Router.

Handles user registration and login endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db import models, schemas
from app.db.session import get_db

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Helpers
def hash_password(password: str):
    """Hash a password using bcrypt."""
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400, detail="Password too long (max 72 characters)"
        )
    return pwd_context.hash(password)


def verify_password(plain, hashed):
    """Verify a plain password against its hashed version."""
    return pwd_context.verify(plain, hashed)


# Register
@router.post("/register", response_model=schemas.UserResponse)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    existing_user = (
        db.query(models.User).filter(models.User.username == user.username).first()
    )

    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    new_user = models.User(
        username=user.username, password_hash=hash_password(user.password)
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


# Login
@router.post("/login")
def login(user: schemas.UserLogin, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT access token."""
    db_user = (
        db.query(models.User).filter(models.User.username == user.username).first()
    )

    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": db_user.id})

    return {"access_token": token, "token_type": "bearer"}
