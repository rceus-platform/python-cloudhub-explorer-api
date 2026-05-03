"""Integration tests for the main application entry point."""


def test_read_root(client):
    """Test the health check endpoint."""

    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "CloudHub Explorer API is running"}


def test_cors_headers(client):
    """Test that CORS headers are correctly configured."""

    response = client.options(
        "/",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
