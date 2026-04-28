"""Main Application: initializes FastAPI, configures CORS, and manages app lifespan."""


import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import accounts, auth, files
from app.core.dependencies import get_current_user, get_current_user_dev
from app.db.models import Base
from app.db.session import engine

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="CloudHub Explorer API",
    description="Unified Cloud File Explorer Backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration
origins = [
    "http://localhost:3000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["Accounts"])
app.include_router(files.router, prefix="/files", tags=["Files"])

# Development Overrides
if os.environ.get("DEV_MODE") == "true":
    logger.warning("DEV_MODE is enabled. Authentication is bypassed.")
    app.dependency_overrides[get_current_user] = get_current_user_dev



@app.get("/")
def root():
    """Health check endpoint"""

    return {"message": "CloudHub Explorer API is running"}
