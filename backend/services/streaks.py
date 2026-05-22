"""Shared reading-streak computation.

Buckets sessions by the user's local day with a 4-hour rollover, so a session
started at 01:30 CEST still counts toward the previous day's bedtime read.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.tome_sync import ReadingSession

ROLLOVER_HOURS = 4


def _effective_hours(tz_offset_minutes: int, rollover_hours: int = ROLLOVER_HOURS) -> int:
    # JS getTimezoneOffset: minutes, negative = east of UTC (e.g. CEST → -120)
    tz_hours = -(tz_offset_minutes // 60)
    return tz_hours - rollover_hours


def date_modifier(tz_offset_minutes: int, rollover_hours: int = ROLLOVER_HOURS) -> str:
    """SQLite date() modifier that maps a UTC timestamp to its local day with rollover."""
    return f"{_effective_hours(tz_offset_minutes, rollover_hours):+d} hours"


def effective_today(tz_offset_minutes: int, rollover_hours: int = ROLLOVER_HOURS) -> date:
    """The user's current 'reading day' — what walking back a streak should start from."""
    return (datetime.utcnow() + timedelta(hours=_effective_hours(tz_offset_minutes, rollover_hours))).date()


def streaks_from_dates(day_set: set[date], today: date) -> tuple[int, int]:
    if not day_set:
        return 0, 0
    current = 0
    d = today
    while d in day_set:
        current += 1
        d -= timedelta(days=1)
    if current == 0:
        d = today - timedelta(days=1)
        while d in day_set:
            current += 1
            d -= timedelta(days=1)
    sorted_days = sorted(day_set)
    longest = 1
    run = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    return current, longest


def compute_user_streaks(
    db: Session,
    user_id: int,
    tz_offset_minutes: int,
) -> tuple[int, int]:
    """Return (current_streak, longest_streak) for a user, in their local day with 4h rollover."""
    modifier = date_modifier(tz_offset_minutes)
    rows = (
        db.query(func.date(ReadingSession.started_at, modifier).label("d"))
        .filter(ReadingSession.user_id == user_id)
        .distinct()
        .all()
    )
    day_set = {date.fromisoformat(r.d) for r in rows if r.d}
    return streaks_from_dates(day_set, effective_today(tz_offset_minutes))
