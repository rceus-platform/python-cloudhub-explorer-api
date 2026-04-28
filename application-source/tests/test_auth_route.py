"""Tests for the authentication routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_db():
    """Fixture for a mock database session."""

    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


def test_register_success(mock_db):
    """Test successful user registration."""

    # Mock no existing user
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "newuser"
    mock_db.add.side_effect = lambda u: setattr(
        u, "id", 1
    )  # Simulate DB auto-increment
    mock_db.commit.return_value = None
    mock_db.refresh.side_effect = lambda u: setattr(u, "id", 1)

    response = client.post(
        "/auth/register",
        json={"username": "newuser", "password": "password123"},
    )

    assert response.status_code == 200
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_register_duplicate_user(mock_db):
    """Test user registration with an existing username."""

    # Mock existing user
    mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

    response = client.post(
        "/auth/register",
        json={"username": "existinguser", "password": "password123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "User already exists"


def test_login_success(mock_db):
    """Test successful user login."""

    # Mock user exists with hashed password
    from app.api.routes.auth import hash_password

    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "testuser"
    mock_user.password_hash = hash_password("correct_password")
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.api.routes.auth.create_access_token") as mock_token:
        mock_token.return_value = "fake-jwt-token"

        response = client.post(
            "/auth/login",
            json={"username": "testuser", "password": "correct_password"},
        )

        assert response.status_code == 200
        assert response.json()["access_token"] == "fake-jwt-token"


def test_login_invalid_credentials(mock_db):
    """Test user login with invalid credentials."""

    # Mock user exists but wrong password
    from app.api.routes.auth import hash_password

    mock_user = MagicMock()
    mock_user.password_hash = hash_password("correct_password")
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    response = client.post(
        "/auth/login",
        json={"username": "testuser", "password": "wrong_password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
