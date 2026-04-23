"""
Database Models Module

Responsibilities:
- Define SQLAlchemy ORM models for Users, Accounts, and File Cache
- Manage relationships between entities
"""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.session import Base


class User(Base):
    """User account model for authentication"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    accounts = relationship("Account", back_populates="user")


class Account(Base):
    """Cloud provider account model (Google Drive, Mega, etc.)"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    provider = Column(String, nullable=False)
    email = Column(String, nullable=True)
    label = Column(String, nullable=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)

    user = relationship("User", back_populates="accounts")


class FileCache(Base):
    """Cache model for cloud file metadata"""

    __tablename__ = "files_cache"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, index=True)
    provider = Column(String)
    type = Column(String)
    size = Column(Integer)
    parent_folder = Column(String)
