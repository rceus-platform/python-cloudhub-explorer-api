"""Tests for the account service."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.account_service import get_provider_account, get_user_accounts


@pytest.fixture
def mock_db():
    """Fixture for a mock database session."""
    return MagicMock()


@pytest.fixture
def mock_settings():
    """Fixture for mock settings with environment fallbacks."""
    with patch("app.services.account_service.settings") as mock:
        mock.MEGA_USERNAME = "env_user"
        mock.MEGA_PASSWORD = "env_password"
        yield mock


@pytest.mark.usefixtures("mock_settings")
def test_get_user_accounts_with_env_fallback(mock_db):
    """Test retrieving user accounts with environment variable fallback."""
    # Mock DB returns no accounts
    mock_db.query.return_value.filter.return_value.all.return_value = []

    accounts = get_user_accounts(mock_db, user_id=1)

    assert len(accounts) == 1
    assert accounts[0].provider == "mega"
    assert accounts[0].access_token == "env_user"


@pytest.mark.usefixtures("mock_settings")
def test_get_user_accounts_prefers_db(mock_db):
    """Test that database accounts are preferred over environment fallbacks."""
    # Mock DB already has a mega account
    db_account = MagicMock()
    db_account.provider = "mega"
    db_account.access_token = "env_user"
    mock_db.query.return_value.filter.return_value.all.return_value = [db_account]

    accounts = get_user_accounts(mock_db, user_id=1)

    assert len(accounts) == 1
    assert accounts[0] == db_account


@pytest.mark.usefixtures("mock_settings")
def test_get_provider_account_env_fallback(mock_db):
    """Test retrieving a specific provider account with environment fallback."""
    # Mock DB returns None
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        None
    )

    account = get_provider_account(mock_db, user_id=1, provider="mega")

    assert account is not None
    assert account.provider == "mega"
    assert account.access_token == "env_user"


def test_get_provider_account_none_if_no_env(mock_db):
    """Test that None is returned if no DB account exists and environment vars are missing."""
    with patch("app.services.account_service.settings") as mock_s:
        mock_s.MEGA_USERNAME = None
        mock_s.MEGA_PASSWORD = None

        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            None
        )

        account = get_provider_account(mock_db, user_id=1, provider="mega")
        assert account is None
