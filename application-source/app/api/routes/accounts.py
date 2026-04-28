"""Accounts API Module.

Responsibilities:
- Handle OAuth2 flow for Google Drive accounts
- Manage account linking and credential persistence
- Provide endpoints for listing and managing linked accounts

Boundaries:
- Does not handle file listing (delegated to routes.files)
- Does not handle JWT verification (delegated to core.dependencies)
"""

import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from google_auth_oauthlib.flow import Flow  # type: ignore[import]
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db import models
from app.db.schemas import (
    AccountAddRequest,
    AccountResponse,
    AuthUrlResponse,
    SuccessMessageResponse,
    SuccessStatusResponse,
)
from app.db.session import get_db
from app.services import file_cache
from app.services.gdrive_service import get_account_info as get_gdrive_info
from app.services.mega_service import get_mega_session, get_storage_info as get_mega_info

router = APIRouter()


@router.get("/", response_model=list[AccountResponse])
async def get_accounts(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    """Retrieve all linked accounts with real-time health and storage status."""

    accounts = db.query(models.Account).filter(models.Account.user_id == user.id).all()

    async def refresh_account_status(acc: models.Account):
        try:
            if acc.provider == "gdrive":
                info = await asyncio.to_thread(get_gdrive_info, acc, db)
                if info:
                    acc.email = info["email"]
                    acc.storage_used = info["storage_used"]
                    acc.storage_total = info["storage_total"]
                    acc.is_active = True
                else:
                    acc.is_active = False
            elif acc.provider == "mega":
                m = await asyncio.to_thread(get_mega_session, acc.access_token, acc.refresh_token)
                if m:
                    info = await asyncio.to_thread(get_mega_info, m)
                    acc.storage_used = info["storage_used"]
                    acc.storage_total = info["storage_total"]
                    acc.is_active = True
                else:
                    acc.is_active = False
            db.commit()
        except Exception as e:
            print(f"Error refreshing account status for {acc.email}: {e}")
            acc.is_active = False
            db.commit()

    # Refresh status in parallel
    await asyncio.gather(*(refresh_account_status(acc) for acc in accounts))

    return accounts


@router.post("/add", response_model=SuccessMessageResponse)
async def add_account(
    request: AccountAddRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Link a new MEGA account using credentials."""

    if request.provider == "mega":
        m = await asyncio.to_thread(get_mega_session, request.email, request.password)
        if not m:
            raise HTTPException(status_code=401, detail="Invalid MEGA credentials")

        info = await asyncio.to_thread(get_mega_info, m)

        # Check if already exists
        existing = db.query(models.Account).filter(
            models.Account.user_id == user.id,
            models.Account.email == request.email,
            models.Account.provider == "mega"
        ).first()

        if existing:
            existing.access_token = request.email
            existing.refresh_token = request.password
            existing.storage_used = info["storage_used"]
            existing.storage_total = info["storage_total"]
            existing.is_active = True
        else:
            account = models.Account(
                user_id=user.id,
                email=request.email,
                provider="mega",
                access_token=request.email,  # Storing email as access_token for MEGA
                refresh_token=request.password, # Storing password as refresh_token for MEGA
                storage_used=info["storage_used"],
                storage_total=info["storage_total"],
                is_active=True
            )
            db.add(account)

        db.commit()
        file_cache.invalidate_all(user.id)
        return {"message": "MEGA account linked successfully"}

    raise HTTPException(status_code=400, detail="Unsupported provider for this endpoint")


@router.delete("/{account_id}", response_model=SuccessStatusResponse)
def disconnect_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Disconnect and remove a linked cloud account."""

    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    db.delete(account)
    db.commit()
    file_cache.invalidate_all(user.id)

    return {"status": "success"}


@router.get("/google/login", response_model=AuthUrlResponse)
def google_login(
    request: Request,
    _user: models.User = Depends(get_current_user)
) -> AuthUrlResponse:
    """Initiate the Google OAuth2 authorization flow."""

    flow = Flow.from_client_config(  # type: ignore[no-untyped-call]
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
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        ],
    )

    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

    # Extract raw token from Authorization header to pass as state
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(" ")[1] if auth_header and " " in auth_header else ""

    auth_url, _ = flow.authorization_url(  # type: ignore[no-untyped-call]
        access_type="offline",
        prompt="consent",
        state=token
    )

    return AuthUrlResponse(auth_url=auth_url)  # type: ignore[return-value]


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
):
    """Handle the Google OAuth2 callback and persist tokens."""

    # Authenticate user using the token passed in state
    user = get_current_user(credentials=None, token=state, db=db)

    flow = Flow.from_client_config(  # type: ignore[no-untyped-call]
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
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        ],
    )

    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

    # Relax token scope validation for Google OAuth
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    # Exchange code for tokens
    flow.fetch_token(code=code)  # type: ignore[no-untyped-call]
    credentials = flow.credentials

    # Create temporary account object to fetch info
    temp_acc = models.Account(
        access_token=credentials.token,
        refresh_token=credentials.refresh_token
    )

    info = await asyncio.to_thread(get_gdrive_info, temp_acc, db)
    if not info:
        raise HTTPException(status_code=500, detail="Failed to fetch Google account info")

    # Match by provider and email to find existing linked account.
    existing = db.query(models.Account).filter(
        models.Account.email == info["email"],
        models.Account.provider == "gdrive"
    ).first()

    if existing and existing.user_id != user.id:
        raise HTTPException(
            status_code=409,
            detail="This Google account is already linked to another user"
        )

    if existing:
        existing.access_token = credentials.token
        if credentials.refresh_token:
            existing.refresh_token = credentials.refresh_token
        existing.storage_used = info["storage_used"]
        existing.storage_total = info["storage_total"]
        existing.is_active = True
    else:
        account = models.Account(
            user_id=user.id,
            email=info["email"],
            provider="gdrive",
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            storage_used=info["storage_used"],
            storage_total=info["storage_total"],
            is_active=True
        )
        db.add(account)

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # Race-safe retry path if another request inserted the same account.
        print(f"Race condition detected during account link for {info['email']}: {e}")
        existing = db.query(models.Account).filter(
            models.Account.email == info["email"],
            models.Account.provider == "gdrive"
        ).first()

        if not existing:
            # If still not found, it might be a different integrity issue
            print(f"Failed to find existing account after IntegrityError for {info['email']}")
            raise HTTPException(
                status_code=500,
                detail="Database integrity error during account linking"
            ) from e

        if existing.user_id != user.id:
            raise HTTPException(
                status_code=409,
                detail="This Google account is already linked to another user"
            ) from e

        existing.access_token = credentials.token
        if credentials.refresh_token:
            existing.refresh_token = credentials.refresh_token
        existing.storage_used = info["storage_used"]
        existing.storage_total = info["storage_total"]
        existing.is_active = True
        try:
            db.commit()
        except Exception as commit_err:
            db.rollback()
            print(f"Final commit failed during account link retry: {commit_err}")
            raise HTTPException(
                status_code=500,
                detail="Failed to persist account updates"
            ) from commit_err

    file_cache.invalidate_all(user.id)

    return HTMLResponse(
        content="""
        <html>
            <script>
                if (window.opener) {
                    window.opener.postMessage('google-login-success', '*');
                    window.close();
                } else {
                    document.body.innerHTML = '<h1>Success</h1><p>Google account linked successfully. You can close this tab.</p>';
                }
            </script>
        </html>
        """
    )
