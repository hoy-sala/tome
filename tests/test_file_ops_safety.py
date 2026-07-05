"""Crash-safety / data-integrity behaviour of the file-mutating admin paths.

Covers the fixes from the 2026-07-03 file-operations audit:
- reorganize: per-file commit, shutil.move, conflict instead of suffix ratchet
- delete_book: DB delete commits before files are unlinked (no ghost rows)
- purge-empty-dirs / _cleanup_empty_dirs: junk whitelist, never touch
  Syncthing markers or hidden directories, never 500 mid-walk
"""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend.models.book import Book, BookFile


@pytest.fixture()
def library_dir(tmp_path: Path, monkeypatch) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    monkeypatch.setattr("backend.core.config.settings.library_dir", lib)
    return lib


def _book_with_file(make_book, db, library_dir: Path, *, title="Solaris",
                    author="Stanislaw Lem", series=None, series_index=None,
                    rel_path=None, content=b"epub-bytes") -> Book:
    """Create a Book whose BookFile points at a real file inside library_dir."""
    rel = rel_path or f"Wrong Folder/{title}.epub"
    abs_path = library_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    book = make_book(title=title, author=author, series=series,
                     series_index=series_index, file_path=str(abs_path))
    db.commit()
    return book


# ---------------------------------------------------------------------------
# Reorganize
# ---------------------------------------------------------------------------

class TestReorganize:
    def test_moves_file_and_updates_db(self, client: TestClient, db, make_book, library_dir):
        book = _book_with_file(make_book, db, library_dir)
        bf = book.files[0]
        old_path = Path(bf.file_path)

        resp = client.post("/api/books/reorganize", json={"file_ids": [bf.id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["moved"]) == 1
        assert data["errors"] == []

        db.refresh(bf)
        new_path = Path(bf.file_path)
        assert new_path != old_path
        assert new_path.exists(), "file must exist at the committed DB path"
        assert not old_path.exists()
        assert new_path == library_dir / "Stanislaw Lem" / "Solaris.epub"

    def test_occupied_slot_reports_conflict_instead_of_suffixing(
        self, client: TestClient, db, make_book, library_dir
    ):
        # A different file already sits in the canonical slot.
        squatter = library_dir / "Stanislaw Lem" / "Solaris.epub"
        squatter.parent.mkdir(parents=True)
        squatter.write_bytes(b"someone else")

        book = _book_with_file(make_book, db, library_dir)
        bf = book.files[0]
        old_path = Path(bf.file_path)

        resp = client.post("/api/books/reorganize", json={"file_ids": [bf.id]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["moved"] == []
        assert len(data["errors"]) == 1
        assert "occupied" in data["errors"][0]["error"]

        # Nothing moved, nothing suffixed, squatter untouched.
        assert old_path.exists()
        assert squatter.read_bytes() == b"someone else"
        assert not (library_dir / "Stanislaw Lem" / "Solaris (2).epub").exists()
        db.refresh(bf)
        assert Path(bf.file_path) == old_path

    def test_dry_run_reports_conflict_too(self, client: TestClient, db, make_book, library_dir):
        squatter = library_dir / "Stanislaw Lem" / "Solaris.epub"
        squatter.parent.mkdir(parents=True)
        squatter.write_bytes(b"someone else")
        book = _book_with_file(make_book, db, library_dir)
        bf = book.files[0]

        resp = client.post("/api/books/reorganize", json={"file_ids": [bf.id], "dry_run": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["moved"] == []
        assert len(data["errors"]) == 1

    def test_already_correct_file_is_skipped(self, client: TestClient, db, make_book, library_dir):
        book = _book_with_file(make_book, db, library_dir,
                               rel_path="Stanislaw Lem/Solaris.epub")
        bf = book.files[0]

        resp = client.post("/api/books/reorganize", json={"file_ids": [bf.id]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["moved"] == []
        assert data["errors"] == []

    def test_leftover_ds_store_does_not_fail_cleanup(
        self, client: TestClient, db, make_book, library_dir
    ):
        book = _book_with_file(make_book, db, library_dir)
        bf = book.files[0]
        old_parent = Path(bf.file_path).parent
        (old_parent / ".DS_Store").write_bytes(b"junk")

        resp = client.post("/api/books/reorganize", json={"file_ids": [bf.id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["moved"]) == 1
        # Junk-only source folder is cleaned up, junk included.
        assert not old_parent.exists()

    def test_syncthing_marker_blocks_source_dir_cleanup(
        self, client: TestClient, db, make_book, library_dir
    ):
        book = _book_with_file(make_book, db, library_dir)
        bf = book.files[0]
        old_parent = Path(bf.file_path).parent
        marker = old_parent / ".stfolder"
        marker.write_bytes(b"")

        resp = client.post("/api/books/reorganize", json={"file_ids": [bf.id]})
        assert resp.status_code == 200
        assert len(resp.json()["moved"]) == 1
        # The move happened but the marker (and its dir) survive.
        assert marker.exists()


# ---------------------------------------------------------------------------
# Delete book
# ---------------------------------------------------------------------------

class TestDeleteBook:
    def test_delete_removes_row_and_files(self, client: TestClient, db, make_book, library_dir):
        book = _book_with_file(make_book, db, library_dir)
        book_id = book.id
        fp = Path(book.files[0].file_path)

        resp = client.delete(f"/api/books/{book_id}")
        assert resp.status_code == 204
        assert db.query(Book).filter(Book.id == book_id).first() is None
        assert not fp.exists()
        assert not fp.parent.exists()  # emptied dir removed

    def test_row_deleted_even_when_file_removal_fails(
        self, client: TestClient, db, make_book, library_dir
    ):
        # Point the BookFile at a directory: unlink() raises, simulating a
        # failing disk cleanup. The row must be gone regardless — the old
        # order left a permanent ghost row when the crash hit the other way.
        stubborn = library_dir / "Stubborn Dir"
        stubborn.mkdir()
        book = make_book(title="Ghost", file_path=str(stubborn))
        db.commit()
        book_id = book.id

        resp = client.delete(f"/api/books/{book_id}")
        assert resp.status_code == 204
        assert db.query(Book).filter(Book.id == book_id).first() is None
        assert db.query(BookFile).filter(BookFile.book_id == book_id).first() is None
        assert stubborn.exists()  # cleanup failed, but no ghost row

    def test_delete_removes_cover(self, client: TestClient, db, make_book,
                                  library_dir, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.core.config.settings.data_dir", tmp_path / "data")
        from backend.core.config import settings
        settings.covers_dir.mkdir(parents=True, exist_ok=True)
        cover = settings.covers_dir / "42.jpg"
        cover.write_bytes(b"jpeg")

        book = _book_with_file(make_book, db, library_dir)
        book.cover_path = "42.jpg"
        db.commit()

        resp = client.delete(f"/api/books/{book.id}")
        assert resp.status_code == 204
        assert not cover.exists()


# ---------------------------------------------------------------------------
# Purge empty dirs
# ---------------------------------------------------------------------------

class TestPurgeEmptyDirs:
    def test_removes_junk_only_and_empty_dirs(self, client: TestClient, library_dir):
        junk_dir = library_dir / "Old Series"
        junk_dir.mkdir()
        (junk_dir / ".DS_Store").write_bytes(b"junk")
        (junk_dir / "._resource").write_bytes(b"appledouble")
        empty_dir = library_dir / "Empty"
        empty_dir.mkdir()

        resp = client.post("/api/books/purge-empty-dirs")
        assert resp.status_code == 200
        removed = resp.json()["removed"]
        assert "Old Series" in removed
        assert "Empty" in removed
        assert not junk_dir.exists()
        assert not empty_dir.exists()

    def test_keeps_syncthing_markers(self, client: TestClient, library_dir):
        synced = library_dir / "Synced Folder"
        synced.mkdir()
        (synced / ".stfolder").write_bytes(b"")

        resp = client.post("/api/books/purge-empty-dirs")
        assert resp.status_code == 200
        assert resp.json()["removed"] == []
        assert (synced / ".stfolder").exists()

    def test_hidden_directory_does_not_500_and_survives(self, client: TestClient, library_dir):
        # .stversions holds versioned copies of user files — must survive, and
        # the old code 500ed trying to unlink() a directory.
        parent = library_dir / "Series"
        versions = parent / ".stversions"
        versions.mkdir(parents=True)
        keep = versions / "Book v1.epub"
        keep.write_bytes(b"old version")

        resp = client.post("/api/books/purge-empty-dirs")
        assert resp.status_code == 200
        assert keep.exists()
        assert parent.exists()

    def test_keeps_dirs_with_real_content(self, client: TestClient, library_dir):
        full = library_dir / "Author"
        full.mkdir()
        (full / "Book.epub").write_bytes(b"content")
        (full / ".DS_Store").write_bytes(b"junk")

        resp = client.post("/api/books/purge-empty-dirs")
        assert resp.status_code == 200
        assert (full / "Book.epub").exists()
        assert (full / ".DS_Store").exists()  # junk only purged when it's ALL junk
