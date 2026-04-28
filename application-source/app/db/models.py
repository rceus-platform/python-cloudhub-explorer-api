"""Database Models: defines SQLAlchemy ORM models and custom encrypted field types."""


import os

from cryptography.fernet import Fernet
from sqlalchemy import Column, ForeignKey, Integer, String, TypeDecorator
from sqlalchemy.orm import relationship

from app.db.session import Base


class EncryptedString(TypeDecorator):
    """SQLAlchemy TypeDecorator for transparent encryption/decryption."""

    impl = String

    cache_ok = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        key = os.environ.get("FERNET_KEY")
        if not key:
            # We don't raise here during module load to avoid breaking migrations/tools
            # but we will fail on actual encryption/decryption if missing.
            self.fernet = None
        else:
            self.fernet = Fernet(key.encode())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not self.fernet:
            raise RuntimeError("FERNET_KEY environment variable is not set")
        return self.fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if not self.fernet:
            raise RuntimeError("FERNET_KEY environment variable is not set")
        return self.fernet.decrypt(value.encode()).decode()

    def process_literal_param(self, value, dialect):
        return value

    @property
    def python_type(self):
        return str


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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)
    email = Column(String, nullable=True)
    label = Column(String, nullable=True)
    access_token = Column(EncryptedString, nullable=False)
    refresh_token = Column(EncryptedString, nullable=True)

    user = relationship("User", back_populates="accounts")


class FileCache(Base):
    """Cache model for cloud file metadata"""

    __tablename__ = "files_cache"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, index=True)
    provider = Column(String)
    file_type = Column("type", String)
    size = Column(Integer)
    parent_folder = Column(String)
