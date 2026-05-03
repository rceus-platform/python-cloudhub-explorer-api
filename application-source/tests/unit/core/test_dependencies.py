"""Unit tests for the core dependencies module."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core import dependencies
from app.db import models


def test_get_current_user_valid_token():
    """Test get_current_user with a valid token."""
    mock_db = MagicMock()
    with patch("app.core.dependencies.verify_token", return_value={"user_id": 1}):
        mock_user = models.User(id=1, username="test@example.com")
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        user = dependencies.get_current_user(credentials=None, token="valid_token", db=mock_db)
        assert user == mock_user


def test_get_current_user_invalid_token():
    """Test get_current_user with an invalid token."""
    with patch("app.core.dependencies.verify_token", side_effect=HTTPException(status_code=401)):
        with pytest.raises(HTTPException) as exc:
            dependencies.get_current_user(credentials=None, token="invalid")
        assert exc.value.status_code == 401


def test_get_current_user_not_found():
    """Test get_current_user when user is not in DB."""
    mock_db = MagicMock()
    with patch("app.core.dependencies.verify_token", return_value={"user_id": 999}):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc:
            dependencies.get_current_user(credentials=None, token="valid", db=mock_db)
        assert exc.value.status_code == 404


def test_get_current_user_optional():
    """Test get_current_user_optional."""
    mock_db = MagicMock()
    # Case: No token
    user = dependencies.get_current_user_optional(credentials=None, token=None)
    assert user is None

    # Case: Valid token
    mock_user = models.User(id=1, username="test@example.com")
    with patch("app.core.dependencies.verify_token", return_value={"user_id": 1}):
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        user = dependencies.get_current_user_optional(credentials=None, token="valid", db=mock_db)
        assert user == mock_user

    # Case: Invalid token (should return None, not raise)
    with patch("app.core.dependencies.verify_token", side_effect=HTTPException(status_code=401)):
        user = dependencies.get_current_user_optional(credentials=None, token="invalid", db=mock_db)
        assert user is None


def test_get_db():
    """Test get_db generator."""
    mock_session_local = MagicMock()
    with patch("app.db.session.SessionLocal", mock_session_local):
        db_gen = dependencies.get_db()
        db = next(db_gen)
        assert db == mock_session_local.return_value
        db_gen.close()  # Ensure it's closed
        # Or more properly:
        try:
            next(db_gen)
        except StopIteration:
            pass
        mock_session_local.return_value.close.assert_called_once()


def test_get_current_user_dev():
    """Test the development dummy user dependency."""
    user = dependencies.get_current_user_dev()
    assert user.id == 1


def test_get_current_user_header():
    """Test get_current_user using the Authorization header (HTTPBearer)."""
    mock_db = MagicMock()
    mock_creds = MagicMock()
    mock_creds.credentials = "header_token"
    with patch("app.core.dependencies.verify_token", return_value={"user_id": 1}):
        mock_user = models.User(id=1, username="u")
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        user = dependencies.get_current_user(credentials=mock_creds, token=None, db=mock_db)
        assert user == mock_user


def test_get_current_user_no_token():
    """Test get_current_user raises 401 when no token is provided."""
    with pytest.raises(HTTPException) as exc:
        dependencies.get_current_user(credentials=None, token=None)
    assert exc.value.status_code == 401


def test_get_current_user_invalid_payload():
    """Test get_current_user with token missing user_id in payload."""
    with patch("app.core.dependencies.verify_token", return_value={}):
        with pytest.raises(HTTPException) as exc:
            dependencies.get_current_user(credentials=None, token="token")
        assert exc.value.status_code == 401
        assert "Invalid token" in exc.value.detail


def test_get_current_user_optional_invalid_payload():
    """Test get_current_user_optional with token missing user_id."""
    with patch("app.core.dependencies.verify_token", return_value={}):
        user = dependencies.get_current_user_optional(credentials=None, token="token")
        assert user is None
