"""Web-created annotations + device adoption.

A highlight made in the web reader is stored under a provisional "web:<uuid>"
anchor with the selection's CFI. Devices never render the provisional anchor —
they locate the text natively and "adopt" it: the sync upsert carries
``adopted_from`` and the server retires the provisional row. Anchors are
deterministic per book copy, so concurrent adoption by two devices converges
on one canonical row.
"""
from backend.models.tome_sync import ApiKey, Annotation, AnnotationTombstone


def _api_key_for(db, user_id: int) -> str:
    plaintext = ApiKey.generate()
    db.add(ApiKey(user_id=user_id, key_hash=ApiKey.hash_key(plaintext),
                  key_prefix=plaintext[:11], label="test"))
    db.flush()
    return plaintext


def _sync(client, hdr, book_id, upserts=(), deletes=()):
    return client.post(f"/api/tome-sync/annotations/{book_id}/sync", headers=hdr,
                       json={"upserts": list(upserts), "deletes": list(deletes)})


def _create_web(client, book_id, **over):
    body = {
        "book_id": book_id,
        "highlighted_text": "The cheapest server is the one you turned off.",
        "cfi": "epubcfi(/6/18!/4/2/2,/1:0,/1:46)",
        "color": "yellow",
        "chapter": "1. What Is FinOps?",
        "datetime": "2026-07-02 10:00:00",
        **over,
    }
    return client.post("/api/annotations", json=body)


XP = "/body/DocFragment[9]/p[4]/text().0"
XP_END = "/body/DocFragment[9]/p[4]/text().46"


def test_create_web_annotation(client, db, admin_user, make_book):
    book = make_book()
    r = _create_web(client, book.id, note="from the web")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["anchor"].startswith("web:")
    assert a["cfi"].startswith("epubcfi(")
    assert a["datetime_updated"] == "2026-07-02 10:00:00"

    # Web per-book GET carries the cfi; the plugin GET lists it as alive.
    user, _ = admin_user
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    web = client.get(f"/api/books/{book.id}/annotations").json()
    assert web[0]["cfi"] == a["cfi"]
    plug = client.get(f"/api/tome-sync/annotations/{book.id}", headers=hdr).json()
    assert [x["anchor"] for x in plug["annotations"]] == [a["anchor"]]


def test_adoption_retires_provisional(client, db, admin_user, make_book):
    user, _ = admin_user
    book = make_book()
    prov = _create_web(client, book.id).json()["anchor"]
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}

    # Device locates the text and re-anchors it natively.
    r = _sync(client, hdr, book.id, upserts=[{
        "anchor": XP, "anchor_end": XP_END,
        "highlighted_text": "The cheapest server is the one you turned off.",
        "color": "yellow", "chapter": "1. What Is FinOps?",
        "datetime": "2026-07-02 10:00:00", "datetime_updated": "2026-07-02 10:00:00",
        "adopted_from": prov,
    }])
    assert r.status_code == 200, r.text
    anchors = [x["anchor"] for x in r.json()["annotations"]]
    assert anchors == [XP]                     # canonical present, provisional gone
    assert r.json()["tombstones"] == []        # identity move, not a delete
    assert db.query(Annotation).filter_by(book_id=book.id).count() == 1


def test_double_adoption_is_idempotent(client, db, admin_user, make_book):
    """Second device adopts after the first: same deterministic anchor → dedupe;
    the missing provisional is a no-op."""
    user, _ = admin_user
    book = make_book()
    prov = _create_web(client, book.id).json()["anchor"]
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    item = {
        "anchor": XP, "anchor_end": XP_END,
        "highlighted_text": "The cheapest server is the one you turned off.",
        "color": "yellow", "datetime": "2026-07-02 10:00:00",
        "datetime_updated": "2026-07-02 10:00:00", "adopted_from": prov,
    }
    _sync(client, hdr, book.id, upserts=[item])
    r = _sync(client, hdr, book.id, upserts=[item])   # device B, same computation
    assert r.status_code == 200
    assert [x["anchor"] for x in r.json()["annotations"]] == [XP]
    assert db.query(Annotation).filter_by(book_id=book.id).count() == 1


def test_web_delete_before_adoption(client, db, admin_user, make_book):
    """Deleting the web highlight before any device adopts it tombstones the
    provisional; the device sees no alive web anchor and adopts nothing."""
    user, _ = admin_user
    book = make_book()
    created = _create_web(client, book.id).json()
    assert client.delete(f"/api/annotations/{created['id']}").status_code == 204

    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    g = client.get(f"/api/tome-sync/annotations/{book.id}", headers=hdr).json()
    assert g["annotations"] == []
    assert [t["anchor"] for t in g["tombstones"]] == [created["anchor"]]
    # A straggling adoption for the now-deleted provisional creates the canonical
    # copy (the device DID make a local highlight) — acceptable; no crash.
    r = _sync(client, hdr, book.id, upserts=[{
        "anchor": XP, "highlighted_text": "x", "datetime": "2026-07-02 11:00:00",
        "adopted_from": created["anchor"],
    }])
    assert r.status_code == 200


def test_edit_note_bumps_mtime_strictly(client, db, admin_user, make_book):
    """A web edit must win LWW on devices even when the server clock is at or
    behind the row's mtime (created here with a far-future device timestamp)."""
    book = make_book()
    created = _create_web(client, book.id, datetime="2099-01-01 00:00:00").json()
    r = client.put(f"/api/annotations/{created['id']}", json={"note": "edited on web"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["note"] == "edited on web"
    assert out["datetime_updated"] > "2099-01-01 00:00:00"


def test_create_validation(client, db, admin_user, make_book):
    book = make_book()
    assert _create_web(client, book.id, highlighted_text="  ").status_code == 422
    r = client.post("/api/annotations", json={"book_id": 999999, "highlighted_text": "x"})
    assert r.status_code == 404
