"""Query-time reconciliation of reading-session data.

PageStat-based KOReader page-stats have been removed (the model is gone).
All statistics come from ReadingSession records only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer, func, or_
from sqlalchemy.orm import Session

from backend.models.reading import ReadingSession

NON_DEVICE_SOURCES = ("web", "web-reader", "manual")


def _epoch(dt: Optional[datetime]) -> Optional[int]:
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt else None


def covered_book_ids(db: Session, user_id: int) -> list[int]:
    """Book ids that have imported page-stats (page-stats win for these books).
    Always empty — PageStat model has been removed."""
    return []


def _rs_filtered(db: Session, user_id: int, covered: list[int],
                 cutoff: Optional[datetime], range_end: Optional[datetime]):
    q = db.query(ReadingSession).filter(ReadingSession.user_id == user_id)
    if covered:
        # Covered books drop only their device-origin sessions (page-stats
        # already describe that reading); web/manual sessions stay additive.
        q = q.filter(or_(
            ReadingSession.book_id.notin_(covered),
            ReadingSession.device.in_(NON_DEVICE_SOURCES),
        ))
    if cutoff is not None:
        q = q.filter(ReadingSession.started_at >= cutoff)
    if range_end is not None:
        q = q.filter(ReadingSession.started_at < range_end)
    return q


# ── Totals ────────────────────────────────────────────────────────────────────

def totals(db, user_id, tzm, covered, cutoff, range_end) -> tuple[int, int, int]:
    """(seconds, sessions, pages) over the window."""
    rs = _rs_filtered(db, user_id, covered, cutoff, range_end).with_entities(
        func.coalesce(func.sum(ReadingSession.duration_seconds), 0),
        func.count(ReadingSession.id),
        func.coalesce(func.sum(ReadingSession.pages_turned), 0),
    ).one()
    return int(rs[0] or 0), int(rs[1] or 0), int(rs[2] or 0)


# ── Daily (per local-day) ─────────────────────────────────────────────────────

def daily_map(db, user_id, tzm, covered, start_dt, end_dt) -> dict[str, tuple[int, int, int]]:
    """day_str -> (seconds, sessions, pages). Caller fills the gaps."""
    rows = (
        _rs_filtered(db, user_id, covered, start_dt, end_dt)
        .with_entities(
            func.date(ReadingSession.started_at, tzm).label("day"),
            func.coalesce(func.sum(ReadingSession.duration_seconds), 0).label("secs"),
            func.count(ReadingSession.id).label("sessions"),
            func.coalesce(func.sum(ReadingSession.pages_turned), 0).label("pages"),
        )
        .group_by("day").all()
    )
    out: dict[str, list[int]] = {r.day: [int(r.secs or 0), int(r.sessions or 0), int(r.pages or 0)] for r in rows}
    return {d: (v[0], v[1], v[2]) for d, v in out.items()}


# ── Per-book ──────────────────────────────────────────────────────────────────

def book_seconds(db, user_id, tzm, covered, cutoff, range_end) -> dict[int, tuple[int, int, int]]:
    """book_id -> (seconds, sessions, pages) over the window."""
    rows = (
        _rs_filtered(db, user_id, covered, cutoff, range_end)
        .filter(ReadingSession.book_id.isnot(None))
        .with_entities(
            ReadingSession.book_id,
            func.coalesce(func.sum(ReadingSession.duration_seconds), 0).label("secs"),
            func.count(ReadingSession.id).label("sessions"),
            func.coalesce(func.sum(ReadingSession.pages_turned), 0).label("pages"),
        )
        .group_by(ReadingSession.book_id).all()
    )
    out: dict[int, list[int]] = {r.book_id: [int(r.secs or 0), int(r.sessions or 0), int(r.pages or 0)] for r in rows}
    return {b: (v[0], v[1], v[2]) for b, v in out.items()}


def book_month_seconds(db, user_id, tzm, covered, start_dt) -> dict[tuple[int, str], int]:
    """(book_id, 'YYYY-MM') -> seconds. For the genre-over-time stack."""
    rs_month = func.strftime("%Y-%m", func.datetime(ReadingSession.started_at, tzm))
    rows = (
        _rs_filtered(db, user_id, covered, start_dt, None)
        .filter(ReadingSession.book_id.isnot(None))
        .with_entities(ReadingSession.book_id, rs_month.label("m"),
                       func.coalesce(func.sum(ReadingSession.duration_seconds), 0).label("secs"))
        .group_by(ReadingSession.book_id, "m").all()
    )
    return {(r.book_id, r.m): int(r.secs or 0) for r in rows}


# ── Hour × day-of-week ────────────────────────────────────────────────────────

def hour_dow(db, user_id, tzm, covered, cutoff, range_end) -> dict[tuple[int, int], tuple[int, int]]:
    """(dow, hour) -> (seconds, sessions)."""
    rs_local = func.datetime(ReadingSession.started_at, tzm)
    rows = (
        _rs_filtered(db, user_id, covered, cutoff, range_end)
        .with_entities(
            func.cast(func.strftime("%w", rs_local), Integer).label("dow"),
            func.cast(func.strftime("%H", rs_local), Integer).label("hour"),
            func.coalesce(func.sum(ReadingSession.duration_seconds), 0).label("secs"),
            func.count(ReadingSession.id).label("sessions"),
        )
        .group_by("dow", "hour").all()
    )
    return {(r.dow, r.hour): (int(r.secs or 0), int(r.sessions or 0)) for r in rows}


# ── Monthly (per 'YYYY-MM') ───────────────────────────────────────────────────

def monthly_map(db, user_id, tzm, covered, start_dt) -> dict[str, tuple[int, int]]:
    """'YYYY-MM' -> (seconds, sessions)."""
    rs_month = func.strftime("%Y-%m", func.datetime(ReadingSession.started_at, tzm))
    rows = (
        _rs_filtered(db, user_id, covered, start_dt, None)
        .with_entities(rs_month.label("m"),
                       func.coalesce(func.sum(ReadingSession.duration_seconds), 0).label("secs"),
                       func.count(ReadingSession.id).label("sessions"))
        .group_by("m").all()
    )
    return {r.m: (int(r.secs or 0), int(r.sessions or 0)) for r in rows}



