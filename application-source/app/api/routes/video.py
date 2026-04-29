"""Video API Module.

Responsibilities:
- Manage user watch history and playback progress
- Provide endpoints for retrieving video state (current time, duration)

Boundaries:
- Does not handle video streaming or extraction (delegated to routes.files)
- Does not handle database session management (delegated to db.session)
"""

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db import models, schemas
from app.db.session import get_db

router = APIRouter()


@router.post("/progress", response_model=schemas.SuccessStatusResponse)
def save_video_progress(
    progress: schemas.VideoProgressResponse,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Save or update the current playback position for a specific file."""

    user_id = int(user.id)  # type: ignore[arg-type]

    record = (
        db.query(models.WatchHistory)
        .filter(
            models.WatchHistory.user_id == user_id,
            models.WatchHistory.file_id == progress.file_id,
        )
        .first()
    )

    if not record:
        record = models.WatchHistory(
            user_id=user_id,
            file_id=progress.file_id,
            current_time=progress.current_time,
            duration=progress.duration,
            last_watched=int(time.time()),
        )
        db.add(record)
    else:
        record.current_time = progress.current_time  # type: ignore[attr-defined]
        if progress.duration > 0:
            record.duration = progress.duration  # type: ignore[attr-defined]
        record.last_watched = int(time.time())  # type: ignore[attr-defined]

    db.commit()
    return {"status": "success"}


@router.get("/state/{file_id}", response_model=schemas.VideoStateResponse)
def get_video_state(
    file_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Retrieve the last known playback position and duration for a file."""

    user_id = int(user.id)  # type: ignore[arg-type]

    record = (
        db.query(models.WatchHistory)
        .filter(
            models.WatchHistory.user_id == user_id,
            models.WatchHistory.file_id == file_id,
        )
        .first()
    )

    if not record:
        return {"current_time": 0, "duration": 0}

    current_time_val = record.current_time if record.current_time is not None else 0  # type: ignore[comparison-overlap]
    duration_val = record.duration if record.duration is not None else 0  # type: ignore[comparison-overlap]

    return {"current_time": current_time_val, "duration": duration_val}
