"""Batch 2 — insights blocks on /api/stats: lifetime, records, tbr, language."""
from datetime import datetime

from backend.models.user_book_status import UserBookStatus
from backend.models.tome_sync import ReadingSession


def _sess(db, user, book, secs, when, pages):
    db.add(ReadingSession(user_id=user.id, book_id=book.id, started_at=when, ended_at=when,
                          duration_seconds=secs, pages_turned=pages))


def test_insights_blocks(client, db, admin_user, make_book):
    user, _ = admin_user
    a = make_book(title="A", language="en")
    b = make_book(title="B", language="eng")   # folds to English too
    make_book(title="C", language="de")        # owned, unread, no reading time
    db.add(UserBookStatus(user_id=user.id, book_id=a.id, status="read"))
    db.add(UserBookStatus(user_id=user.id, book_id=b.id, status="reading"))
    _sess(db, user, a, 600, datetime(2026, 1, 1, 10), 20)
    _sess(db, user, b, 300, datetime(2026, 1, 2, 10), 10)
    db.flush()

    s = client.get("/api/stats?days=0").json()

    # lifetime (all-time)
    assert s["lifetime"]["seconds"] == 900
    assert s["lifetime"]["books_finished"] == 1
    assert s["lifetime"]["active_days"] == 2

    # records
    assert s["records"]["longest_session_seconds"] == 600
    assert s["records"]["longest_session_title"] == "A"
    assert s["records"]["biggest_day_seconds"] == 600

    # tbr: 3 owned, 1 read, 1 reading, 1 implicitly unread
    assert s["tbr"]["owned"] == 3
    assert s["tbr"]["read"] == 1 and s["tbr"]["reading"] == 1
    assert s["tbr"]["unread"] == 1
    assert s["tbr"]["pct"] == 33.3

    # language: en + eng fold into one "English" entry (900s, 2 books); 'C' has no time
    langs = {l["language"]: l for l in s["language"]}
    assert "English" in langs
    assert langs["English"]["seconds"] == 900 and langs["English"]["books"] == 2
    assert "German" not in langs  # C was never read, so no reading time
