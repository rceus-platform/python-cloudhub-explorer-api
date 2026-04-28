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





def get_user_accounts(db: Session, user_id: int) -> list[models.Account]:
    """Retrieve all linked accounts for a user."""

    return db.query(models.Account).filter(models.Account.user_id == user_id).all()


def get_provider_account(
    db: Session, user_id: int, provider: str
) -> models.Account | None:
    """Find a specific provider account for a user."""

    return (
        db.query(models.Account)
        .filter(models.Account.user_id == user_id, models.Account.provider == provider)
        .order_by(models.Account.id.desc())
        .first()
    )


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
