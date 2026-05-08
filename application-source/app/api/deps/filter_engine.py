"""Filter Engine Dependency.

Responsibilities:
- Parse and validate query parameters for the item listing endpoint
- Construct SQL-level filter and sort expressions
- Provide a FastAPI-injectable dependency that returns a filtered SQLAlchemy query

Boundaries:
- Does not handle HTTP responses or pagination (delegated to route handlers)
- Does not manage database sessions (injected via get_db)
"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import Depends, Query
from sqlalchemy import and_, case
from sqlalchemy.orm import Query as SAQuery, Session

from app.db import models
from app.db.session import get_db

logger = logging.getLogger(__name__)

SortField = Literal["name", "size", "modified_at"]
SortOrder = Literal["asc", "desc"]


def build_item_query(
    db: Session = Depends(get_db),
    # --- Search ---
    search: str | None = Query(None, description="Case-insensitive substring match on name"),
    # --- Tags ---
    tags: str | None = Query(
        None,
        description="Comma-separated tag names, e.g. 'work,urgent'",
    ),
    logic: Literal["and", "or"] = Query(
        "or", description="Tag filter logic: 'and' requires all tags, 'or' requires any"
    ),
    # --- Metadata filters ---
    mime_type: str | None = Query(None, description="Filter by MIME type prefix, e.g. 'video/'"),
    min_size: int | None = Query(None, ge=0, description="Minimum file size in bytes"),
    max_size: int | None = Query(None, ge=0, description="Maximum file size in bytes"),
    date_from: str | None = Query(None, description="ISO-8601 lower bound for updated_at"),
    date_to: str | None = Query(None, description="ISO-8601 upper bound for updated_at"),
    # --- Sorting ---
    sort_by: SortField = Query("name", description="Sort field"),
    sort_order: SortOrder = Query("asc", description="Sort direction"),
) -> SAQuery:
    """FastAPI dependency that builds a filtered, sorted SQLAlchemy query over FileSystemItems.

    Folders are always hoisted to the top via a SQL CASE expression, regardless
    of the chosen sort field — consistent with the implementation advice.
    """
    q: SAQuery = db.query(models.FileSystemItem)

    # 1. Name search (case-insensitive LIKE)
    if search:
        q = q.filter(models.FileSystemItem.name.ilike(f"%{search}%"))

    # 2. Tag filtering
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if tag_list:
            if logic == "and":
                # Each tag must appear in the item's tag set
                for tag_name in tag_list:
                    q = q.filter(
                        models.FileSystemItem.tags.any(
                            and_(
                                models.Tag.name == tag_name,
                            )
                        )
                    )
            else:
                # Any of the tags is sufficient
                q = q.filter(
                    models.FileSystemItem.tags.any(
                        models.Tag.name.in_(tag_list)
                    )
                )

    # 3. MIME type prefix filter
    if mime_type:
        q = q.filter(models.FileSystemItem.mime_type.ilike(f"{mime_type}%"))

    # 4. Size range
    if min_size is not None:
        q = q.filter(models.FileSystemItem.size >= min_size)
    if max_size is not None:
        q = q.filter(models.FileSystemItem.size <= max_size)

    # 5. Date range on updated_at
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            q = q.filter(models.FileSystemItem.updated_at >= dt_from)
        except ValueError:
            logger.warning("Invalid date_from value: %s — ignored", date_from)

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            q = q.filter(models.FileSystemItem.updated_at <= dt_to)
        except ValueError:
            logger.warning("Invalid date_to value: %s — ignored", date_to)

    # 6. Sorting — folders always first via CASE expression (SQL-level, not Python)
    folder_first = case(
        (models.FileSystemItem.is_folder == True, 0),  # noqa: E712
        else_=1,
    )

    sort_column_map = {
        "name": models.FileSystemItem.name,
        "size": models.FileSystemItem.size,
        "modified_at": models.FileSystemItem.updated_at,
    }
    sort_col = sort_column_map.get(sort_by, models.FileSystemItem.name)

    if sort_order == "desc":
        q = q.order_by(folder_first, sort_col.desc())
    else:
        q = q.order_by(folder_first, sort_col.asc())

    return q
