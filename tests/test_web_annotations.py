"""Web-created annotations + device adoption.

A highlight made in the web reader is stored under a provisional "web:<uuid>"
anchor with the selection's CFI. Devices never render the provisional anchor —
they locate the text natively and "adopt" it: the sync upsert carries
``adopted_from`` and the server retires the provisional row. Anchors are
deterministic per book copy, so concurrent adoption by two devices converges
on one canonical row.
"""
from backend.models.reading import Annotation, AnnotationTombstone


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
