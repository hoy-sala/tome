"""Persist a book's chapter map (see BookChapter for the anchor design)."""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.models.book import Book, BookChapter

logger = logging.getLogger(__name__)


def replace_book_chapters(db: Session, book_id: int, chapters: list[dict] | None) -> int:
    """Persist a chapter-extraction RESULT for a book.

    - ``None``  → extraction never ran (non-EPUB callers): nothing happens.
    - ``[]``    → extraction ran and found no usable TOC: the attempt is
      stamped (``chapters_extracted_at``) so the backfill stops re-queuing the
      book, but existing rows are left alone — a missing TOC today doesn't
      invalidate a map extracted from the same file yesterday.
    - ``[...]`` → rows are replaced and the attempt stamped.

    Returns the number of chapter rows written.
    """
    if chapters is None:
        return 0
    book = db.get(Book, book_id)
    if book is not None:
        book.chapters_extracted_at = datetime.utcnow()
    if not chapters:
        return 0
    db.query(BookChapter).filter(BookChapter.book_id == book_id).delete()
    for c in chapters:
        db.add(BookChapter(
            book_id=book_id,
            idx=c["idx"],
            title=(c["title"] or "")[:512],
            start_fraction=c["start_fraction"],
            end_fraction=c["end_fraction"],
        ))
    return len(chapters)
