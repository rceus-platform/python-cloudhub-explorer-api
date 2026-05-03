"""Tests for the core security module."""

import pytest
from fastapi import HTTPException

from app.core import security


def test_hash_and_verify_password():
    """Test password hashing and verification logic."""

    pwd = "my_password"
    hashed = security.hash_password(pwd)
    assert hashed != pwd
    assert security.verify_password(pwd, hashed) is True
    assert security.verify_password("wrong", hashed) is False


def test_hash_password_too_long():
    """Test that hashing a very long password raises an error."""

    with pytest.raises(HTTPException) as exc:
        security.hash_password("a" * 100)
    assert exc.value.status_code == 400


def test_create_and_verify_token():
    """Test JWT token creation and verification."""

    data = {"user_id": 123}
    token = security.create_access_token(data)
    assert isinstance(token, str)

    payload = security.verify_token(token)
    assert payload["user_id"] == 123
    assert "exp" in payload


def test_verify_token_invalid():
    """Test that verifying an invalid token raises an error."""

    with pytest.raises(HTTPException) as exc:
        security.verify_token("invalid_token")
    assert exc.value.status_code == 401
