"""Tests for the Authentication API router."""


def test_register_success(client):
    """Test successful user registration."""
    response = client.post(
        "/auth/register", json={"username": "newuser", "password": "newpassword"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "newuser"
    assert "id" in response.json()


def test_register_duplicate(client, test_user):
    """Test registration with an existing username."""
    # test_user is used to ensure the user exists in the DB
    _ = test_user
    response = client.post(
        "/auth/register", json={"username": "testuser", "password": "testpassword"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "User already exists"


def test_login_success(client, test_user):
    """Test successful user login."""
    _ = test_user
    response = client.post(
        "/auth/login", json={"username": "testuser", "password": "testpass"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_invalid_password(client, test_user):
    """Test login with an incorrect password."""
    _ = test_user
    response = client.post(
        "/auth/login", json={"username": "testuser", "password": "wrongpassword"}
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


def test_login_nonexistent_user(client):
    """Test login with a username that doesn't exist."""
    response = client.post(
        "/auth/login", json={"username": "noone", "password": "somepassword"}
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


def test_get_current_user_no_token(client):
    """Test dependency when no token is provided."""
    response = client.get("/accounts/")
    assert response.status_code == 401


def test_register_password_too_long(client):
    """Test registration with a password exceeding security limits."""
    response = client.post(
        "/auth/register", json={"username": "longpass", "password": "a" * 73}
    )
    assert response.status_code == 400
    assert "Password too long" in response.json()["detail"]
