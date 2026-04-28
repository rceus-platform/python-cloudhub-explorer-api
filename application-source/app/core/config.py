"""Core Configuration Module.

Responsibilities:
- Load and validate application settings from environment variables
- Provide a centralized settings object for all modules
- Define default values and configuration for external services

Boundaries:
- Does not handle logic for specific services (delegated to services layer)
"""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings managed via Pydantic and .env."""

    SITE_PASSCODE: str = ""
    DATABASE_URL: str = "sqlite:///./cloudhub.db"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/accounts/google/callback"

    # Security keys (will fallback to SITE_PASSCODE if not set)
    SECRET_KEY: str = ""
    FERNET_KEY: str = ""

    # CORS allowed origins
    CORS_ORIGINS: list[str] = ["*"]

    # Directory for per-account Mega session persistence
    MEGA_SESSION_DIR: str = os.path.join(os.path.expanduser("~"), ".mega_sessions")

    # Shared secret for internal service communication
    INTERNAL_SECRET: str = ""

    # Toggle for development-only auth bypass
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
