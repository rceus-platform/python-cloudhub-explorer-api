"""Account Service Module.

Responsibilities:
- Resolve and merge user accounts from the database
- Provide unified access to provider credentials

Boundaries:
- Does not handle auth token verification (delegated to dependencies)
- Does not handle provider-specific listing (delegated to gdrive/mega services)
"""

from sqlalchemy.orm import Session

from app.db import models
from app.core.config import settings


def get_user_accounts(db: Session, user_id: int) -> list[models.Account]:
    """Retrieve all linked accounts for a user."""

    accounts = db.query(models.Account).filter(models.Account.user_id == user_id).all()

    # Fallback for MEGA account via environment variables
    has_mega = any(acc.provider == "mega" for acc in accounts)
    if not has_mega and settings.MEGA_USERNAME and settings.MEGA_PASSWORD:
        env_mega = models.Account(
            user_id=user_id,
            email=settings.MEGA_USERNAME,
            provider="mega",
            access_token=settings.MEGA_USERNAME,
            refresh_token=settings.MEGA_PASSWORD,
            is_active=True,
        )
        accounts.append(env_mega)

    return accounts


def get_provider_account(db: Session, user_id: int, provider: str) -> models.Account | None:
    """Find a specific provider account for a user."""

    account = (
        db.query(models.Account)
        .filter(models.Account.user_id == user_id, models.Account.provider == provider)
        .order_by(models.Account.id.desc())
        .first()
    )

    # Fallback for MEGA account via environment variables
    if not account and provider == "mega" and settings.MEGA_USERNAME and settings.MEGA_PASSWORD:
        return models.Account(
            user_id=user_id,
            email=settings.MEGA_USERNAME,
            provider="mega",
            access_token=settings.MEGA_USERNAME,
            refresh_token=settings.MEGA_PASSWORD,
            is_active=True,
        )

    return account


def get_account_by_email(
    db: Session, user_id: int, provider: str, email: str
) -> models.Account | None:
    """Find a specific account by provider and email."""

    return (
        db.query(models.Account)
        .filter(
            models.Account.user_id == user_id,
            models.Account.provider == provider,
            models.Account.email == email,
        )
        .first()
    )
