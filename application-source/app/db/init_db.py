"""Database Initialization Module.

Responsibilities:
- Ensure mandatory records (like the admin user) exist in the database
- Handle initial data seeding on first deployment
"""

import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import models
from app.core.config import settings
from app.core.security import hash_password

logger = logging.getLogger(__name__)


def ensure_schema_compatibility(db: Session) -> None:
    """Apply lightweight schema fixes for older SQLite databases."""

    result = db.execute(text("PRAGMA table_info(accounts)"))
    account_columns = {row[1] for row in result}

    if "expires_at" not in account_columns:
        logger.info("Applying schema patch: adding accounts.expires_at")
        db.execute(text("ALTER TABLE accounts ADD COLUMN expires_at INTEGER"))
        db.commit()
        logger.info("Schema patch applied successfully")


def init_admin_user(db: Session) -> None:
    """Ensure an 'admin' user exists with the configured SITE_PASSCODE."""

    if not settings.SITE_PASSCODE:
        logger.warning("No SITE_PASSCODE configured. Skipping admin user initialization.")
        return

    admin_user = db.query(models.User).filter(models.User.username == "admin").first()

    if not admin_user:
        logger.info("Creating default 'admin' user...")
        admin_user = models.User(
            username="admin", password_hash=hash_password(settings.SITE_PASSCODE)
        )
        db.add(admin_user)
        db.commit()
        logger.info("Admin user created successfully.")
    else:
        # Update password to match current environment config
        # This ensures that changing the ENV variable updates the access code
        admin_user.password_hash = hash_password(settings.SITE_PASSCODE)
        db.commit()
        logger.info("Admin user credentials updated from environment config.")
