"""Core configuration: manage environment variables and global settings using Pydantic Settings."""


import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings schema"""

    SITE_PASSCODE: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    API_BASE_URL: str = "http://localhost:8000"
    STREAM_SERVICE_URL: str = "http://localhost:4000"

    # Optional Mega credentials from environment
    MEGA_USERNAME: str | None = None
    MEGA_PASSWORD: str | None = None

    # Directory where per-account Mega session pickles are stored.
    # Defaults to ~/.mega_sessions/ when not set in .env.
    MEGA_SESSION_DIR: str = os.path.join(os.path.expanduser("~"), ".mega_sessions")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
