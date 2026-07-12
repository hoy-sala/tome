from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.ratings import validate_rating
from backend.core.security import get_current_user
from backend.core.permissions import require_role, is_admin
from backend.models.series_meta import SeriesMeta
from backend.models.user import User
from backend.schemas.series import (
    SeriesMetaOut,
    SeriesMetaUpdate,
)

router = APIRouter(tags=["series"])

VALID_STATUSES = {"ongoing", "finished", "hiatus", "unknown"}


# ── Series reading-stats endpoint ─────────────────────────────────────────────
# Registered before /series/{name}/arcs and /series/{name}/meta so the
# static suffix "reading-stats" is matched first.

# ── SeriesMeta endpoints ──────────────────────────────────────────────────────

@router.get("/series/meta-map", response_model=dict[str, str])
def list_series_meta_map(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return a {series_name: status} dict for every SeriesMeta row.

    Cheap one-shot lookup for dashboards that render a status badge per
    series — avoids N parallel GET /series/{name}/meta calls that can
    exhaust the DB connection pool.
    """
    rows = db.query(SeriesMeta.series_name, SeriesMeta.status).all()
    return {r.series_name: r.status for r in rows}


@router.get("/series/{name}/meta", response_model=SeriesMetaOut)
def get_series_meta(
    name: str,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return SeriesMeta for a series. Returns a placeholder with status='unknown' if none exists."""
    meta = db.query(SeriesMeta).filter(SeriesMeta.series_name == name).first()
    if meta is None:
        return SeriesMetaOut(series_name=name, status="unknown")
    return meta


@router.put("/series/{name}/meta", response_model=SeriesMetaOut)
def upsert_series_meta(
    name: str,
    body: SeriesMetaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upsert the SeriesMeta for a series. Admin only."""
    require_role(current_user, "admin")
    meta = db.query(SeriesMeta).filter(SeriesMeta.series_name == name).first()
    if meta is None:
        meta = SeriesMeta(series_name=name, status=body.status)
        db.add(meta)
    else:
        meta.status = body.status
    db.commit()
    db.refresh(meta)
    return meta


# ── Series rating (per-user) ──────────────────────────────────────────────────
# A volume's effective rating is its own rating else this series rating
# (inherited). Series *display* rating is the explicit value if set, else the
# average of the user's volume ratings. The "__unserialized__" sentinel + empty
# string are the No-Series bucket and can never be rated.

from pydantic import BaseModel
from sqlalchemy import func as _func
from backend.models.user_series_rating import UserSeriesRating
from backend.models.user_book_status import UserBookStatus
from backend.models.book import Book

NO_SERIES_SENTINEL = "__unserialized__"


class SeriesRatingOut(BaseModel):
    series_name: str
    rating: Optional[float] = None      # explicit series rating (half-star steps)
    review: Optional[str] = None
    volume_average: Optional[float] = None  # avg of the user's volume ratings
    rated_volumes: int = 0
    display: Optional[float] = None      # explicit if set, else rounded average


class SeriesRatingIn(BaseModel):
    rating: Optional[float] = None       # 1–5 in half-star steps, or null to clear
    review: Optional[str] = None


def _series_rating_out(db: Session, user: User, name: str) -> "SeriesRatingOut":
    row = (
        db.query(UserSeriesRating)
        .filter(UserSeriesRating.user_id == user.id, UserSeriesRating.series_name == name)
        .first()
    )
    avg, cnt = (
        db.query(_func.avg(UserBookStatus.rating), _func.count(UserBookStatus.rating))
        .join(Book, Book.id == UserBookStatus.book_id)
        .filter(
            UserBookStatus.user_id == user.id,
            UserBookStatus.rating.isnot(None),
            Book.series == name,
        )
        .one()
    )
    explicit = row.rating if row else None
    # Derived average rounds to the nearest HALF star (widgets render halves).
    display = explicit if explicit is not None else (round(avg * 2) / 2 if avg is not None else None)
    return SeriesRatingOut(
        series_name=name,
        rating=explicit,
        review=row.review if row else None,
        volume_average=round(float(avg), 2) if avg is not None else None,
        rated_volumes=int(cnt or 0),
        display=display,
    )


def _reject_no_series(name: str) -> None:
    if not name or name == NO_SERIES_SENTINEL:
        raise HTTPException(400, "The 'No Series' group cannot be rated")


@router.get("/series/{name}/rating", response_model=SeriesRatingOut)
def get_series_rating(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _series_rating_out(db, current_user, name)


@router.put("/series/{name}/rating", response_model=SeriesRatingOut)
def set_series_rating(
    name: str,
    body: SeriesRatingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _reject_no_series(name)
    validate_rating(body.rating)
    from datetime import datetime
    raw = body.model_dump(exclude_unset=True)
    row = (
        db.query(UserSeriesRating)
        .filter(UserSeriesRating.user_id == current_user.id, UserSeriesRating.series_name == name)
        .first()
    )
    if not row:
        row = UserSeriesRating(user_id=current_user.id, series_name=name)
        db.add(row)
    if "rating" in raw:
        row.rating = body.rating
        row.rated_at = datetime.utcnow() if body.rating is not None else None
    if "review" in raw:
        row.review = body.review or None
    db.commit()
    return _series_rating_out(db, current_user, name)



