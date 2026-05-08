"""Database Schemas Module.

Responsibilities:
- Define Pydantic models for API request and response validation
- Provide type safety and serialization for database objects
- Decouple internal database models from external API contracts

Boundaries:
- Does not handle database logic or persistence (delegated to db.models)
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class AccountResponse(BaseModel):
    """Schema for linked account information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    email: str | None = None
    provider: str
    is_active: bool
    storage_used: int
    storage_total: int


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
    current_time: float
    duration: float


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

    current_time: float
    duration: float




class SuccessStatusResponse(BaseModel):
    """Schema for generic success status responses."""

    status: str


# ---------------------------------------------------------------------------
# File System Item Schemas
# ---------------------------------------------------------------------------

class FileSystemItemBase(BaseModel):
    """Shared base fields for file system items."""

    name: str
    is_folder: bool
    mime_type: str | None = None
    size: int | None = None
    extension: str | None = None
    provider: str
    provider_id: str | None = None
    parent_id: str | None = None


class FileSystemItemCreate(FileSystemItemBase):
    """Schema for creating a new file or folder record."""

    pass


class TagResponse(BaseModel):
    """Schema for a single tag."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ShareLinkResponse(BaseModel):
    """Schema for a share link."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    hash: str
    permission: str
    expires_at: str | None = None


class FileSystemItemResponse(FileSystemItemBase):
    """Schema for reading a file system item (includes derived/relational fields)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    tags: list[TagResponse] = []
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# CRUD Operation Request Schemas
# ---------------------------------------------------------------------------

class ItemMoveRequest(BaseModel):
    """Schema for moving one or more items to a new parent folder."""

    item_ids: list[str]
    destination_id: str | None = None  # None = move to root


class ItemCopyRequest(BaseModel):
    """Schema for copying one or more items."""

    item_ids: list[str]
    destination_id: str | None = None  # None = copy to root


class ItemRenameRequest(BaseModel):
    """Schema for renaming a single file or folder."""

    name: str


class ItemDeleteRequest(BaseModel):
    """Schema for bulk deletion of items."""

    item_ids: list[str]


# ---------------------------------------------------------------------------
# Tag & Share Link Schemas
# ---------------------------------------------------------------------------

class TagUpdateRequest(BaseModel):
    """Schema for replacing the full tag set on an item."""

    tags: list[str]  # Tag names; new tags are created, orphaned ones removed


class ShareLinkCreate(BaseModel):
    """Schema for creating a new share link."""

    item_id: str
    permission: str = "view"            # 'view' | 'edit'
    expires_at: str | None = None       # ISO-8601 datetime string; None = no expiry
    password: str | None = None         # Plain-text; stored as bcrypt hash


class ShareLinkVerify(BaseModel):
    """Schema for verifying access to a password-protected share link."""

    password: str


# ---------------------------------------------------------------------------
# Folder Creation & File Upload Schemas
# ---------------------------------------------------------------------------

class FolderCreateRequest(BaseModel):
    """Schema for creating a new folder."""

    name: str
    parent_id: str | None = None


class TextFileCreateRequest(BaseModel):
    """Schema for creating a plain-text file with inline content."""

    name: str
    content: str
    parent_id: str | None = None


# ---------------------------------------------------------------------------
# Search & Filter Engine Schemas
# ---------------------------------------------------------------------------

class FilterParams(BaseModel):
    """Parsed, validated filter parameters for the item listing endpoint."""

    search: str | None = None
    tags: list[str] = []
    tag_logic: str = "or"               # 'and' | 'or'
    mime_type: str | None = None
    min_size: int | None = None
    max_size: int | None = None
    date_from: str | None = None        # ISO-8601 date string
    date_to: str | None = None
    sort_by: str = "name"               # 'name' | 'size' | 'modified_at'
    sort_order: str = "asc"             # 'asc' | 'desc'
