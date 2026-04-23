"""
Core Configuration Module

Responsibilities:
- Manage environment variables using Pydantic Settings
- Define global application settings and secrets
"""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings schema"""

    SITE_PASSCODE: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # Optional Mega credentials from environment
    MEGA_USERNAME: str | None = None
    MEGA_PASSWORD: str | None = None

    # Directory where per-account Mega session pickles are stored.
    # Defaults to ~/.mega_sessions/ when not set in .env.
    MEGA_SESSION_DIR: str = os.path.join(os.path.expanduser("~"), ".mega_sessions")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
