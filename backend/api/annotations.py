"""Annotations API — the cross-library Highlights / commonplace view.

`GET /api/annotations` returns the current user's KOReader-synced highlights
across *all* visible books (the per-book view lives at
`GET /api/books/{id}/annotations`). Read-only: KOReader owns annotations; the
plugin pushes them via `PUT /api/tome-sync/annotations/{id}`.

Registered before `/api/books/{id}` is irrelevant here (distinct prefix), but the
router is mounted at /api like the rest.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.core.permissions import book_visibility_filter
from backend.models.book import Book
from backend.models.tome_sync import Annotation
from backend.models.user import User

router = APIRouter(tags=["annotations"])


def _to_item(a, b) -> dict:
    """Shape one (Annotation, Book) row for the API, with book context."""
    return {
        "id": a.id,
        "book_id": b.id,
        "book_title": b.title,
        "book_author": b.author,
        "book_cover": f"/api/books/{b.id}/cover" if b.cover_path else None,
        "highlighted_text": a.highlighted_text,
        "note": a.note,
        "chapter": a.chapter,
        "color": a.color,
        "datetime": a.koreader_datetime,  # when highlighted on the device
        "synced_at": a.created_at.isoformat() + "Z",  # when Tome first stored it
    }


def _month_day(dt: Optional[str]) -> Optional[str]:
    """Pull 'MM-DD' out of a KOReader datetime string like '2024-01-15 10:30:00'.

    KOReader writes 'YYYY-MM-DD HH:MM:SS' (local wall-clock). We only need the
    month-day for the 'on this day' filter, so a cheap slice is enough; return
    None for anything that doesn't look like a date.
    """
    if not dt or len(dt) < 10 or dt[4] != "-" or dt[7] != "-":
        return None
    return dt[5:10]


@router.get("/annotations")
def list_annotations(
    q: Optional[str] = Query(None, description="case-insensitive text search"),
    on_this_day: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The current user's highlights across every book they can see."""
    query = (
        db.query(Annotation, Book)
        .join(Book, Annotation.book_id == Book.id)
        .filter(
            Annotation.user_id == current_user.id,
            Book.status == "active",
            book_visibility_filter(db, current_user),
        )
    )

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Annotation.highlighted_text.ilike(like),
                Annotation.note.ilike(like),
                Annotation.chapter.ilike(like),
                Book.title.ilike(like),
            )
        )

    # Newest highlights first (KOReader's own timestamp, falling back to id).
    rows = (
        query.order_by(Annotation.koreader_datetime.desc().nullslast(), Annotation.id.desc())
        .all()
    )

    if on_this_day:
        today = _month_day(func_now_str())
        rows = [(a, b) for (a, b) in rows if _month_day(a.koreader_datetime) == today]

    total = len(rows)
    book_ids = {b.id for (_, b) in rows}
    page = rows[offset : offset + limit]

    items = [_to_item(a, b) for (a, b) in page]

    return {"total": total, "books": len(book_ids), "items": items}


@router.get("/annotations/spotlight")
def annotation_spotlight(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One highlight for the Home tab: a random highlight made on this calendar
    day in a past year, falling back to any random highlight so the card is never
    empty. `on_this_day` tells the UI which case it got.
    """
    base = (
        db.query(Annotation, Book)
        .join(Book, Annotation.book_id == Book.id)
        .filter(
            Annotation.user_id == current_user.id,
            Book.status == "active",
            Annotation.highlighted_text.isnot(None),
            Annotation.highlighted_text != "",
            book_visibility_filter(db, current_user),
        )
    )

    today_md = _month_day(func_now_str())
    on_day_row = None
    if today_md:
        on_day_row = (
            base.filter(
                Annotation.koreader_datetime.isnot(None),
                func.substr(Annotation.koreader_datetime, 6, 5) == today_md,
            )
            .order_by(func.random())
            .first()
        )

    row = on_day_row or base.order_by(func.random()).first()
    if not row:
        return {"highlight": None, "on_this_day": False}
    a, b = row
    return {"highlight": _to_item(a, b), "on_this_day": on_day_row is not None}


def func_now_str() -> str:
    """Today's local date as 'YYYY-MM-DD HH:MM:SS' so _month_day can slice it.

    Wrapped in a helper (not inlined) so tests can monkeypatch 'today'.
    """
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
