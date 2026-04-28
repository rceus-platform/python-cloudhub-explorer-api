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
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
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
    provider = Column(String, nullable=False)  # e.g., 'gdrive', 'mega'
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    sid_or_token = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    storage_used = Column(BigInteger, default=0)
    storage_total = Column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint("email", "provider", name="ix_accounts_email_provider"),
    )

    user = relationship("User", back_populates="accounts")


class FileCache(Base):
    """Cached representation of file objects from external providers."""

    __tablename__ = "files_cache"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, index=True)
    provider = Column(String)
    type = Column(String)  # 'file', 'folder', 'video', 'image'
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
