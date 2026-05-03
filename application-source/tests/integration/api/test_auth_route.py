"""Tests for authentication routes."""

from unittest.mock import patch

from app.db import models


def test_register_success(client, mock_db):
    """Test successful user registration."""

    mock_db._query_results[models.User] = []

    def mock_refresh(obj):
        obj.id = 1
        return obj

    mock_db.refresh.side_effect = mock_refresh

    payload = {"username": "newuser", "password": "password123"}
    response = client.post("/auth/register", json=payload)

    assert response.status_code == 200
    assert response.json()["username"] == "newuser"
    assert response.json()["id"] == 1
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_register_existing(client, mock_db):
    """Test registration with an existing username."""

    mock_db._query_results[models.User] = [models.User(username="existing")]

    payload = {"username": "existing", "password": "password123"}
    response = client.post("/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "User already exists"


def test_login_success(client, mock_db):
    """Test successful user login."""

    user = models.User(id=1, username="test", password_hash="hashed")
    mock_db._query_results[models.User] = [user]

    with patch("app.api.routes.auth.verify_password", return_value=True):
        with patch("app.api.routes.auth.create_access_token", return_value="fake_token"):
            payload = {"username": "test", "password": "password123"}
            response = client.post("/auth/login", json=payload)

            assert response.status_code == 200
            assert response.json()["access_token"] == "fake_token"


def test_login_invalid_credentials(client, mock_db):
    """Test login with invalid credentials."""

    mock_db._query_results[models.User] = []

    payload = {"username": "wrong", "password": "password123"}
    response = client.post("/auth/login", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
