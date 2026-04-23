"""
Pydantic Schemas for the API.

Contains request and response schemas.
"""

from pydantic import BaseModel, ConfigDict

# -------------------------
# Auth Schemas
# -------------------------


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    username: str
    password: str


class UserLogin(BaseModel):
    """Schema for user login credentials."""

    username: str
    password: str


class UserResponse(BaseModel):
    """Schema for user responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
