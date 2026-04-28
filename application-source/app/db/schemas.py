"""Pydantic Schemas: defines request and response models for the API."""

from pydantic import BaseModel, ConfigDict


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


class AccountOut(BaseModel):
    """Safe schema for account response (excludes sensitive tokens)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    email: str | None = None
    label: str | None = None


class AccountCreate(BaseModel):
    """Schema for manually adding an account."""

    provider: str
    access_token: str
