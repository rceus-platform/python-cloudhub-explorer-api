"""
Tests for core application functionality, including security and dependencies.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.dependencies import (
    get_current_user,
    get_current_user_dev,
    get_current_user_optional,
)


def test_verify_token_invalid():
    """Test verification of an invalid token."""
    from app.core.dependencies import verify_token

    with pytest.raises(HTTPException) as excinfo:
        verify_token("invalid")
    assert excinfo.value.status_code == 401


def test_get_current_user_success(db, test_user):
    """Test successful retrieval of current user from token."""
    _ = db
    with patch(
        "app.core.dependencies.verify_token", return_value={"user_id": test_user.id}
    ):
        user = get_current_user(None, "valid_token", db)
        assert user.id == test_user.id


def test_get_current_user_not_found(db):
    """Test dependency when user ID in token is not in DB."""
    _ = db
    with patch("app.core.dependencies.verify_token", return_value={"user_id": 999}):
        with pytest.raises(HTTPException) as excinfo:
            get_current_user(None, "token", db)
        assert excinfo.value.status_code == 404


def test_get_current_user_optional_success(db, test_user):
    """Test optional user dependency with a valid token."""
    _ = db
    with patch(
        "app.core.dependencies.verify_token", return_value={"user_id": test_user.id}
    ):
        user = get_current_user_optional(None, "token", db)
        assert user.id == test_user.id


def test_get_current_user_optional_not_found(db):
    """Test optional user dependency when user ID is not found."""
    _ = db
    # token for non-existent user id 999
    with patch("app.core.dependencies.verify_token", return_value={"user_id": 999}):
        assert get_current_user_optional(None, "token", db) is None


def test_get_current_user_optional_no_token(db):
    """Test optional user dependency with no token provided."""
    _ = db
    assert get_current_user_optional(None, None, db) is None


def test_get_current_user_dev():
    """Test the development-mode dummy user."""
    user = get_current_user_dev()
    assert user.id == 1


def test_get_db():
    """Test the database session generator."""
    from app.db.session import get_db

    db_gen = get_db()
    db_session = next(db_gen)
    assert db_session is not None
    # No need to close manually here as it's a mock DB in tests
