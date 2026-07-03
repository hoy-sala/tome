"""Hardcover sync — crypto, ISBN helpers, matcher guard, reconciler, endpoints."""
import httpx
import pytest
import respx

from backend.models.notification import Notification
from backend.models.user_book_status import UserBookStatus
from backend.services import hardcover_sync as hs
from backend.services.hardcover_sync import HARDCOVER_URL


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """Tests must not sleep 1.1s per mocked request."""
    monkeypatch.setattr(hs, "MIN_REQUEST_SPACING", 0.0)


# ── crypto ────────────────────────────────────────────────────────────────────

def test_crypto_roundtrip_and_tamper():
    from backend.core.crypto import decrypt_secret, encrypt_secret
    ct = encrypt_secret("hc_secret_token")
    assert ct != "hc_secret_token"
    assert decrypt_secret(ct) == "hc_secret_token"
    assert decrypt_secret(None) is None
    assert decrypt_secret("") is None
    assert decrypt_secret("garbage-not-fernet") is None


# ── ISBN helpers ──────────────────────────────────────────────────────────────

def test_normalize_isbn():
    assert hs.normalize_isbn("978-0-306-40615-7") == "9780306406157"
    assert hs.normalize_isbn("0-306-40615-2") == "0306406152"
    assert hs.normalize_isbn("155404295x") == "155404295X"
    assert hs.normalize_isbn("not an isbn") is None
    assert hs.normalize_isbn(None) is None
    assert hs.normalize_isbn("12345") is None


def test_isbn10_to_13_known_pair():
    assert hs.isbn10_to_13("0306406152") == "9780306406157"


def test_isbn_variants_includes_13_for_a_10():
    assert hs.isbn_variants("0-306-40615-2") == ["0306406152", "9780306406157"]
    assert hs.isbn_variants("9780306406157") == ["9780306406157"]
    assert hs.isbn_variants(None) == []


# ── reconciler diff ───────────────────────────────────────────────────────────

def _row(**kw) -> UserBookStatus:
    defaults = dict(user_id=1, book_id=1, status="unread")
    defaults.update(kw)
    return UserBookStatus(**defaults)


def test_needs_sync_rating_change():
    assert hs.needs_sync(_row(rating=4.5))
    assert not hs.needs_sync(_row(rating=4.5, hardcover_synced_rating=4.5))
    # legacy int snapshot vs float rating: 4 == 4.0 → no push
    assert not hs.needs_sync(_row(rating=4, hardcover_synced_rating=4.0))


def test_needs_sync_never_propagates_rating_clear():
    assert not hs.needs_sync(_row(rating=None, hardcover_synced_rating=4.0))


def test_needs_sync_status_and_progress():
    assert hs.needs_sync(_row(status="reading", progress_pct=0.2))
    assert hs.needs_sync(_row(status="read", hardcover_synced_status="reading",
                              progress_pct=1.0, hardcover_synced_pct=1.0))
    assert not hs.needs_sync(_row(status="reading", hardcover_synced_status="reading",
                                  progress_pct=0.5, hardcover_synced_pct=0.495))
    assert hs.needs_sync(_row(status="reading", hardcover_synced_status="reading",
                              progress_pct=0.52, hardcover_synced_pct=0.50))
    # unread/shelved never push
    assert not hs.needs_sync(_row(status="shelved", progress_pct=0.4))


def test_needs_sync_progress_is_forward_only():
    # A regression (stale device rewind, re-opened book) is never mirrored to
    # the public profile.
    assert not hs.needs_sync(_row(status="reading", hardcover_synced_status="reading",
                                  progress_pct=0.62, hardcover_synced_pct=0.90))


def test_progress_pages_math():
    assert hs._progress_pages(_row(status="reading", progress_pct=0.5), 384) == 192
    assert hs._progress_pages(_row(status="read", progress_pct=0.4), 384) == 384
    assert hs._progress_pages(_row(status="reading", progress_pct=0.5), None) is None
    assert hs._progress_pages(_row(status="reading", progress_pct=0.5), 0) is None
    assert hs._progress_pages(_row(status="reading", progress_pct=1.5), 100) == 100


# ── matcher ───────────────────────────────────────────────────────────────────

def _search_payload(hits):
    return {"data": {"search": {"results": {"hits": hits}}}}


@respx.mock
async def test_match_book_isbn_hit(make_book):
    book = make_book(title="Dune", isbn="9780441013593")
    respx.post(HARDCOVER_URL).mock(return_value=httpx.Response(200, json={
        "data": {"editions": [{"id": 555, "pages": 412, "book_id": 77,
                               "book": {"id": 77, "title": "Dune", "pages": 412}}]}
    }))
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is True
    assert book.hardcover_book_id == 77
    assert book.hardcover_edition_id == 555
    assert book.hardcover_pages == 412
    assert book.hardcover_match_method == "isbn13"


@respx.mock
async def test_match_book_search_guard_refuses_dissimilar(make_book):
    book = make_book(title="A Very Specific Novel", author="Jane Author", isbn=None)
    respx.post(HARDCOVER_URL).mock(return_value=httpx.Response(200, json=_search_payload([
        {"document": {"id": 1, "title": "Completely Different Book",
                      "author_names": ["Jane Author"]}},
        {"document": {"id": 2, "title": "A Very Specific Novel",
                      "author_names": ["Somebody Else Entirely"]}},
    ])))
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is False
    assert book.hardcover_match_method == "none"
    assert book.hardcover_book_id is None
    assert book.hardcover_matched_at is not None


@respx.mock
async def test_match_book_search_accepts_close_match(make_book):
    book = make_book(title="Project Hail Mary", author="Andy Weir", isbn=None)

    def responder(request):
        body = request.read().decode()
        if "SearchBook" in body:
            return httpx.Response(200, json=_search_payload([
                {"document": {"id": 90, "title": "Project Hail Mary",
                              "author_names": ["Andy Weir"]}},
            ]))
        return httpx.Response(200, json={"data": {"books": [
            {"id": 90, "pages": 476, "editions": [{"id": 901, "pages": 476}]}
        ]}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is True
    assert book.hardcover_book_id == 90
    assert book.hardcover_edition_id == 901
    assert book.hardcover_pages == 476
    assert book.hardcover_match_method == "search"


@respx.mock
async def test_match_book_volume_aware_search(make_book):
    """LN volumes share a bare series title in Tome; the matcher must pick the
    per-volume Hardcover record, never the unmarked vol-1/series record or the
    manga variant (shapes taken from the live catalogue)."""
    book = make_book(title="Black Summoner", author="Doufu Mayoi",
                     series="Black Summoner", series_index=2, isbn=None)
    seen_queries = []

    def responder(request):
        import json
        body = json.loads(request.read())
        if "SearchBook" in body["query"]:
            seen_queries.append(body["variables"]["q"])
            return httpx.Response(200, json=_search_payload([
                {"document": {"id": 2213196, "title": "Black Summoner",
                              "author_names": ["Doufu Mayoi"]}},           # unmarked vol-1 record
                {"document": {"id": 1661771, "title": "Black Summoner (Manga) Vol 2",
                              "author_names": ["Gin Ammo"]}},              # manga variant
                {"document": {"id": 2624495, "title": "Black Summoner, Vol. 2",
                              "author_names": []}},                        # the right one
            ]))
        return httpx.Response(200, json={"data": {"books": [
            {"id": 2624495, "pages": 230, "editions": [{"id": 999, "pages": 230}]}
        ]}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is True
    assert book.hardcover_book_id == 2624495
    assert book.hardcover_pages == 230
    # The query itself must carry the volume, not the bare shared title.
    assert "Vol. 2" in seen_queries[0]


@respx.mock
async def test_match_book_splits_multi_author_strings(make_book):
    """Tome's 'A and B' author string must match individual author_names."""
    book = make_book(title="Cloud FinOps", author="J.R. Storment and Mike Fuller", isbn=None)

    def responder(request):
        body = request.read().decode()
        if "SearchBook" in body:
            return httpx.Response(200, json=_search_payload([
                {"document": {"id": 77, "title": "Cloud FinOps",
                              "author_names": ["J.R. Storment", "Mike Fuller"]}},
            ]))
        return httpx.Response(200, json={"data": {"books": [
            {"id": 77, "pages": 457, "editions": [{"id": 771, "pages": 457}]}
        ]}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is True
    assert book.hardcover_book_id == 77
    assert book.hardcover_match_method == "search"


@respx.mock
async def test_match_book_standalone_rejects_numbered_volume(make_book):
    book = make_book(title="Dune", author="Frank Herbert", isbn=None)
    respx.post(HARDCOVER_URL).mock(return_value=httpx.Response(200, json=_search_payload([
        {"document": {"id": 5, "title": "Dune Vol. 3", "author_names": ["Frank Herbert"]}},
    ])))
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is False
    assert book.hardcover_match_method == "none"


@respx.mock
async def test_match_book_prefers_popular_record_over_stub(make_book):
    """Vol-1 case observed live: the '… Vol. 1' query surfaces only a
    user-created stub (users_count 1, no author); the real record has the bare
    series title and only appears for the bare query. Both query forms must be
    searched and the community record preferred."""
    book = make_book(title="Black Summoner", author="Doufu Mayoi",
                     series="Black Summoner", series_index=1, isbn=None)
    import json as _json
    queries = []

    def responder(request):
        body = _json.loads(request.read())
        if "SearchBook" in body["query"]:
            q = body["variables"]["q"]
            queries.append(q)
            if "Vol. 1" in q:
                return httpx.Response(200, json=_search_payload([
                    {"document": {"id": 2624493, "title": "Black Summoner -, Vol. 1",
                                  "author_names": [], "users_count": 1}},
                ]))
            return httpx.Response(200, json=_search_payload([
                {"document": {"id": 2213196, "title": "Black Summoner",
                              "author_names": ["Doufu Mayoi"], "users_count": 58}},
            ]))
        return httpx.Response(200, json={"data": {"books": [
            {"id": 2213196, "pages": 230, "editions": [{"id": 555, "pages": 230}]}
        ]}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is True
    assert book.hardcover_book_id == 2213196   # the real record wins
    assert len(queries) == 2                    # both query forms were searched


@respx.mock
async def test_match_book_isbn_hit_sanity_checked(make_book):
    """A stored ISBN resolving to the WRONG volume (legacy wrong-edition ISBNs,
    or a bad catalogue mapping — observed live: vol 2's ISBN → 'Volume 10')
    must fall through to the guarded search instead of matching."""
    book = make_book(title="Black Summoner", author="Doufu Mayoi",
                     series="Black Summoner", series_index=2, isbn="9781718375666")

    def responder(request):
        body = request.read().decode()
        if "EditionByIsbn" in body:
            return httpx.Response(200, json={"data": {"editions": [
                {"id": 32716494, "title": None, "pages": 246, "book_id": 2440311,
                 "book": {"id": 2440311, "title": "Black Summoner: Volume 10", "pages": 246}}
            ]}})
        if "SearchBook" in body:
            return httpx.Response(200, json=_search_payload([
                {"document": {"id": 2624495, "title": "Black Summoner, Vol. 2",
                              "author_names": []}},
            ]))
        return httpx.Response(200, json={"data": {"books": [
            {"id": 2624495, "pages": 230, "editions": [{"id": 999, "pages": 230}]}
        ]}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        assert await hs.match_book(client, "tok", book) is True
    assert book.hardcover_book_id == 2624495
    assert book.hardcover_match_method == "search"


def test_isbn_hit_plausible(make_book):
    vol2 = make_book(title="Black Summoner", series="Black Summoner", series_index=2)
    assert not hs._isbn_hit_plausible(vol2, "Black Summoner: Volume 10")
    assert hs._isbn_hit_plausible(vol2, "Black Summoner: Volume 2")
    assert hs._isbn_hit_plausible(vol2, "Black Summoner")   # unnumbered title: permissive
    assert not hs._isbn_hit_plausible(vol2, "Black Summoner (Manga) Vol 2")
    standalone = make_book(title="Dune")
    assert not hs._isbn_hit_plausible(standalone, "Dune Vol. 3")
    assert not hs._isbn_hit_plausible(standalone, "A Totally Unrelated Cookbook")
    assert hs._isbn_hit_plausible(standalone, "Dune")
    assert hs._isbn_hit_plausible(standalone, "")           # nothing to check


def test_vol_and_author_helpers():
    assert hs._vol_in_title("Black Summoner, Vol. 2") == 2
    assert hs._vol_in_title("Overlord Volume 14") == 14
    assert hs._vol_in_title("Berserk v03") == 3
    assert hs._vol_in_title("Dune") is None
    assert hs._split_authors("J.R. Storment and Mike Fuller") == ["J.R. Storment", "Mike Fuller"]
    assert hs._split_authors("A, B & C") == ["A", "B", "C"]
    assert hs._split_authors(None) == []
    assert hs._is_manga_title("Black Summoner (Manga) Vol 2")
    assert not hs._is_manga_title("Black Summoner, Vol. 2")


# ── push flow ─────────────────────────────────────────────────────────────────

@respx.mock
async def test_push_row_full_flow(db, admin_user, make_book):
    user, _ = admin_user
    user.hardcover_user_id = 42
    book = make_book(title="Dune", isbn="9780441013593")
    book.hardcover_book_id = 77
    book.hardcover_edition_id = 555
    book.hardcover_pages = 400
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="reading",
                         progress_pct=0.5, rating=4.5)
    db.add(row)
    db.flush()

    seen = []

    def responder(request):
        body = request.read().decode()
        seen.append(body)
        if "mutation InsertUserBook" in body:
            return httpx.Response(200, json={"data": {"insert_user_book": {"id": 1001, "error": None}}})
        if "mutation UpdateUserBook" in body:
            return httpx.Response(200, json={"data": {"update_user_book": {"id": 1001, "error": None}}})
        if "mutation InsertRead" in body:
            return httpx.Response(200, json={"data": {"insert_user_book_read": {"id": 2002, "error": None}}})
        if "query UserBook" in body:
            return httpx.Response(200, json={"data": {"user_books": []}})
        return httpx.Response(200, json={"data": {}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        await hs._push_row(client, "tok", user, row, book)

    assert row.hardcover_user_book_id == 1001
    assert row.hardcover_read_id == 2002
    assert row.hardcover_synced_rating == 4.5
    assert row.hardcover_synced_status == "reading"
    assert row.hardcover_synced_pct == 0.5
    assert row.hardcover_error is None
    # progress_pages must be page-based: round(0.5 × 400) = 200
    assert any('"progress_pages": 200' in b or '"progress_pages":200' in b for b in seen)


@respx.mock
async def test_push_row_adopts_auto_created_read(db, admin_user, make_book):
    """insert_user_book auto-creates an initial read row on Hardcover (observed
    live) — the push must adopt it, not insert a duplicate."""
    user, _ = admin_user
    user.hardcover_user_id = 42
    book = make_book(title="Dune")
    book.hardcover_book_id = 77
    book.hardcover_pages = 400
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="reading", progress_pct=0.5)
    db.add(row)
    db.flush()

    def responder(request):
        body = request.read().decode()
        assert "mutation InsertRead" not in body, "must adopt the auto-created read, not insert"
        if "query UserBook" in body:
            return httpx.Response(200, json={"data": {"user_books": []}})
        if "mutation InsertUserBook" in body:
            return httpx.Response(200, json={"data": {"insert_user_book": {"id": 1001, "error": None}}})
        if "query Reads" in body:
            return httpx.Response(200, json={"data": {"user_book_reads": [{"id": 3003}]}})
        if "mutation UpdateRead" in body:
            return httpx.Response(200, json={"data": {"update_user_book_read": {"id": 3003, "error": None}}})
        return httpx.Response(200, json={"data": {}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        await hs._push_row(client, "tok", user, row, book)
    assert row.hardcover_read_id == 3003
    assert row.hardcover_synced_pct == 0.5


@respx.mock
async def test_push_row_status_only_without_pages(db, admin_user, make_book):
    user, _ = admin_user
    user.hardcover_user_id = 42
    book = make_book(title="Obscure Book")
    book.hardcover_book_id = 88
    book.hardcover_pages = None
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="reading", progress_pct=0.3)
    db.add(row)
    db.flush()

    def responder(request):
        body = request.read().decode()
        assert "mutation InsertRead" not in body and "mutation UpdateRead" not in body, \
            "page-less book must not push progress reads"
        if "query UserBook" in body:
            return httpx.Response(200, json={"data": {"user_books": [
                {"id": 1001, "status_id": None, "user_book_reads": []}]}})
        if "mutation UpdateUserBook" in body:
            return httpx.Response(200, json={"data": {"update_user_book": {"id": 1001, "error": None}}})
        return httpx.Response(200, json={"data": {}})

    respx.post(HARDCOVER_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as client:
        await hs._push_row(client, "tok", user, row, book)
    assert row.hardcover_synced_status == "reading"
    assert row.hardcover_synced_pct == 0.3  # snapshotted so needs_sync stops firing
    assert not hs.needs_sync(row)


# ── auth failure → expired + one notification ────────────────────────────────

def test_mark_token_expired_notifies_once(db, admin_user):
    user, _ = admin_user
    user.hardcover_token = "enc"
    user.hardcover_token_status = "ok"
    hs.mark_token_expired(db, user)
    hs.mark_token_expired(db, user)
    assert user.hardcover_token_status == "expired"
    notes = db.query(Notification).filter_by(user_id=user.id, kind="hardcover_token_expired").all()
    assert len(notes) == 1


# ── API endpoints ─────────────────────────────────────────────────────────────

def test_link_flow_and_status(client, db, admin_user, monkeypatch):
    user, _ = admin_user

    async def fake_verify(token):
        # Hardcover needs the literal "Bearer " prefix; the endpoint normalizes
        # a bare pasted token (verified against the live API).
        assert token == "Bearer hc_tok"
        return {"id": 42, "username": "benedict"}

    monkeypatch.setattr(hs, "verify_token", fake_verify)
    started_for: list[int] = []
    monkeypatch.setattr(hs, "start_manual_sync", lambda uid: started_for.append(uid) or True)

    r = client.get("/api/hardcover/status")
    assert r.status_code == 200 and r.json() == {"linked": False}

    r = client.post("/api/hardcover/link", json={"token": "hc_tok"})
    assert r.status_code == 200
    assert r.json()["username"] == "benedict"
    # Linking kicks off the initial backfill itself.
    assert r.json()["sync_started"] is True
    assert started_for == [user.id]
    assert user.hardcover_sync_enabled is True
    assert user.hardcover_user_id == 42
    # token stored encrypted (with the normalized Bearer prefix), decrypts back
    from backend.core.crypto import decrypt_secret
    assert "hc_tok" not in (user.hardcover_token or "")
    assert decrypt_secret(user.hardcover_token) == "Bearer hc_tok"

    r = client.get("/api/hardcover/status")
    body = r.json()
    assert body["linked"] is True
    assert body["username"] == "benedict"
    assert body["token_status"] == "ok"

    r = client.put("/api/hardcover/settings", json={"sync_enabled": False})
    assert r.status_code == 200 and r.json()["sync_enabled"] is False

    r = client.delete("/api/hardcover/link")
    assert r.status_code == 204
    assert user.hardcover_token is None
    assert client.get("/api/hardcover/status").json() == {"linked": False}


def test_link_rejects_bad_token(client, monkeypatch):
    async def fake_verify(token):
        raise hs.HardcoverAuthError()

    monkeypatch.setattr(hs, "verify_token", fake_verify)
    r = client.post("/api/hardcover/link", json={"token": "bad"})
    assert r.status_code == 400


def test_sync_now_requires_link(client):
    r = client.post("/api/hardcover/sync-now")
    assert r.status_code == 400


def test_sync_now_resets_parked_rows(client, db, admin_user, make_book, monkeypatch):
    user, _ = admin_user
    from backend.core.crypto import encrypt_secret
    user.hardcover_token = encrypt_secret("t")
    user.hardcover_token_status = "ok"
    book = make_book(title="Parked")
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="read",
                         hardcover_fail_count=10, hardcover_error="boom")
    db.add(row)
    db.flush()

    monkeypatch.setattr(hs, "start_manual_sync", lambda uid: True)
    r = client.post("/api/hardcover/sync-now")
    assert r.status_code == 200 and r.json()["started"] is True
    db.refresh(row)
    assert row.hardcover_fail_count == 0


def _link_test_user(user):
    from backend.core.crypto import encrypt_secret
    user.hardcover_token = encrypt_secret("Bearer t")
    user.hardcover_token_status = "ok"
    user.hardcover_user_id = 42


def test_hardcover_books_page_endpoint(client, db, admin_user, make_book):
    """The /hardcover page's data source: every status-row book with its state."""
    user, _ = admin_user
    _link_test_user(user)
    matched = make_book(title="Black Summoner", series="Black Summoner", series_index=10)
    matched.hardcover_book_id = 2440311
    matched.hardcover_slug = "black-summoner-volume-10"
    matched.hardcover_match_method = "isbn13"
    unmatched = make_book(title="Obscure Zine")
    unmatched.hardcover_match_method = "none"
    from datetime import datetime as _dt
    unmatched.hardcover_matched_at = _dt.utcnow()
    pending = make_book(title="Fresh Upload")
    for i, b in enumerate((matched, unmatched, pending)):
        db.add(UserBookStatus(user_id=user.id, book_id=b.id, status="reading",
                              progress_pct=0.1 * (i + 1)))
    db.flush()

    r = client.get("/api/hardcover/books")
    assert r.status_code == 200
    by_id = {i["book_id"]: i for i in r.json()}
    assert by_id[matched.id]["state"] == "matched"
    assert by_id[matched.id]["slug"] == "black-summoner-volume-10"
    assert by_id[matched.id]["series_index"] == 10       # volume is renderable
    assert by_id[unmatched.id]["state"] == "unmatched"
    assert by_id[pending.id]["state"] == "pending"


def test_matches_visible_in_books_endpoint(client, db, admin_user, make_book):
    user, _ = admin_user
    _link_test_user(user)
    book = make_book(title="Dune", author="Frank Herbert")
    book.hardcover_book_id = 77
    book.hardcover_slug = "dune"
    book.hardcover_match_method = "isbn13"
    book.hardcover_pages = 412
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="read"))
    db.flush()

    items = client.get("/api/hardcover/books").json()
    mine = [i for i in items if i["book_id"] == book.id]
    assert mine and mine[0]["slug"] == "dune" and mine[0]["method"] == "isbn13"


def test_rematch_retry_clears_match_and_deletes_profile_entry(client, db, admin_user, make_book, monkeypatch):
    user, _ = admin_user
    _link_test_user(user)
    book = make_book(title="Wrongly Matched")
    book.hardcover_book_id = 999
    book.hardcover_slug = "wrong-record"
    book.hardcover_match_method = "search"
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="reading",
                         progress_pct=0.5, hardcover_user_book_id=1234,
                         hardcover_read_id=55, hardcover_synced_pct=0.5,
                         hardcover_synced_status="reading")
    db.add(row)
    db.flush()

    deleted: list[int] = []

    async def fake_delete(client_, token, ub_id):
        deleted.append(ub_id)
        return True

    monkeypatch.setattr(hs, "delete_user_book", fake_delete)
    r = client.post(f"/api/hardcover/books/{book.id}/rematch", json={"mode": "retry"})
    assert r.status_code == 200
    assert r.json()["removed_from_profile"] is True
    assert deleted == [1234]
    db.refresh(book); db.refresh(row)
    assert book.hardcover_book_id is None
    assert book.hardcover_match_method is None       # eligible for re-match
    assert row.hardcover_user_book_id is None
    assert row.hardcover_synced_pct is None          # will re-push after re-match


def test_rematch_exclude_stops_sync_attempts(client, db, admin_user, make_book, monkeypatch):
    user, _ = admin_user
    _link_test_user(user)
    book = make_book(title="Not On Hardcover")
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="read", rating=5)
    db.add(row)
    db.flush()

    async def fake_delete(client_, token, ub_id):
        raise AssertionError("nothing to delete")

    monkeypatch.setattr(hs, "delete_user_book", fake_delete)
    r = client.post(f"/api/hardcover/books/{book.id}/rematch", json={"mode": "exclude"})
    assert r.status_code == 200
    db.refresh(book)
    assert book.hardcover_match_method == "excluded"
    # appears in the page's book list, flagged
    items = client.get("/api/hardcover/books").json()
    assert any(i["book_id"] == book.id and i["state"] == "excluded" for i in items)
    # and Sync-now must NOT clear the exclusion (only 'none' markers)
    monkeypatch.setattr(hs, "start_manual_sync", lambda uid: True)
    client.post("/api/hardcover/sync-now")
    db.refresh(book)
    assert book.hardcover_match_method == "excluded"


@respx.mock
async def test_failed_match_not_retried_next_cycle(db, admin_user, make_book):
    """Regression: the failed-match commit bumps Book.updated_at (onupdate)
    PAST the in-flight matched_at — the retry guard must still hold, or every
    cycle re-matches (and re-bills) every unmatched book forever."""
    user, _ = admin_user
    _link_test_user(user)
    book = make_book(title="Never On Hardcover", author="Nobody")
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="read", rating=4))
    db.flush()

    route = respx.post(HARDCOVER_URL).mock(
        return_value=httpx.Response(200, json=_search_payload([])))
    async with httpx.AsyncClient() as client:
        stats1 = await hs.sync_user(db, client, user, hs._Budget(50))
        calls_after_first = route.call_count
        stats2 = await hs.sync_user(db, client, user, hs._Budget(50))
    assert stats1["skipped_unmatched"] == 1
    assert stats2["skipped_unmatched"] == 1
    assert route.call_count == calls_after_first, "second cycle must not re-match"


@respx.mock
async def test_sync_user_skips_excluded_without_requests(db, admin_user, make_book):
    user, _ = admin_user
    _link_test_user(user)
    book = make_book(title="Excluded Book")
    book.hardcover_match_method = "excluded"
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="read", rating=4))
    db.flush()

    route = respx.post(HARDCOVER_URL).mock(
        return_value=httpx.Response(200, json={"data": {}}))
    budget = hs._Budget(10)
    async with httpx.AsyncClient() as client:
        stats = await hs.sync_user(db, client, user, budget)
    assert stats["pushed"] == 0
    assert budget.used == 0          # skip must not consume budget
    assert not route.called          # and must make zero API calls


def test_manual_match_search_endpoint(client, db, admin_user, monkeypatch):
    user, _ = admin_user
    _link_test_user(user)

    async def fake_search(token, q, limit=8):
        assert q == "black summoner"
        return [{"hardcover_book_id": 785858, "title": "Black Summoner: Volume 1",
                 "authors": ["Doufu Mayoi"], "slug": "black-summoner-volume-1",
                 "users_count": 12, "cover_url": None, "series": "Black Summoner"}]

    monkeypatch.setattr(hs, "search_candidates", fake_search)
    r = client.get("/api/hardcover/search", params={"q": "black summoner"})
    assert r.status_code == 200
    assert r.json()[0]["hardcover_book_id"] == 785858


def test_manual_match_pins_record_and_clears_old_state(client, db, admin_user, make_book, monkeypatch):
    user, _ = admin_user
    _link_test_user(user)
    book = make_book(title="Black Summoner", series="Black Summoner", series_index=1)
    book.hardcover_book_id = 2624493            # the stub it wrongly matched
    book.hardcover_slug = "stub-record"
    book.hardcover_match_method = "search"
    row = UserBookStatus(user_id=user.id, book_id=book.id, status="reading",
                         progress_pct=0.42, hardcover_user_book_id=111,
                         hardcover_synced_pct=0.42, hardcover_synced_status="reading")
    db.add(row)
    db.flush()

    deleted: list[int] = []

    async def fake_delete(client_, token, ub_id):
        deleted.append(ub_id)
        return True

    async def fake_resolve(token, b, hc_id):
        assert hc_id == 785858
        b.hardcover_book_id = hc_id
        b.hardcover_slug = "black-summoner-volume-1"
        b.hardcover_edition_id = 30789992
        b.hardcover_pages = 227
        b.hardcover_match_method = "manual"
        from datetime import datetime as _dt
        b.hardcover_matched_at = _dt.utcnow()

    monkeypatch.setattr(hs, "delete_user_book", fake_delete)
    monkeypatch.setattr(hs, "resolve_manual_match", fake_resolve)

    r = client.post(f"/api/hardcover/books/{book.id}/match", json={"hardcover_book_id": 785858})
    assert r.status_code == 200
    assert r.json()["slug"] == "black-summoner-volume-1"
    assert deleted == [111]                     # old profile entry removed
    db.refresh(book); db.refresh(row)
    assert book.hardcover_book_id == 785858
    assert book.hardcover_match_method == "manual"
    assert row.hardcover_user_book_id is None   # push state reset → re-pushes to the pick
    assert row.hardcover_synced_pct is None
    # 'manual' is not auto-cleared by Sync-now (only 'none' markers are)
    monkeypatch.setattr(hs, "start_manual_sync", lambda uid: True)
    client.post("/api/hardcover/sync-now")
    db.refresh(book)
    assert book.hardcover_match_method == "manual"


def test_sync_now_retries_unmatched_books(client, db, admin_user, make_book, monkeypatch):
    user, _ = admin_user
    from datetime import datetime
    from backend.core.crypto import encrypt_secret
    user.hardcover_token = encrypt_secret("t")
    user.hardcover_token_status = "ok"
    book = make_book(title="Missed Last Month")
    book.hardcover_match_method = "none"
    book.hardcover_matched_at = datetime.utcnow()
    db.add(UserBookStatus(user_id=user.id, book_id=book.id, status="read"))
    db.flush()

    monkeypatch.setattr(hs, "start_manual_sync", lambda uid: True)
    r = client.post("/api/hardcover/sync-now")
    assert r.status_code == 200
    db.refresh(book)
    # Explicit click clears the failed-match marker so the matcher tries again.
    assert book.hardcover_match_method is None
    assert book.hardcover_matched_at is None
