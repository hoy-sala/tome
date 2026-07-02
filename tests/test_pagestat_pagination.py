"""Pagination-robust page-stat math.

KOReader re-paginates whenever font/margins change, so absolute page numbers
are only meaningful against their own row's ``total_pages``. Regressions here:
mixing paginations shrank a finished book to "250 of 1571 pages · 16%",
counted page N under two paginations as a re-read, halved/doubled device-only
completion estimates, and let one source's evidence inflate the other's
confidence.
"""
from datetime import datetime, timezone

from backend.models.ko_stats import PageStat
from backend.models.tome_sync import ReadingSession
from backend.models.user_book_status import UserBookStatus

DAY = 86_400
BASE = 1_700_000_000
NOW = int(datetime.utcnow().replace(tzinfo=timezone.utc).timestamp())


def _page(db, user, book, page, total, ts, dur=60, device="Kindle"):
    db.add(PageStat(user_id=user.id, book_id=book.id, page=page, total_pages=total,
                    start_time=ts, duration_seconds=dur, device=device))


def test_repagination_does_not_shrink_a_finished_book(client, db, admin_user, make_book):
    """Fully read at a 250-page pagination, reopened once at 1571 pages: the
    book page must not claim '250 of 1571 pages · 16%'."""
    user, _ = admin_user
    book = make_book(title="Font Change Victim")
    for p in range(1, 251):                       # cover to cover at 250 pages
        _page(db, user, book, p, 250, BASE + p)
    _page(db, user, book, 400, 1571, BASE + 30 * DAY)   # one later dwell, re-paginated
    db.flush()

    r = client.get(f"/api/books/{book.id}/reading-stats?tz_offset=0").json()
    own, intensity = r["own"], r["intensity"]
    assert intensity["total_pages"] == 1571        # latest pagination, not max()
    assert intensity["pct_read"] == 100.0          # coverage is fraction-space
    assert intensity["pages_read"] == 1571
    assert own["pages_turned"] == 1571
    assert own["progress"] == 1.0                  # furthest per-row fraction = 250/250


def test_estimates_progress_uses_per_row_fraction(client, db, admin_user, make_book):
    """Position = max(page/total per row): 245/250 (98%) must win over the
    misleading max(page)=245 vs max(total)=1571 (16%)."""
    user, _ = admin_user
    book = make_book(title="Almost Done")
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="reading", progress_pct=0.0))
    for p in range(240, 246):                      # near the end at 250 pages
        _page(db, user, book, p, 250, NOW - 2 * DAY + p)
    _page(db, user, book, 100, 1571, NOW - DAY)    # later re-paginated dwell
    db.flush()

    rows = client.get("/api/stats/completion-estimates?tz_offset=0").json()
    row = next(r for r in rows if r["book_id"] == book.id)
    assert row["progress"] == 98.0


def test_rereads_scoped_to_one_pagination(client, db, admin_user, make_book):
    """Page 10 dwelled under two different paginations is different content,
    not a revisit; the same pagination on two days still is."""
    user, _ = admin_user
    cross = make_book(title="Cross Pagination")
    real = make_book(title="Real Reread")
    for p in range(1, 6):
        _page(db, user, cross, p, 250, BASE + 12 * 3600 + p)             # day 0, 250pp
        _page(db, user, cross, p, 1571, BASE + 10 * DAY + 12 * 3600 + p)  # day 10, 1571pp
        _page(db, user, real, p, 250, BASE + 12 * 3600 + p)
        _page(db, user, real, p, 250, BASE + 10 * DAY + 12 * 3600 + p)   # same pagination
    db.flush()

    rr = {b["book_id"]: b for b in client.get("/api/stats?days=0&tz_offset=0").json()["rereads"]["books"]}
    assert cross.id not in rr
    assert real.id in rr
    assert rr[real.id]["reread_pages"] == 5
    assert rr[real.id]["total_pages"] == 250


def test_device_estimate_counts_all_active_days(client, db, admin_user, make_book):
    """20 pages over 2 active days is 10 pages/day — the first-day subtraction
    made it 20/day and halved the estimate."""
    user, _ = admin_user
    book = make_book(title="Steady Reader")
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="reading", progress_pct=0.0))
    for i, p in enumerate(range(1, 21)):
        ts = NOW - (2 * DAY if p <= 10 else DAY)   # two reading days, 10 pages each
        _page(db, user, book, p, 100, ts + i)
    db.flush()

    rows = client.get("/api/stats/completion-estimates?tz_offset=0").json()
    row = next(r for r in rows if r["book_id"] == book.id)
    assert row["progress"] == 20.0
    # 80 pages left at 10/day → 8 days (the old first-day subtraction said 4).
    assert row["estimated_days"] == 8
    assert row["confidence"] == "medium"           # 2 page-stat days


def test_confidence_follows_the_estimating_path(client, db, admin_user, make_book):
    """A session-driven estimate with 2 sessions stays 'medium' even when the
    book also has many page-stat reading days (which that path never uses)."""
    user, _ = admin_user
    book = make_book(title="Mixed Sources")
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="reading", progress_pct=0.5))
    # 10 page-stat reading days (would be "high" under max(...) cross-talk)
    for d in range(10):
        _page(db, user, book, d + 1, 100, NOW - (d + 2) * DAY + 12 * 3600)
    # 2 live sessions in the window → the session path drives the estimate
    for d in (1, 2):
        started = datetime.utcfromtimestamp(NOW - d * DAY)
        db.add(ReadingSession(user_id=user.id, book_id=book.id, started_at=started,
                              ended_at=started, duration_seconds=1200,
                              progress_start=0.3, progress_end=0.5, device="web-reader"))
    db.flush()

    rows = client.get("/api/stats/completion-estimates?tz_offset=0").json()
    row = next(r for r in rows if r["book_id"] == book.id)
    assert row["confidence"] == "medium"
