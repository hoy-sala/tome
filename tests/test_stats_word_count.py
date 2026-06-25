"""Phase 4 word-count stats blocks: words / wpm / book_lengths on /api/stats."""
from datetime import datetime

from backend.models.tome_sync import ReadingSession
from backend.models.user_book_status import UserBookStatus


def _finish(db, user, book, when):
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="read", updated_at=when))


def _session(db, user, book, secs, when):
    db.add(ReadingSession(user_id=user.id, book_id=book.id, started_at=when,
                          ended_at=when, duration_seconds=secs, pages_turned=10))


def test_word_count_blocks(client, db, admin_user, make_book):
    user, _ = admin_user

    a = make_book(title="A"); a.word_count = 100_000
    b = make_book(title="B"); b.word_count = 60_000
    c = make_book(title="C"); c.word_count = 200_000
    # finished but no word_count (e.g. a PDF) → excluded everywhere
    d = make_book(title="D", file_format="pdf"); d.word_count = None
    db.flush()

    _finish(db, user, a, datetime(2025, 3, 1))
    _finish(db, user, b, datetime(2026, 1, 1))
    _finish(db, user, c, datetime(2026, 2, 1))
    _finish(db, user, d, datetime(2026, 2, 2))
    # read-time: A & C get enough to count for WPM; B is under the 5-min floor
    _session(db, user, a, 6000, datetime(2025, 3, 1))   # 100k/6000s -> 1000 wpm
    _session(db, user, c, 6000, datetime(2026, 2, 1))   # 200k/6000s -> 2000 wpm
    _session(db, user, b, 120, datetime(2026, 1, 1))    # < 300s -> excluded from WPM
    db.flush()

    s = client.get("/api/stats?days=0").json()

    # ── words ──
    w = s["words"]
    assert w["total_words"] == 360_000          # a + b + c (d has none)
    assert w["books_counted"] == 3
    assert w["by_year"] == [
        {"year": 2025, "words": 100_000},
        {"year": 2026, "words": 260_000},        # b + c
    ]

    # ── wpm ──
    wpm = s["wpm"]
    assert wpm["books_counted"] == 2             # a, c (b under floor)
    assert wpm["overall"] == 1500.0             # (100k+200k)*60 / (6000+6000)
    assert [bk["title"] for bk in wpm["books"]] == ["C", "A"]  # sorted wpm desc
    assert wpm["books"][0]["wpm"] == 2000.0

    # ── book_lengths ──
    bl = s["book_lengths"]
    assert bl["count"] == 3
    assert bl["avg_words"] == 120_000           # (100k+60k+200k)/3
    assert bl["median_words"] == 100_000
    assert bl["longest"]["title"] == "C"
    counts = {b["label"]: b["count"] for b in bl["buckets"]}
    assert counts == {"<50k": 0, "50–100k": 1, "100–150k": 1, "150–250k": 1, "250k+": 0}


def test_word_count_blocks_empty_user(client, db, admin_user, make_book):
    # A user with no finished+counted books gets well-formed empty blocks.
    make_book(title="Unread")  # exists but never finished
    db.flush()
    s = client.get("/api/stats?days=0").json()
    assert s["words"] == {"total_words": 0, "books_counted": 0, "by_year": []}
    assert s["wpm"] == {"overall": 0, "books_counted": 0, "books": []}
    assert s["book_lengths"]["count"] == 0
    assert s["book_lengths"]["avg_words"] == 0
    assert s["book_lengths"]["longest"] is None
