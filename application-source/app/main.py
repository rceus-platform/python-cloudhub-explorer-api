"""CloudHub Explorer API Entry Point.

Responsibilities:
- Initialize the FastAPI application and mount middleware
- Register API routers for auth, accounts, files, and video
- Manage database initialization and server lifecycle events

Boundaries:
- Does not handle business logic or data validation (delegated to routes/services)
- Does not handle raw database queries (delegated to models/session)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import accounts, auth, files, video
from app.core.config import settings
from app.core.dependencies import get_current_user, get_current_user_dev
from app.db.models import Base
from app.db.session import engine

# Initialize database schema
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manage application startup and shutdown events."""

    # Startup
    print("Server started successfully")
    yield
    # Shutdown
    print("Server shutting down")


app = FastAPI(
    title="CloudHub Explorer API",
    description="Unified Cloud File Explorer Backend",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS with environment-aware origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["Accounts"])
app.include_router(files.router, prefix="/files", tags=["Files"])
app.include_router(video.router, prefix="/video", tags=["Video"])

# Development-only auth bypass
if settings.DEBUG:
    from app.core.dependencies import get_current_user_optional

    app.dependency_overrides[get_current_user] = get_current_user_dev
    app.dependency_overrides[get_current_user_optional] = get_current_user_dev


@app.get("/")
def root():
    """Health check endpoint."""

    return {"message": "CloudHub Explorer API is running"}
