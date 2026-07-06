"""Whole-library 'count words' background backfill job.

A single, serial, cancellable job parses every EPUB whose ``Book.word_count`` is
still NULL and stores the count. It runs in a daemon thread so it survives the
request that started it — closing the browser tab or navigating away never
cancels it. Progress lives in module-global state (guarded by a lock) and is
read back via the status endpoint, so the UI is just a poller and can reconnect
at any time.

Unlike the bake job this NEVER touches files on disk — it only reads them and
writes one integer column — so there is no atomic-replace / hash / read-only
machinery. New uploads already get their count at ingest
(``metadata.extract_epub``); this job is purely for books that predate the
feature.

Single-process model: state is in-memory, so a server restart drops the job and
its progress. That is safe and cheap to recover from — the work list is "books
with word_count IS NULL", so a re-run simply resumes with whatever is left.
(Tome runs a single uvicorn worker; SQLite is single-writer.)

Progress is weighted by *bytes* (parse time roughly tracks file size), so the
ETA is ``elapsed * bytes_left / bytes_done`` rather than a lying file-count bar.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from sqlalchemy import func

from backend.core.database import SessionLocal
from backend.models.book import Book, BookFile
from backend.services.chapters import replace_book_chapters
from backend.services.metadata import (
    count_pages_fixed_layout,
    count_words_epub,
    extract_chapters_epub,
)

log = logging.getLogger(__name__)

_MAX_ISSUES = 500

_lock = threading.Lock()
_cancel = threading.Event()
_thread: Optional[threading.Thread] = None

# status: idle | running | done | cancelled | error
_state: dict = {"status": "idle"}


class WordCountAlreadyRunning(Exception):
    pass


def _epub_books() -> dict[int, tuple[Optional[int], int, str, bool]]:
    """One row per book that has an EPUB file:
    book_id → (word_count, size, path, chapters_checked).
    If a book has several EPUB files we keep the first.

    chapters_checked comes from the attempt marker, NOT from having chapter
    rows — a TOC-less EPUB never gains rows and would otherwise re-queue on
    every run forever."""
    with SessionLocal() as db:
        rows = (
            db.query(
                Book.id,
                Book.word_count,
                Book.chapters_extracted_at,
                BookFile.file_size,
                BookFile.file_path,
            )
            .join(BookFile, BookFile.book_id == Book.id)
            .filter(func.lower(BookFile.format) == "epub")
            .all()
        )
    out: dict[int, tuple[Optional[int], int, str, bool]] = {}
    for book_id, wc, checked_at, size, path in rows:
        if book_id not in out:
            out[book_id] = (wc, size or 0, path, checked_at is not None)
    return out


def _fixed_layout_books() -> list[tuple[int, str, int]]:
    """Books with a PDF/CBZ/CBR file and no intrinsic page count yet."""
    with SessionLocal() as db:
        rows = (
            db.query(Book.id, BookFile.file_path, BookFile.file_size)
            .join(BookFile, BookFile.book_id == Book.id)
            .filter(
                Book.page_count.is_(None),
                func.lower(BookFile.format).in_(("pdf", "cbz", "cbr")),
            )
            .all()
        )
    seen: set[int] = set()
    out: list[tuple[int, str, int]] = []
    for book_id, path, size in rows:
        if book_id not in seen:
            seen.add(book_id)
            out.append((book_id, path, size or 0))
    return out


def preflight() -> dict:
    """Cheap DB-only summary of what a run would do (no disk access)."""
    books = _epub_books()
    total = len(books)
    pending = pending_bytes = 0
    for wc, size, _path, has_ch in books.values():
        if wc is None or not has_ch:
            pending += 1
            pending_bytes += size
    pages = _fixed_layout_books()
    return {
        "epub_total": total,
        "already_counted": total - pending,
        "pending": pending + len(pages),
        "pending_bytes": pending_bytes + sum(s for _, _, s in pages),
        # split, for anyone curious (the UI shows the aggregate)
        "pending_epubs": pending,
        "pending_page_counts": len(pages),
    }


def _snapshot() -> dict:
    s = dict(_state)
    if s.get("status") == "running" and s.get("started_at"):
        elapsed = time.time() - s["started_at"]
    elif s.get("started_at") and s.get("finished_at"):
        elapsed = s["finished_at"] - s["started_at"]
    else:
        elapsed = 0.0
    s["elapsed_seconds"] = round(elapsed, 1)

    eta = None
    if s.get("status") == "running":
        done_bytes = s.get("done_bytes", 0)
        total_bytes = s.get("total_bytes", 0)
        if done_bytes > 0 and total_bytes > done_bytes:
            eta = elapsed * (total_bytes - done_bytes) / done_bytes
    s["eta_seconds"] = round(eta, 1) if eta is not None else None
    return s


def get_status() -> dict:
    with _lock:
        return _snapshot()


def dismiss() -> dict:
    """Reset a finished run's summary to idle. No-op while running."""
    global _state
    with _lock:
        if _state.get("status") != "running":
            _state = {"status": "idle"}
        return _snapshot()


def request_cancel() -> bool:
    with _lock:
        if _state.get("status") == "running":
            _cancel.set()
            return True
        return False


def start(*, username: Optional[str] = None) -> dict:
    """Begin a whole-library word-count backfill. Raises if one is active."""
    global _state, _thread
    with _lock:
        if _state.get("status") == "running":
            raise WordCountAlreadyRunning()

        # kind "epub": word count (if missing) + chapter map (if missing).
        # kind "pages": intrinsic PDF/CBZ/CBR page count.
        work: list[tuple[int, str, int, str, bool]] = []
        total_bytes = 0
        for book_id, (wc, size, path, has_ch) in _epub_books().items():
            if wc is None or not has_ch:
                work.append((book_id, path, size, "epub", wc is None))
                total_bytes += size
        for book_id, path, size in _fixed_layout_books():
            work.append((book_id, path, size, "pages", False))
            total_bytes += size

        _cancel.clear()
        _state = {
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "triggered_by": username,
            "total_files": len(work),
            "total_bytes": total_bytes,
            "done_files": 0,
            "done_bytes": 0,
            "counted": 0,
            "failed": 0,
            "words_total": 0,
            "current_file": None,
            "issues": [],
            "error": None,
        }
        _thread = threading.Thread(
            target=_run, args=(work,), name="word-count-backfill", daemon=True
        )
        _thread.start()
        return _snapshot()


def _set_current(path: str) -> None:
    with _lock:
        _state["current_file"] = path


def _record(*, size: int, words: Optional[int], path: str) -> None:
    with _lock:
        _state["done_files"] += 1
        _state["done_bytes"] += size
        if words is not None:
            _state["counted"] += 1
            _state["words_total"] += words
        else:
            _state["failed"] += 1
            if len(_state["issues"]) < _MAX_ISSUES:
                _state["issues"].append({"path": path, "reason": "could not parse EPUB"})


def _finish(status: str, error: Optional[str] = None) -> None:
    with _lock:
        _state["status"] = status
        _state["finished_at"] = time.time()
        _state["current_file"] = None
        if error:
            _state["error"] = error


def _run(work: list[tuple[int, str, int, str, bool]]) -> None:
    try:
        for book_id, path, size, kind, needs_words in work:
            if _cancel.is_set():
                _finish("cancelled")
                return
            _set_current(path)

            if kind == "pages":
                try:
                    pages = count_pages_fixed_layout(Path(path))
                    if pages:
                        with SessionLocal() as db:
                            book = db.get(Book, book_id)
                            if book is not None:
                                book.page_count = pages
                                db.commit()
                    # Page counting is cheap and can't produce words — record it
                    # as counted so progress advances without skewing the totals.
                    _record(size=size, words=0 if pages else None, path=path)
                except Exception:  # noqa: BLE001 — one bad file never aborts the run
                    log.exception("word-count: page count error on book #%s", book_id)
                    _record(size=size, words=None, path=path)
                continue

            try:
                words = count_words_epub(Path(path)) if needs_words else None
                chapters = extract_chapters_epub(Path(path))
            except Exception:  # noqa: BLE001 — one bad file never aborts the run
                log.exception("word-count: error on book #%s", book_id)
                _record(size=size, words=None, path=path)
                continue
            try:
                with SessionLocal() as db:
                    book = db.get(Book, book_id)
                    if book is not None:
                        if words is not None:
                            book.word_count = words
                        replace_book_chapters(db, book_id, chapters)
                        db.commit()
            except Exception:  # noqa: BLE001
                log.exception("word-count: DB write failed for book #%s", book_id)
                _record(size=size, words=None, path=path)
                continue
            # A chapters-only pass (words already stored) still counts as done.
            _record(size=size, words=words if needs_words else 0, path=path)
        _finish("done")
    except Exception as e:  # noqa: BLE001
        log.exception("word-count: job crashed")
        _finish("error", error=str(e))
