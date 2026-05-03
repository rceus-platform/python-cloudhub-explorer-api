"""Tests for database initialization."""

from unittest.mock import MagicMock, patch

from app.db import models
from app.db.init_db import init_admin_user


def test_init_admin_user_creates_if_not_exists(mock_db):
    """Test that init_admin_user creates a new admin user if one doesn't exist."""

    with patch("app.db.init_db.settings") as mock_settings:
        mock_settings.SITE_PASSCODE = "secret"
        # Admin does not exist
        mock_db.query.return_value.filter.return_value.first.return_value = None

        init_admin_user(mock_db)

        # Check that user was added
        mock_db.add.assert_called_once()
        args = mock_db.add.call_args[0][0]
        assert isinstance(args, models.User)
        assert args.username == "admin"
        mock_db.commit.assert_called_once()


def test_init_admin_user_updates_if_exists(mock_db):
    """Test that init_admin_user updates the existing admin user's password."""

    with patch("app.db.init_db.settings") as mock_settings:
        mock_settings.SITE_PASSCODE = "new_secret"
        # Admin exists
        admin = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = admin

        init_admin_user(mock_db)

        # Check that user was updated, not added
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()
        assert admin.password_hash is not None
