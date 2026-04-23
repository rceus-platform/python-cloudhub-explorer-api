"""
Accounts API Router

Responsibilities:
- Manage Google Drive and Mega account connections
- Handle OAuth callbacks and credential storage

Boundaries:
- Does not handle file listing or streaming (handled by files.py)
"""

from fastapi import APIRouter, Depends, HTTPException
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db import models
from app.db.session import get_db
from app.services.mega_service import get_mega_session

router = APIRouter()


@router.get("/google/login")
def google_login(_user=Depends(get_current_user)):
    """Generate Google OAuth login URL"""

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    )

    flow.redirect_uri = "http://localhost:8000/accounts/google/callback"

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    return {"auth_url": auth_url}


@router.get("/google/callback")
def google_callback(
    code: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Handle Google OAuth callback and store tokens"""

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    )

    flow.redirect_uri = "http://localhost:8000/accounts/google/callback"

    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Fetch user email from Google
    session = flow.authorized_session()
    user_info = session.get("https://www.googleapis.com/oauth2/v1/userinfo").json()
    email = user_info.get("email")

    account = models.Account(
        user_id=user.id,
        provider="gdrive",
        email=email,
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
    )

    db.add(account)
    db.commit()

    return {"message": f"Google Drive connected successfully for {email}"}


@router.post("/add")
def add_account(
    provider: str,
    access_token: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Manually add a cloud provider account"""

    account = models.Account(
        user_id=user.id, provider=provider, access_token=access_token
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    return {"message": "Account added successfully"}


@router.get("/")
def get_accounts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Retrieve all connected accounts for the current user"""

    accounts = db.query(models.Account).filter(models.Account.user_id == user.id).all()

    return accounts


class MegaLoginRequest(BaseModel):
    """Mega login request schema"""

    email: str
    password: str
    label: str | None = None


@router.post("/mega/login")
def mega_login(
    data: MegaLoginRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Authenticate with Mega and store credentials"""

    m = get_mega_session(data.email, data.password)
    if not m:
        raise HTTPException(
            status_code=401,
            detail="Could not authenticate with Mega. Check credentials or try again shortly.",
        )

    account = models.Account(
        user_id=user.id,
        provider="mega",
        email=data.email,
        label=data.label,
        access_token=data.email,
        refresh_token=data.password,
    )

    db.add(account)
    db.commit()

    return {"message": f"Mega connected successfully for {data.email}"}
