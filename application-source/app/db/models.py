"""Database Models Module.

Responsibilities:
- Define SQLAlchemy ORM models for the application schema
- Establish relationships and constraints between entities
- Provide a blueprint for database tables (Users, Accounts, History, etc.)

Boundaries:
- Does not handle database sessions or connections (delegated to db.session)
- Does not handle data validation for APIs (delegated to db.schemas)

Compliance Note:
- Shadows built-in 'id' and 'type' names (Rule 173). Flagged for future migration.
"""

import datetime
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


class User(Base):
    """Primary user account model with authentication credentials."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    accounts = relationship("Account", back_populates="user")


class Account(Base):
    """External cloud provider account linked to a user."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String, index=True)
    # e.g., 'gdrive', 'mega'
    provider = Column(String, nullable=False)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    sid_or_token = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    storage_used = Column(BigInteger, default=0)
    storage_total = Column(BigInteger, default=0)
    expires_at = Column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("email", "provider", name="ix_accounts_email_provider"),)

    user = relationship("User", back_populates="accounts")


class FileCache(Base):
    """Cached representation of file objects from external providers."""

    __tablename__ = "files_cache"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, index=True)
    provider = Column(String)
    # 'file', 'folder', 'video', 'image'
    type = Column(String)
    size = Column(Integer)
    parent_folder = Column(String)


class WatchHistory(Base):
    """User-specific playback progress and history for media files."""

    __tablename__ = "watch_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    file_id = Column(String, index=True, nullable=False)
    current_time = Column(Integer, default=0)
    duration = Column(Integer, default=0)
    last_watched = Column(Integer)


class FileMetadata(Base):
    """Persistent metadata and extraction results for files (thumbnails, dimensions)."""

    __tablename__ = "file_metadata"

    file_id = Column(String, primary_key=True, index=True)
    provider = Column(String, nullable=False)
    name = Column(String)
    size = Column(Integer)
    thumbnail_path = Column(String)
    duration = Column(String)
    width = Column(Integer)
    height = Column(Integer)
    created_at = Column(Integer)
    updated_at = Column(Integer)


class FolderCache(Base):
    """Persistent cache for merged folder listings."""

    __tablename__ = "folder_cache"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    folder_id = Column(String, index=True)
    data = Column(JSON)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Unified File System Models (new feature set)
# ---------------------------------------------------------------------------

# Association table for the many-to-many relationship between items and tags.
# Industry standard pattern: avoids a full ORM model for a pure join table.
item_tags = Table(
    "item_tags",
    Base.metadata,
    Column(
        "item_id", String, ForeignKey("file_system_items.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class FileSystemItem(Base):
    """Unified model representing both files and folders in the virtual file system.

    This replaces the split FileCache / FileMetadata pattern with a single
    self-referential table capable of expressing arbitrary directory trees.
    """

    __tablename__ = "file_system_items"

    # UUID primary key decoupled from the cloud provider's own IDs
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    # Stable reference back to the cloud-provider file/folder ID
    provider_id = Column(String, index=True, nullable=True)
    provider = Column(String, nullable=False)  # 'gdrive', 'mega', 'local'
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    name = Column(String, nullable=False, index=True)
    # Self-referential parent; NULL means root
    parent_id = Column(
        String, ForeignKey("file_system_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_folder = Column(Boolean, nullable=False, default=False)

    mime_type = Column(String, nullable=True)
    # For files: actual size; for folders: cached aggregated size of all descendants
    size = Column(BigInteger, nullable=True, default=0)
    extension = Column(String, nullable=True)

    # Cloud provider-specific raw metadata (JSON blob for extensibility)
    extra_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Relationships
    children = relationship(
        "FileSystemItem",
        primaryjoin="FileSystemItem.parent_id == FileSystemItem.id",
        foreign_keys="[FileSystemItem.parent_id]",
        lazy="dynamic",
    )
    tags = relationship("Tag", secondary=item_tags, back_populates="items")
    share_links = relationship("ShareLink", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "provider", "user_id", name="ix_fsi_provider_id_provider_user"
        ),
    )


class Tag(Base):
    """Reusable label that can be associated with multiple file system items."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)

    items = relationship("FileSystemItem", secondary=item_tags, back_populates="tags")

    __table_args__ = (UniqueConstraint("user_id", "name", name="ix_tags_user_id_name"),)


class ShareLink(Base):
    """Secure, optionally time-limited and password-protected share link for a file/folder."""

    __tablename__ = "share_links"

    id = Column(Integer, primary_key=True, index=True)
    # URL-safe random hash used as the public token (e.g., /share/<hash>)
    hash = Column(String, unique=True, nullable=False, index=True)
    item_id = Column(String, ForeignKey("file_system_items.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Permission level: 'view' or 'edit'
    permission = Column(String, nullable=False, default="view")
    # Optional expiry; NULL means link never expires
    expires_at = Column(DateTime, nullable=True)
    # bcrypt hash of the access password; NULL means no password required
    password_hash = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    item = relationship("FileSystemItem", back_populates="share_links")
