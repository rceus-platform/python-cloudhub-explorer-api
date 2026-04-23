"""
Tests for the Accounts API router.
"""

from unittest.mock import MagicMock, patch
from app.db import models


def test_get_accounts_empty(authenticated_client):
    """Test getting accounts when none exist."""
    response = authenticated_client.get("/accounts/")
    assert response.status_code == 200
    assert response.json() == []


def test_add_account_manual(authenticated_client, db, test_user):
    """Test manually adding an account."""
    response = authenticated_client.post(
        "/accounts/add?provider=gdrive&access_token=test_token"
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Account added successfully"

    # Verify in DB
    acc = db.query(models.Account).filter(models.Account.user_id == test_user.id).first()
    assert acc.provider == "gdrive"
    assert acc.access_token == "test_token"


@patch("app.api.routes.accounts.Flow")
def test_google_login(mock_flow, authenticated_client):
    """Test Google login flow initiation."""
    mock_instance = MagicMock()
    mock_flow.from_client_config.return_value = mock_instance
    mock_instance.authorization_url.return_value = ("http://auth.url", "state")

    response = authenticated_client.get("/accounts/google/login")
    assert response.status_code == 200
    assert response.json()["auth_url"] == "http://auth.url"


@patch("app.api.routes.accounts.Flow")
def test_google_callback(mock_flow, authenticated_client, db):
    """Test Google login callback handling."""
    mock_instance = MagicMock()
    mock_flow.from_client_config.return_value = mock_instance
    mock_instance.credentials.token = "new_access_token"
    mock_instance.credentials.refresh_token = "new_refresh_token"

    mock_session = MagicMock()
    mock_instance.authorized_session.return_value = mock_session
    mock_session.get.return_value.json.return_value = {"email": "test@gmail.com"}

    response = authenticated_client.get("/accounts/google/callback?code=test_code")
    assert response.status_code == 200
    assert "Google Drive connected successfully" in response.json()["message"]

    acc = db.query(models.Account).filter(models.Account.email == "test@gmail.com").first()
    assert acc.access_token == "new_access_token"
    assert acc.provider == "gdrive"


@patch("app.api.routes.accounts.get_mega_session")
def test_mega_login_success(mock_get_mega, authenticated_client, db):
    """Test successful MEGA login."""
    mock_get_mega.return_value = MagicMock()

    response = authenticated_client.post(
        "/accounts/mega/login",
        json={"email": "mega@test.com", "password": "megapassword", "label": "My Mega"}
    )
    assert response.status_code == 200
    assert "Mega connected successfully" in response.json()["message"]

    acc = db.query(models.Account).filter(models.Account.email == "mega@test.com").first()
    assert acc.provider == "mega"
    assert acc.refresh_token == "megapassword" # Password is stored in refresh_token for Mega


@patch("app.api.routes.accounts.get_mega_session")
def test_mega_login_failure(mock_get_mega, authenticated_client):
    """Test failed MEGA login."""
    mock_get_mega.return_value = None

    response = authenticated_client.post(
        "/accounts/mega/login",
        json={"email": "wrong@test.com", "password": "wrongpassword"}
    )
    assert response.status_code == 401
    assert "Could not authenticate with Mega" in response.json()["detail"]
