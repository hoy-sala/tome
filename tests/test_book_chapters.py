"""Phase 3 plumbing: chapter map extraction (BookChapter), fixed-layout page
counts, and the time-per-chapter stat built on both."""
import io
import zipfile
from pathlib import Path

from ebooklib import epub

from backend.models.book import BookChapter
from backend.models.ko_stats import PageStat
from backend.services.metadata import (
    count_pages_fixed_layout,
    extract_chapters_epub,
    extract_metadata,
)
from backend.services.reading_stats import compute_book_chapter_times


def _make_epub(path: Path, chapters: list[tuple[str, str]]) -> None:
    """chapters: list of (title, body-text)."""
    book = epub.EpubBook()
    book.set_identifier("ch-test")
    book.set_title("Chapter Test")
    book.set_language("en")
    items = []
    for i, (title, txt) in enumerate(chapters):
        c = epub.EpubHtml(title=title, file_name=f"c{i}.xhtml", lang="en")
        c.content = f"<html><body><h1>{title}</h1><p>{txt}</p></body></html>"
        book.add_item(c)
        items.append(c)
    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    epub.write_epub(str(path), book)


def _make_cbz(path: Path, pages: int) -> None:
    # 1x1 white JPEG, tiny but real enough for a namelist count
    jpeg = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffffffff"
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        "ffffffffffffffffffffffffc00b080001000101011100ffc40014000100000000"
        "00000000000000000000000009ffc40014100100000000000000000000000000000"
        "000ffda0008010100003f0037ffd9"
    )
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(pages):
            zf.writestr(f"{i:03d}.jpg", jpeg)


# ── extraction ───────────────────────────────────────────────────────────────

class TestChapterExtraction:
    def test_fractions_follow_word_weight(self, tmp_path):
        # ch1 has 100 words, ch2 has 300 → ch2 starts at 0.25 of the book.
        path = tmp_path / "b.epub"
        _make_epub(path, [
            ("One", " ".join(f"w{i}" for i in range(100))),
            ("Two", " ".join(f"w{i}" for i in range(300))),
        ])
        chapters = extract_chapters_epub(path)
        assert [c["title"] for c in chapters] == ["One", "Two"]
        assert chapters[0]["start_fraction"] == 0.0
        assert abs(chapters[1]["start_fraction"] - 0.25) < 0.03  # h1 text adds a little
        assert chapters[0]["end_fraction"] == chapters[1]["start_fraction"]
        assert chapters[1]["end_fraction"] == 1.0
        assert [c["idx"] for c in chapters] == [0, 1]

    def test_single_chapter_toc_is_no_structure(self, tmp_path):
        path = tmp_path / "b.epub"
        _make_epub(path, [("Only", "some words here")])
        assert extract_chapters_epub(path) == []

    def test_no_toc_returns_empty(self, tmp_path):
        path = tmp_path / "b.epub"
        book = epub.EpubBook()
        book.set_identifier("x")
        book.set_title("No TOC")
        book.set_language("en")
        c = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
        c.content = "<html><body><p>text body words</p></body></html>"
        book.add_item(c)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", c]
        epub.write_epub(str(path), book)
        assert extract_chapters_epub(path) == []

    def test_extract_metadata_carries_private_chapters_key(self, tmp_path):
        path = tmp_path / "b.epub"
        _make_epub(path, [("One", "alpha " * 50), ("Two", "beta " * 50)])
        meta = extract_metadata(path, tmp_path)
        assert len(meta["_chapters"]) == 2


class TestFixedLayoutPageCount:
    def test_cbz_counts_images(self, tmp_path):
        path = tmp_path / "c.cbz"
        _make_cbz(path, 7)
        assert count_pages_fixed_layout(path) == 7
        meta = extract_metadata(path, tmp_path)
        assert meta["page_count"] == 7

    def test_epub_gets_no_page_count(self, tmp_path):
        path = tmp_path / "b.epub"
        _make_epub(path, [("One", "alpha"), ("Two", "beta")])
        assert count_pages_fixed_layout(path) is None
        meta = extract_metadata(path, tmp_path)
        assert "page_count" not in meta


# ── time-per-chapter ─────────────────────────────────────────────────────────

def _chapter(db, book_id, idx, title, start, end):
    db.add(BookChapter(book_id=book_id, idx=idx, title=title,
                       start_fraction=start, end_fraction=end))


def _dwell(db, user_id, book_id, page, total, seconds, start_time=1_700_000_000):
    db.add(PageStat(user_id=user_id, book_id=book_id, page=page,
                    total_pages=total, start_time=start_time + page,
                    duration_seconds=seconds, device="kindle"))


class TestChapterTimes:
    def test_buckets_dwell_by_fraction(self, db, admin_user, make_book):
        user, _ = admin_user
        book = make_book(title="Bucketed")
        _chapter(db, book.id, 0, "One", 0.0, 0.5)
        _chapter(db, book.id, 1, "Two", 0.5, 1.0)
        # 100-page pagination: pages 1-50 → ch One, 51-100 → ch Two
        _dwell(db, user.id, book.id, page=10, total=100, seconds=60)
        _dwell(db, user.id, book.id, page=40, total=100, seconds=30)
        _dwell(db, user.id, book.id, page=80, total=100, seconds=45)
        db.commit()

        out = compute_book_chapter_times(db, user_id=user.id, book_id=book.id)
        assert [c["seconds"] for c in out] == [90, 45]
        assert [c["title"] for c in out] == ["One", "Two"]
        # When the chapter was read: pages 10 and 40 are 30s apart in _dwell's
        # stamping (base + page), well under the 30-min gap → ONE sitting
        # covering both; chapter Two has a single dwell.
        assert out[0]["sittings"] == [{"start_ts": 1_700_000_010, "end_ts": 1_700_000_070}]
        assert out[1]["sittings"] == [{"start_ts": 1_700_000_080, "end_ts": 1_700_000_125}]

    def test_sittings_split_on_thirty_minute_gap(self, db, admin_user, make_book):
        user, _ = admin_user
        book = make_book(title="TwoSittings")
        _chapter(db, book.id, 0, "One", 0.0, 1.0)
        _chapter(db, book.id, 1, "Two", 1.0, 1.0)
        base = 1_700_000_000
        # _dwell stamps start_time + page. Two dwells ~5 minutes apart (one
        # sitting), then one ~2 hours later (a second sitting).
        _dwell(db, user.id, book.id, page=1, total=100, seconds=60, start_time=base - 1)      # ts base
        _dwell(db, user.id, book.id, page=2, total=100, seconds=60, start_time=base + 298)    # ts base+300
        _dwell(db, user.id, book.id, page=3, total=100, seconds=60, start_time=base + 7197)   # ts base+7200
        db.commit()

        out = compute_book_chapter_times(db, user_id=user.id, book_id=book.id)
        s = out[0]["sittings"]
        assert len(s) == 2
        assert s[0]["start_ts"] == base and s[0]["end_ts"] == base + 360
        assert s[1]["start_ts"] == base + 7200 and s[1]["end_ts"] == base + 7260

    def test_mixed_paginations_map_independently(self, db, admin_user, make_book):
        user, _ = admin_user
        book = make_book(title="Repaged")
        _chapter(db, book.id, 0, "One", 0.0, 0.5)
        _chapter(db, book.id, 1, "Two", 0.5, 1.0)
        # Same physical spot (~75% in) under two different paginations.
        _dwell(db, user.id, book.id, page=75, total=100, seconds=10)
        _dwell(db, user.id, book.id, page=300, total=400, seconds=20)
        db.commit()

        out = compute_book_chapter_times(db, user_id=user.id, book_id=book.id)
        assert out[1]["seconds"] == 30
        assert out[0]["seconds"] == 0

    def test_front_matter_folds_into_first_chapter(self, db, admin_user, make_book):
        user, _ = admin_user
        book = make_book(title="Fronted")
        # First chapter starts at 0.1 (cover/front matter before it).
        _chapter(db, book.id, 0, "One", 0.1, 1.0)
        _chapter(db, book.id, 1, "Two", 1.0, 1.0)
        _dwell(db, user.id, book.id, page=1, total=100, seconds=15)
        db.commit()

        out = compute_book_chapter_times(db, user_id=user.id, book_id=book.id)
        assert out[0]["seconds"] == 15

    def test_none_without_chapters_or_stats(self, db, admin_user, make_book):
        user, _ = admin_user
        no_chapters = make_book(title="NoCh")
        _dwell(db, user.id, no_chapters.id, page=1, total=10, seconds=5)
        no_stats = make_book(title="NoSt")
        _chapter(db, no_stats.id, 0, "One", 0.0, 0.5)
        _chapter(db, no_stats.id, 1, "Two", 0.5, 1.0)
        db.commit()

        assert compute_book_chapter_times(db, user_id=user.id, book_id=no_chapters.id) is None
        assert compute_book_chapter_times(db, user_id=user.id, book_id=no_stats.id) is None

    def test_endpoint_carries_chapters_block(self, db, client, admin_user, make_book):
        user, _ = admin_user
        book = make_book(title="Endpointed")
        _chapter(db, book.id, 0, "One", 0.0, 0.5)
        _chapter(db, book.id, 1, "Two", 0.5, 1.0)
        _dwell(db, user.id, book.id, page=20, total=100, seconds=120)
        db.commit()

        r = client.get(f"/api/books/{book.id}/reading-stats")
        assert r.status_code == 200, r.text
        chapters = r.json()["chapters"]
        assert chapters[0]["seconds"] == 120 and chapters[1]["seconds"] == 0


# ── EPUB2 / NCX-only fallback + the re-queue marker ──────────────────────────

def _make_epub2_ncx_only(path: Path, chapters: list[tuple[str, str]]) -> None:
    """A hand-built EPUB2: TOC lives ONLY in the NCX (no EPUB3 nav document) —
    the Tolkien-shaped case the nav-only extraction missed."""
    manifest_items, spine_refs, navpoints, files = [], [], [], []
    for i, (title, txt) in enumerate(chapters):
        fn = f"c{i}.xhtml"
        manifest_items.append(f'<item id="c{i}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine_refs.append(f'<itemref idref="c{i}"/>')
        navpoints.append(
            f'<navPoint id="n{i}" playOrder="{i+1}"><navLabel><text>{title}</text></navLabel>'
            f'<content src="{fn}"/></navPoint>'
        )
        files.append((f"OEBPS/{fn}",
                      f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
                      f'<head><title>{title}</title></head><body><h1>{title}</h1><p>{txt}</p></body></html>'))
    opf = f'''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">epub2-ncx-test</dc:identifier>
    <dc:title>NCX Only</dc:title><dc:language>en</dc:language>
  </metadata>
  <manifest>{''.join(manifest_items)}
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncx">{''.join(spine_refs)}</spine>
</package>'''
    ncx = f'''<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="epub2-ncx-test"/></head>
  <docTitle><text>NCX Only</text></docTitle>
  <navMap>{''.join(navpoints)}</navMap>
</ncx>'''
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/toc.ncx", ncx)
        for name, content in files:
            z.writestr(name, content)


class TestNcxFallback:
    def test_epub2_ncx_only_toc_extracts(self, tmp_path):
        path = tmp_path / "epub2.epub"
        _make_epub2_ncx_only(path, [("Chapter I", "alpha " * 100), ("Chapter II", "beta " * 100)])
        chapters = extract_chapters_epub(path)
        assert [c["title"] for c in chapters] == ["Chapter I", "Chapter II"]
        assert chapters[0]["start_fraction"] == 0.0
        assert chapters[-1]["end_fraction"] == 1.0

    def test_ingest_meta_carries_empty_list_for_toc_less_epub(self, tmp_path):
        # A single-chapter book has no usable structure — the meta must still
        # say "tried" ([]), not stay silent (absent key), or the backfill
        # re-queues it forever.
        path = tmp_path / "b.epub"
        _make_epub(path, [("Only", "some words here")])
        meta = extract_metadata(path, tmp_path)
        assert meta["_chapters"] == []


class TestExtractionMarker:
    def test_replace_semantics(self, db, make_book):
        from backend.services.chapters import replace_book_chapters
        book = make_book(title="Marked")

        # None → untouched (non-EPUB caller)
        replace_book_chapters(db, book.id, None)
        db.flush()
        assert book.chapters_extracted_at is None

        # [] → attempt stamped, no rows
        replace_book_chapters(db, book.id, [])
        db.flush()
        assert book.chapters_extracted_at is not None
        assert db.query(BookChapter).filter_by(book_id=book.id).count() == 0

        # [...] → rows written; a later [] keeps them (stale-TOC protection)
        replace_book_chapters(db, book.id, [
            {"idx": 0, "title": "One", "start_fraction": 0.0, "end_fraction": 1.0},
        ])
        db.flush()
        assert db.query(BookChapter).filter_by(book_id=book.id).count() == 1
        replace_book_chapters(db, book.id, [])
        db.flush()
        assert db.query(BookChapter).filter_by(book_id=book.id).count() == 1

    def test_backfill_pending_predicate(self, db, make_book):
        from backend.services.chapters import replace_book_chapters
        # The job pends a book iff words are missing OR it was never
        # chapter-checked — a checked TOC-less book must NOT pend again.
        checked = make_book(title="NoTocChecked", file_format="epub")
        checked.word_count = 1000
        replace_book_chapters(db, checked.id, [])
        fresh = make_book(title="FreshEpub", file_format="epub")
        fresh.word_count = 1000
        db.commit()

        def pending(b):
            return b.word_count is None or b.chapters_extracted_at is None

        assert pending(checked) is False
        assert pending(fresh) is True
