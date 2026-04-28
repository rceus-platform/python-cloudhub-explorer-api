"""Accounts API Router: manages Google Drive and Mega account connections and credential storage."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db import models, schemas
from app.db.session import get_db
from app.services.mega_service import get_mega_session

logger = logging.getLogger(__name__)

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

    flow.redirect_uri = f"{settings.API_BASE_URL}/accounts/google/callback"

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

    flow.redirect_uri = f"{settings.API_BASE_URL}/accounts/google/callback"

    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Fetch user email from Google
        session = flow.authorized_session()
        response = session.get("https://www.googleapis.com/oauth2/v1/userinfo")
        response.raise_for_status()
        user_info = response.json()
        email = user_info.get("email")

        if not email:
            raise ValueError("No email found in Google user info")

    except Exception as exc:
        logger.exception("Error during Google OAuth callback")
        raise HTTPException(
            status_code=502,
            detail="Error communicating with Google services. Please try again.",
        ) from exc

    account = models.Account(
        user_id=user.id,
        provider="gdrive",
        email=email,
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
    )

    db.add(account)
    db.commit()

    logger.info(
        "Successfully connected Google Drive account for user %s (%s)", user.id, email
    )
    return {"message": f"Google Drive connected successfully for {email}"}


@router.post("/add")
def add_account(
    data: schemas.AccountCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Manually add a cloud provider account using JSON body"""

    account = models.Account(
        user_id=user.id, provider=data.provider, access_token=data.access_token
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    logger.info("Manually added account %s for user %s", data.provider, user.id)
    return {"message": "Account added successfully"}


@router.get("/", response_model=list[schemas.AccountOut])
def get_accounts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Retrieve all connected accounts for the current user (safe response)"""

    accounts = db.query(models.Account).filter(models.Account.user_id == user.id).all()

    return accounts


class MegaLoginRequest(schemas.BaseModel):
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
    """Authenticate with Mega and store credentials (safely)"""

    try:
        m = get_mega_session(data.email, data.password)
    except Exception as exc:
        logger.exception(
            "Unexpected error contacting Mega service during login for user %s", user.id
        )
        raise HTTPException(
            status_code=502,
            detail="Error contacting Mega service, please try again later.",
        ) from exc

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
        # We use email as the session key and avoid storing plaintext passwords for MEGA
        access_token=data.email,
        refresh_token=None,
    )

    db.add(account)
    db.commit()

    return {"message": f"Mega connected successfully for {data.email}"}
