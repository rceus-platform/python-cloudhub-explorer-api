"""Database Schemas Module.

Responsibilities:
- Define Pydantic models for API request and response validation
- Provide type safety and serialization for database objects
- Decouple internal database models from external API contracts

Boundaries:
- Does not handle database logic or persistence (delegated to db.models)
"""

from typing import Any

from pydantic import BaseModel


class UserCreate(BaseModel):
    """Schema for creating a new user account."""

    username: str
    password: str


class UserLogin(BaseModel):
    """Schema for user authentication requests."""

    username: str
    password: str


class UserResponse(BaseModel):
    """Schema for public user profile information."""

    id: int
    username: str

    class Config:
        """Pydantic configuration for ORM compatibility."""

        from_attributes = True


class AccountResponse(BaseModel):
    """Schema for linked account information."""

    id: int
    user_id: int
    email: str | None = None
    provider: str
    is_active: bool
    storage_used: int
    storage_total: int

    class Config:
        """Pydantic configuration for ORM compatibility."""

        from_attributes = True


class AccountAddRequest(BaseModel):
    """Schema for adding a new cloud account (MEGA)."""

    email: str
    password: str
    provider: str = "mega"


class AuthUrlResponse(BaseModel):
    """Schema for OAuth authorization URL response."""

    auth_url: str


class SuccessMessageResponse(BaseModel):
    """Schema for generic success responses."""

    message: str


class FileListResponse(BaseModel):
    """Schema for file listing response."""

    folder_id: str
    files: list[dict[str, Any]]


class ThumbnailUpdateResponse(BaseModel):
    """Schema for thumbnail update response."""

    success: bool
    updated_at: int


class VideoProgressResponse(BaseModel):
    """Schema for video progress request."""

    file_id: str
    current_time: int
    duration: int


class VideoProgressUpdateResponse(BaseModel):
    """Schema for video progress update response."""

    success: bool
    message: str


class TokenResponse(BaseModel):
    """Schema for token generation response."""

    access_token: str
    token_type: str


class VideoStateResponse(BaseModel):
    """Schema for video playback state response."""

    current_time: int
    duration: int


class SuccessStatusResponse(BaseModel):
    """Schema for generic success status responses."""

    status: str
