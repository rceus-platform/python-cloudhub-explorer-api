"""Database Initialization Module.

Responsibilities:
- Ensure mandatory records (like the admin user) exist in the database
- Handle initial data seeding on first deployment
"""

from sqlalchemy.orm import Session
from app.db import models
from app.core.config import settings
from app.core.security import hash_password

def init_admin_user(db: Session) -> None:
    """Ensure an 'admin' user exists with the configured SITE_PASSCODE."""
    
    if not settings.SITE_PASSCODE:
        print("⚠️  No SITE_PASSCODE configured. Skipping admin user initialization.")
        return

    admin_user = db.query(models.User).filter(models.User.username == "admin").first()
    
    if not admin_user:
        print("👤 Creating default 'admin' user...")
        admin_user = models.User(
            username="admin",
            password_hash=hash_password(settings.SITE_PASSCODE)
        )
        db.add(admin_user)
        db.commit()
        print("✅ Admin user created successfully.")
    else:
        # Update password to match current environment config
        # This ensures that changing the ENV variable updates the access code
        admin_user.password_hash = hash_password(settings.SITE_PASSCODE)
        db.commit()
        print("✅ Admin user credentials updated from environment config.")
