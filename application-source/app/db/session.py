"""Database Session Module.

Responsibilities:
- Initialize the SQLAlchemy engine and session factory
- Manage the lifecycle of database connections
- Provide a FastAPI dependency for obtaining database sessions

Boundaries:
- Does not define the database schema (delegated to db.models)
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Create engine with appropriate arguments for the selected database
is_sqlite = settings.DATABASE_URL.startswith("sqlite")
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if is_sqlite else {},
)

# Session factory for generating database connections
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all declarative models
Base = declarative_base()


def get_db():
    """FastAPI dependency that provides a transactional database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
