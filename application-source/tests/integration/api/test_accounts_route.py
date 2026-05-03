"""Integration tests for the accounts route."""

from unittest.mock import MagicMock, patch

from app.db import models


def test_get_accounts(client, mock_db):
    """Test retrieving linked accounts."""
    # Mock account retrieval
    acc = models.Account(
        id=1,
        user_id=1,
        email="test@mega.nz",
        provider="mega",
        access_token="t1",
        refresh_token="p1",
        storage_used=100,
        storage_total=1000,
        is_active=True,
    )
    mock_db._query_results[models.Account] = [acc]

    # Mock mega session and info
    with patch("app.api.routes.accounts.get_mega_session") as mock_get_mega:
        mock_get_mega.return_value = MagicMock()
        with patch("app.api.routes.accounts.get_mega_info") as mock_get_info:
            mock_get_info.return_value = {"storage_used": 200, "storage_total": 2000}

            response = client.get("/accounts/")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["email"] == "test@mega.nz"
            assert data[0]["storage_used"] == 200


def test_add_mega_account(client, mock_db):
    """Test adding a new MEGA account."""
    # Mock successful login and info
    with patch("app.api.routes.accounts.get_mega_session") as mock_get_mega:
        mock_get_mega.return_value = MagicMock()
        with patch("app.api.routes.accounts.get_mega_info") as mock_get_info:
            mock_get_info.return_value = {"storage_used": 100, "storage_total": 1000}

            # Mock no existing account
            mock_db._query_results[models.Account] = []

            payload = {"provider": "mega", "email": "new@mega.nz", "password": "pass"}
            response = client.post("/accounts/add", json=payload)

            assert response.status_code == 200
            assert response.json() == {"message": "MEGA account linked successfully"}
            mock_db.add.assert_called_once()


def test_sync_thumbnails_trigger(client):
    """Test triggering the thumbnail synchronization job."""
    # Patch the service directly since it's imported locally in the route
    with patch("app.services.background_service.sync_thumbnails") as mock_bg_sync:
        response = client.post("/accounts/sync")
        assert response.status_code == 200
        assert "Thumbnail sync job started" in response.json()["message"]
        mock_bg_sync.assert_called_once()


def test_get_accounts_gdrive(client, mock_db):
    """Test retrieving linked GDrive accounts."""
    acc = models.Account(id=2, user_id=1, email="test@gmail.com", provider="gdrive")
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.accounts.get_gdrive_info") as mock_info:
        mock_info.return_value = {
            "email": "test@gmail.com",
            "storage_used": 500,
            "storage_total": 5000,
        }
        response = client.get("/accounts/")
        assert response.status_code == 200
        assert response.json()[0]["storage_total"] == 5000


def test_add_mega_account_invalid(client):
    """Test adding a MEGA account with invalid credentials."""
    with patch("app.api.routes.accounts.get_mega_session", return_value=None):
        payload = {"provider": "mega", "email": "bad@mega.nz", "password": "wrong"}
        response = client.post("/accounts/add", json=payload)
        assert response.status_code == 401


def test_add_mega_account_existing(client, mock_db):
    """Test updating an existing MEGA account."""
    acc = models.Account(id=1, user_id=1, email="old@mega.nz", provider="mega")
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.accounts.get_mega_session", return_value=MagicMock()):
        with patch(
            "app.api.routes.accounts.get_mega_info",
            return_value={"storage_used": 1, "storage_total": 10},
        ):
            payload = {"provider": "mega", "email": "old@mega.nz", "password": "new_pass"}
            response = client.post("/accounts/add", json=payload)
            assert response.status_code == 200
            assert acc.refresh_token == "new_pass"


def test_disconnect_account_not_found(client, mock_db):
    """Test disconnecting a non-existent account."""
    mock_db._query_results[models.Account] = []
    response = client.delete("/accounts/999")
    assert response.status_code == 404


def test_get_sync_status(client):
    """Test retrieving the synchronization status."""
    from app.services.background_service import ThumbnailSyncManager

    ThumbnailSyncManager._is_running = True
    response = client.get("/accounts/sync/status")
    assert response.status_code == 200
    assert response.json()["status"] == "running"

    ThumbnailSyncManager._is_running = False
    response = client.get("/accounts/sync/status")
    assert response.json()["status"] == "idle"


def test_google_login(client):
    """Test initiating Google OAuth flow."""
    with patch("google_auth_oauthlib.flow.Flow.from_client_config") as mock_flow:
        mock_flow.return_value.authorization_url.return_value = ("http://auth.url", "state")
        response = client.get(
            "/accounts/google/login", headers={"Authorization": "Bearer fake_token"}
        )
        assert response.status_code == 200
        assert response.json()["auth_url"] == "http://auth.url"


def test_google_callback_success(client, mock_db):
    """Test successful Google OAuth callback."""
    with patch("app.api.routes.accounts.get_current_user", return_value=MagicMock(id=1)):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config") as mock_flow:
            flow_inst = mock_flow.return_value
            flow_inst.credentials.token = "token"
            flow_inst.credentials.refresh_token = "refresh"

            with patch(
                "app.api.routes.accounts.get_gdrive_info",
                return_value={"email": "g@gmail.com", "storage_used": 1, "storage_total": 10},
            ):
                # Mock no existing account
                mock_db._query_results[models.Account] = []

                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 200
                assert "Google account linked successfully" in response.text
                mock_db.add.assert_called_once()


def test_get_accounts_refresh_fail(client, mock_db):
    """Test get_accounts when status refresh fails for some accounts."""
    acc_g = models.Account(
        id=1, user_id=1, email="g@gmail.com", provider="gdrive", storage_used=0, storage_total=0
    )
    acc_m = models.Account(
        id=2, user_id=1, email="m@mega.nz", provider="mega", storage_used=0, storage_total=0
    )
    mock_db._query_results[models.Account] = [acc_g, acc_m]

    with patch("app.api.routes.accounts.get_gdrive_info", return_value=None):
        with patch("app.api.routes.accounts.get_mega_session", return_value=None):
            response = client.get("/accounts/")
            assert response.status_code == 200
            data = response.json()
            assert data[0]["is_active"] is False
            assert data[1]["is_active"] is False


def test_add_account_unsupported(client):
    """Test adding an account with an unsupported provider."""
    payload = {"provider": "dropbox", "email": "d@db.com", "password": "p"}
    response = client.post("/accounts/add", json=payload)
    assert response.status_code == 400


def test_google_callback_info_fail(client):
    """Test Google callback when fetching account info fails."""
    with patch("app.api.routes.accounts.get_current_user", return_value=MagicMock(id=1)):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config"):
            with patch("app.api.routes.accounts.get_gdrive_info", return_value=None):
                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 500


def test_google_callback_conflict(client, mock_db):
    """Test Google callback when account is already linked to another user."""
    user1 = MagicMock(id=1)
    acc_existing = models.Account(id=10, user_id=2, email="g@gmail.com", provider="gdrive")

    with patch("app.api.routes.accounts.get_current_user", return_value=user1):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config"):
            with patch(
                "app.api.routes.accounts.get_gdrive_info", return_value={"email": "g@gmail.com"}
            ):
                mock_db._query_results[models.Account] = [acc_existing]
                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 409


def test_google_callback_integrity_retry(client, mock_db):
    """Test Google callback handling IntegrityError with successful retry."""
    from sqlalchemy.exc import IntegrityError

    user1 = MagicMock(id=1)
    acc_existing = models.Account(
        id=10, user_id=1, email="g@gmail.com", provider="gdrive", storage_used=1, storage_total=10
    )

    with patch("app.api.routes.accounts.get_current_user", return_value=user1):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config") as mock_flow:
            mock_flow.return_value.credentials.token = "t"
            mock_flow.return_value.credentials.refresh_token = "r"
            with patch(
                "app.api.routes.accounts.get_gdrive_info",
                return_value={"email": "g@gmail.com", "storage_used": 1, "storage_total": 10},
            ):
                # Mock sequential results for Account queries
                results_iter = iter([[], [acc_existing]])

                def mock_query_side_effect(model):
                    if model == models.Account:
                        q = MagicMock()
                        res = next(results_iter)
                        q.filter.return_value.first.return_value = res[0] if res else None
                        return q
                    return MagicMock()

                mock_db.query.side_effect = mock_query_side_effect

                # First commit fails, second (in retry) succeeds
                mock_db.commit.side_effect = [IntegrityError("msg", "params", "orig"), None]

                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 200
                assert mock_db.commit.call_count == 2


def test_google_callback_integrity_fatal(client, mock_db):
    """Test Google callback handling fatal IntegrityError (not found on retry)."""
    from sqlalchemy.exc import IntegrityError

    user1 = MagicMock(id=1)

    with patch("app.api.routes.accounts.get_current_user", return_value=user1):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config"):
            with patch(
                "app.api.routes.accounts.get_gdrive_info",
                return_value={"email": "g@gmail.com", "storage_used": 0, "storage_total": 0},
            ):
                mock_db._query_results[models.Account] = []  # Still not found on retry
                mock_db.commit.side_effect = IntegrityError("msg", "params", "orig")

                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 500
                assert "Database integrity error" in response.json()["detail"]


def test_disconnect_account_success(client, mock_db):
    """Test successfully disconnecting an account."""
    acc = models.Account(id=1, user_id=1, email="test@mega.nz")
    mock_db._query_results[models.Account] = [acc]

    response = client.delete("/accounts/1")
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    mock_db.delete.assert_called_once()
    mock_db.commit.assert_called_once()


def test_google_callback_existing_update(client, mock_db):
    """Test Google callback updating an existing account for the same user."""
    user1 = MagicMock(id=1)
    acc_existing = models.Account(id=10, user_id=1, email="g@gmail.com", provider="gdrive")

    with patch("app.api.routes.accounts.get_current_user", return_value=user1):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config") as mock_flow:
            mock_flow.return_value.credentials.token = "new_token"
            mock_flow.return_value.credentials.refresh_token = "new_refresh"
            with patch(
                "app.api.routes.accounts.get_gdrive_info",
                return_value={"email": "g@gmail.com", "storage_used": 100, "storage_total": 1000},
            ):
                mock_db._query_results[models.Account] = [acc_existing]
                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 200
                assert acc_existing.access_token == "new_token"


def test_google_callback_conflict_after_retry(client, mock_db):
    """Test Google callback finding a conflict with ANOTHER user during retry."""
    from sqlalchemy.exc import IntegrityError

    user1 = MagicMock(id=1)
    acc_other = models.Account(id=10, user_id=2, email="g@gmail.com", provider="gdrive")

    with patch("app.api.routes.accounts.get_current_user", return_value=user1):
        with patch("google_auth_oauthlib.flow.Flow.from_client_config"):
            with patch(
                "app.api.routes.accounts.get_gdrive_info",
                return_value={"email": "g@gmail.com", "storage_used": 1, "storage_total": 10},
            ):
                # First call empty, second call returns account owned by user 2
                results_iter = iter([[], [acc_other]])

                def mock_query_side_effect(model):
                    if model == models.Account:
                        q = MagicMock()
                        res = next(results_iter)
                        q.filter.return_value.first.return_value = res[0] if res else None
                        return q
                    return MagicMock()

                mock_db.query.side_effect = mock_query_side_effect
                mock_db.commit.side_effect = [IntegrityError("msg", "params", "orig"), None]

                response = client.get("/accounts/google/callback?code=123&state=abc")
                assert response.status_code == 409
