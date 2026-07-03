"""The plugin's reading-history backfill must stay memory-bounded.

The original implementation materialised every ``page_stat_data`` row since the
watermark into one Lua table (tens of thousands of rows on a real device) and
resent the full ``books`` array with every chunk. These tests pin the windowed
replacement: keyset pagination over (start_time, rowid), short-lived read-only
connections per window, and per-chunk book subsetting. The server import is
idempotent (INSERT OR IGNORE on the identity key), which is what makes the
watermark-boundary refetch safe — that contract is asserted here too.
"""
import shutil
import subprocess
import tempfile

import pytest

from backend.api.tome_sync import TOMESYNC_PLUGIN_BUILD, _main_impl_lua


@pytest.fixture(scope="module")
def impl() -> str:
    return _main_impl_lua("http://localhost:8080", "tk_test", "tester")


def test_backfill_reads_in_keyset_windows(impl):
    """Page rows are fetched LIMIT-windowed with a (start_time, rowid) cursor —
    never all at once."""
    assert "start_time > %d OR (start_time = %d AND rowid > %d)" in impl
    assert "ORDER BY start_time, rowid LIMIT" in impl
    # the old slurp query must be gone
    assert '.. "WHERE start_time >= " .. since .. " ORDER BY start_time")' not in impl


def test_backfill_counts_instead_of_materialising(impl):
    """The progress total comes from COUNT(*), not from the length of an
    all-rows table."""
    assert "SELECT COUNT(*) FROM page_stat_data WHERE start_time >= " in impl


def test_backfill_sends_only_referenced_books(impl):
    """Each chunk carries only the book rows its ko_ids reference."""
    assert "chunk_books" in impl
    assert "books_by_id[r.ko_id]" in impl
    # the old full-table resend shipped the same `books` variable every chunk
    assert "device = dev, books = books," not in impl


def test_backfill_cursor_advances_only_on_server_ack(impl):
    """The keyset cursor moves only after a successful import response, so an
    interrupted run resumes from the server watermark."""
    i_resp = impl.index('local resp = apiRequest("POST", "/tome-sync/stats/import"')
    i_guard = impl.index('if type(resp) ~= "table" then', i_resp)
    i_advance = impl.index("cur_start, cur_rowid = last.start_time, last.rowid")
    assert i_resp < i_guard < i_advance


def test_server_import_is_idempotent_for_boundary_refetch(db, admin_user, make_book):
    """Rows re-sent across the watermark boundary must be no-ops — the plugin
    relies on this to start each run at (watermark, rowid -1)."""
    from backend.services.ko_stats_import import import_batch

    admin_user, _token = admin_user
    make_book(title="Window Test Book", author="A. Author")

    books = [{"ko_id": 1, "md5": "f" * 32, "title": "Window Test Book",
              "authors": "A. Author", "pages": 100, "total_read_pages": 10}]
    rows = [{"ko_id": 1, "page": p, "start_time": 1_700_000_000 + p, "duration": 30,
             "total_pages": 100} for p in range(1, 6)]

    first = import_batch(db, admin_user, device="testdev", books=books, page_stats=rows)
    assert first["page_rows_imported"] == 5

    # same rows again — the boundary-second refetch case
    second = import_batch(db, admin_user, device="testdev", books=books, page_stats=rows)
    assert second["page_rows_imported"] == 0
    assert second["page_rows_skipped"] == 5
    assert second["watermark"] == first["watermark"]


def test_plugin_build_bumped():
    assert TOMESYNC_PLUGIN_BUILD >= 26


def test_impl_still_compiles_under_luajit(impl):
    checker = shutil.which("luajit") or shutil.which("luac5.1")
    if not checker:
        pytest.skip("no LuaJIT/luac5.1 available to syntax-check")
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
        f.write(impl)
        path = f.name
    if "luajit" in checker:
        res = subprocess.run([checker, "-bl", path], capture_output=True, text=True)
    else:
        res = subprocess.run([checker, "-p", path], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[:2000]


def test_foreign_highlights_are_verified_before_painting(impl):
    """Build 28: incoming cross-device highlights verify their text via
    getTextFromXPointers, repair via _locateText, and keep server identity in
    repair_map — never painted on the wrong words, never re-anchored server-side."""
    assert "function TomeSync:_applyForeign" in impl
    assert "getTextFromXPointers" in impl
    assert "function TomeSync:_locateText" in impl
    assert "tomesync_repair_map" in impl
    # the old blind reconstruct (draw whatever the anchor resolves to) is gone
    assert "New highlight from another device: reconstruct so it renders." not in impl
    # pushes translate repaired items back to the server identity
    assert "it.anchor = anchor" in impl
