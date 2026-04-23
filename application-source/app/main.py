"""
Main Application Entry Point

Responsibilities:
- Initialize FastAPI application
- Configure CORS middleware
- Include API routes
- Manage database initialization
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import accounts, auth, files
from app.core.dependencies import get_current_user, get_current_user_dev
from app.db.models import Base
from app.db.session import engine

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CloudHub Explorer API",
    description="Unified Cloud File Explorer Backend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["Accounts"])
app.include_router(files.router, prefix="/files", tags=["Files"])

app.dependency_overrides[get_current_user] = get_current_user_dev


@app.get("/")
def root():
    """Health check endpoint"""

    return {"message": "CloudHub Explorer API is running"}


@app.on_event("startup")
def on_startup():
    """Startup event handler"""

    print("Server started successfully")


@app.on_event("shutdown")
def on_shutdown():
    """Shutdown event handler"""

    print("Server shutting down")
