"""Tests for database session management."""

from unittest.mock import MagicMock, patch

from app.db.session import get_db


def test_get_db():
    """Test the database session generator."""

    mock_session = MagicMock()
    with patch("app.db.session.SessionLocal", return_value=mock_session):
        db_gen = get_db()
        db = next(db_gen)
        assert db == mock_session
        try:
            next(db_gen)
        except StopIteration:
            pass
        mock_session.close.assert_called_once()
