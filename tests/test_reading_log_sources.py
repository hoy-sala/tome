"""Per-source reading reconciliation + the explicit finish date.

Page-stats replace only *device-origin* sessions (they describe the same
reading twice); web-reader and manual-log sessions are invisible to KOReader's
history and must stay additive. Regression: logging 30 minutes of paper
reading on a Kindle-synced book returned 201 and changed nothing visible.

finished_at: updated_at moves on every rating/review/CFI write, so it is not a
finish date. The explicit column is stamped on the transition into "read".
"""
from datetime import datetime, timezone

from backend.models.reading import ReadingSession
from backend.models.user_book_status import UserBookStatus

DAY = 86_400
BASE = 1_700_000_000





def test_finished_at_survives_rating_and_cfi_updates(client, db, admin_user, make_book):
    user, _ = admin_user
    book = make_book(title="Finished In January")

    client.put(f"/api/books/{book.id}/status", json={"status": "read"})
    row = db.query(UserBookStatus).filter_by(user_id=user.id, book_id=book.id).one()
    finished = row.finished_at
    assert finished is not None

    # Rating later must not move the finish date (updated_at will move; that's fine).
    client.put(f"/api/books/{book.id}/rating", json={"rating": 5})
    db.expire_all()
    row = db.query(UserBookStatus).filter_by(user_id=user.id, book_id=book.id).one()
    assert row.finished_at == finished

    own = client.get(f"/api/books/{book.id}/reading-stats?tz_offset=0").json()["own"]
    assert own["finished_at"].startswith(finished.isoformat()[:19])

    # Un-finishing clears the date.
    client.put(f"/api/books/{book.id}/status", json={"status": "reading"})
    db.expire_all()
    row = db.query(UserBookStatus).filter_by(user_id=user.id, book_id=book.id).one()
    assert row.finished_at is None


def test_manual_session_started_at_converts_timezone(client, db, admin_user, make_book):
    """'23:30+02:00' is 21:30 UTC — stripping the offset stored it as 23:30."""
    user, _ = admin_user
    book = make_book(title="TZ Aware")
    r = client.post(f"/api/books/{book.id}/sessions?tz_offset=0", json={
        "duration_minutes": 10,
        "started_at": "2026-06-01T23:30:00+02:00",
    })
    assert r.status_code == 201, r.text
    s = db.query(ReadingSession).filter_by(user_id=user.id, book_id=book.id).one()
    assert s.started_at == datetime(2026, 6, 1, 21, 30)


def test_manual_session_input_validation(client, db, admin_user, make_book):
    user, _ = admin_user
    book = make_book(title="Bad Inputs")
    # A huge duration used to overflow timedelta into an unhandled 500.
    r = client.post(f"/api/books/{book.id}/sessions?tz_offset=0",
                    json={"duration_minutes": 1e10})
    assert r.status_code == 422
    r = client.post(f"/api/books/{book.id}/sessions?tz_offset=0",
                    json={"duration_minutes": 10, "pages": -5})
    assert r.status_code == 422
