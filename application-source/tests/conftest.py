"""Pytest configuration and common fixtures."""

# pylint: disable=redefined-outer-name, wrong-import-position, invalid-name

import os

# Set dummy environment variables for testing
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-12345"
os.environ["FERNET_KEY"] = "6f_z-7_z-7_z-7_z-7_z-7_z-7_z-7_z-7_z-7_z-78="

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app

# Test Database Setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create a test client with overridden dependencies."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db):
    """Create a test user in the database."""
    from passlib.context import CryptContext

    from app.db import models

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = models.User(username="testuser", password_hash=pwd_context.hash("testpass"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def mock_accounts(db, test_user):
    """Provide some mock accounts for testing."""
    from app.db import models

    acc1 = models.Account(
        user_id=test_user.id,
        provider="gdrive",
        email="g@test.com",
        access_token="g_token",
    )
    acc2 = models.Account(
        user_id=test_user.id,
        provider="mega",
        email="m@test.com",
        access_token="m_user",
        refresh_token="m_pass",
    )
    db.add_all([acc1, acc2])
    db.commit()
    return [acc1, acc2]


@pytest.fixture
def authenticated_client(client, test_user):
    """Provide a client with the current user dependency overridden."""
    from app.core.dependencies import get_current_user, get_current_user_optional

    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_current_user_optional] = lambda: test_user
    return client
