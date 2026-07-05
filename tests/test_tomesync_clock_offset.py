"""Clock-offset guard for annotation sync (plugin build 32).

LWW stamps are wall-clock strings. Stamps a device minted stay in that device's
frame (accepted cross-device skew); stamps the SERVER minted (web create/edit/
delete) are shifted into the requesting device's frame — computed from the
`device_time` the plugin stamps on each sync — so a server clock hours ahead of
a device can't make a web delete/edit permanently outrank the user's next local
change (the silent highlight-swallowing class).
"""
from datetime import datetime, timedelta

from backend.api.tome_sync import _clock_offset_seconds, _shift_ko_dt, _KO_DT_FMT
from backend.models.tome_sync import ApiKey, Annotation, AnnotationTombstone


def _api_key_for(db, user_id: int) -> str:
    plaintext = ApiKey.generate()
    db.add(ApiKey(user_id=user_id, key_hash=ApiKey.hash_key(plaintext),
                  key_prefix=plaintext[:11], label="test"))
    db.flush()
    return plaintext


def _hl(anchor, text="t", note=None, dt="2026-06-03 10:00:00", dtu=None):
    return {"anchor": anchor, "highlighted_text": text, "note": note,
            "chapter": "C1", "color": "yellow", "datetime": dt, "datetime_updated": dtu}


def _sync(client, hdr, book_id, upserts=(), deletes=(), device_time=None):
    body = {"upserts": list(upserts), "deletes": list(deletes)}
    if device_time is not None:
        body["device_time"] = device_time
    return client.post(f"/api/tome-sync/annotations/{book_id}/sync", headers=hdr, json=body)


def _dev_now(behind_hours: float = 0) -> str:
    """A device wall-clock string N hours behind the server's clock."""
    return (datetime.now() - timedelta(hours=behind_hours)).strftime(_KO_DT_FMT)


A1 = "/body/DocFragment[2]/p[1]/text().0"


# ── unit: offset + shift helpers ─────────────────────────────────────────────

def test_offset_zero_without_device_time():
    assert _clock_offset_seconds(None) == 0
    assert _clock_offset_seconds("") == 0
    assert _clock_offset_seconds("not a datetime") == 0


def test_offset_small_skew_is_noise():
    # 30s behind: below tolerance, treated as synchronized
    assert _clock_offset_seconds(_dev_now(30 / 3600)) == 0


def test_offset_detects_slow_device_clock():
    off = _clock_offset_seconds(_dev_now(3))
    assert 3 * 3600 - 5 <= off <= 3 * 3600 + 5


def test_shift_ko_dt():
    assert _shift_ko_dt("2026-06-03 10:00:00", -3600) == "2026-06-03 09:00:00"
    assert _shift_ko_dt("2026-06-03 10:00:00", 0) == "2026-06-03 10:00:00"
    assert _shift_ko_dt(None, -3600) is None
    assert _shift_ko_dt("garbage", -3600) == "garbage"


# ── the swallow scenario: web delete vs device re-add, device clock behind ───

def _web_delete(client, db, book_id, anchor):
    """Delete via the web endpoint (server-minted tombstone). The client
    fixture already carries the admin JWT in its default headers."""
    row = (db.query(Annotation)
           .filter(Annotation.book_id == book_id, Annotation.anchor == anchor).first())
    assert row is not None
    r = client.delete(f"/api/annotations/{row.id}")
    assert r.status_code == 204, r.text


def test_readd_after_web_delete_wins_with_device_time(client, db, admin_user, make_book):
    """Device 3h behind server. Web delete mints a tombstone in the device's
    future; the user re-highlights the same passage a moment later (device
    frame). With device_time the server shifts its stamp into the device frame
    and the re-add wins instead of being silently swallowed for 3 hours."""
    user, _ = admin_user
    book = make_book()
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    dev_behind = 3  # hours

    # Device creates the highlight, stamped in its own (slow) frame.
    created = _dev_now(dev_behind)
    _sync(client, hdr, book.id, upserts=[_hl(A1, "keep me", dt=created, dtu=created)],
          device_time=_dev_now(dev_behind))

    # Web delete: tombstone stamped with the server clock (device future).
    _web_delete(client, db, book.id, A1)
    tomb = db.query(AnnotationTombstone).filter_by(book_id=book.id, anchor=A1).first()
    assert tomb is not None and tomb.server_minted is True
    assert tomb.client_deleted_at > _dev_now(dev_behind)  # in the device's future

    # User re-highlights one device-minute later. Without the guard this is
    # mtime <= tombstone and gets skipped.
    readd = (datetime.now() - timedelta(hours=dev_behind) + timedelta(minutes=1)).strftime(_KO_DT_FMT)
    r = _sync(client, hdr, book.id, upserts=[_hl(A1, "keep me", dt=readd, dtu=readd)],
              device_time=_dev_now(dev_behind))
    assert r.status_code == 200, r.text
    assert r.json()["applied"]["created"] == 1, r.json()["applied"]
    assert db.query(AnnotationTombstone).filter_by(book_id=book.id, anchor=A1).count() == 0


def test_readd_after_web_delete_swallowed_without_device_time(client, db, admin_user, make_book):
    """Documents the legacy behavior an old plugin (no device_time) still gets:
    the server-frame tombstone outranks the slow device's re-add."""
    user, _ = admin_user
    book = make_book()
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    dev_behind = 3

    created = _dev_now(dev_behind)
    _sync(client, hdr, book.id, upserts=[_hl(A1, "gone", dt=created, dtu=created)])
    _web_delete(client, db, book.id, A1)

    readd = (datetime.now() - timedelta(hours=dev_behind) + timedelta(minutes=1)).strftime(_KO_DT_FMT)
    r = _sync(client, hdr, book.id, upserts=[_hl(A1, "gone", dt=readd, dtu=readd)])
    assert r.json()["applied"]["skipped"] == 1


def test_device_edit_beats_web_edit_when_actually_later(client, db, admin_user, make_book):
    """Web edit bumps the mtime with the server clock; a device 3h behind edits
    afterwards (later in real time). With device_time the device edit wins."""
    user, _ = admin_user
    book = make_book()
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    dev_behind = 3

    created = _dev_now(dev_behind)
    _sync(client, hdr, book.id, upserts=[_hl(A1, "text", note="device v1", dt=created, dtu=created)],
          device_time=_dev_now(dev_behind))

    row = db.query(Annotation).filter_by(book_id=book.id, anchor=A1).first()
    r = client.put(f"/api/annotations/{row.id}", json={"note": "web edit"})
    assert r.status_code == 200
    db.refresh(row)
    assert row.server_minted is True

    # Device edits a device-minute later (genuinely after the web edit).
    edited = (datetime.now() - timedelta(hours=dev_behind) + timedelta(minutes=1)).strftime(_KO_DT_FMT)
    r = _sync(client, hdr, book.id,
              upserts=[_hl(A1, "text", note="device v2", dt=created, dtu=edited)],
              device_time=_dev_now(dev_behind))
    assert r.json()["applied"]["updated"] == 1, r.json()["applied"]
    db.refresh(row)
    assert row.note == "device v2"
    assert row.server_minted is False  # stamp is device-authored now


def test_response_shifts_server_minted_stamps_into_device_frame(client, db, admin_user, make_book):
    """A web-created highlight travels to a slow device with its stamps shifted
    into that device's frame — never in the device's future."""
    user, _ = admin_user
    book = make_book()
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    dev_behind = 3

    r = client.post("/api/annotations", json={
        "book_id": book.id, "highlighted_text": "from the web", "cfi": "epubcfi(/6/4!/4/2/1:0)",
    })
    assert r.status_code in (200, 201), r.text

    device_now = _dev_now(dev_behind)
    g = _sync(client, hdr, book.id, device_time=device_now).json()
    web = [a for a in g["annotations"] if a["anchor"].startswith("web:")]
    assert len(web) == 1
    assert web[0]["datetime"] <= device_now  # shifted, not in the device future

    # Same pull without device_time: raw server frame (device future).
    g2 = _sync(client, hdr, book.id).json()
    web2 = [a for a in g2["annotations"] if a["anchor"].startswith("web:")]
    assert web2[0]["datetime"] > device_now


def test_device_minted_stamps_are_never_shifted(client, db, admin_user, make_book):
    """Cross-device skew stays accepted: another device's stamps pass through
    verbatim even when the requesting device reports a big offset."""
    user, _ = admin_user
    book = make_book()
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}

    stamp = "2026-06-03 10:00:00"
    _sync(client, hdr, book.id, upserts=[_hl(A1, "device made", dt=stamp, dtu=stamp)])

    g = _sync(client, hdr, book.id, device_time=_dev_now(3)).json()
    a = [x for x in g["annotations"] if x["anchor"] == A1][0]
    assert a["datetime"] == stamp
    assert a["datetime_updated"] == stamp


def test_sync_response_carries_server_time(client, db, admin_user, make_book):
    user, _ = admin_user
    book = make_book()
    hdr = {"Authorization": f"Bearer {_api_key_for(db, user.id)}"}
    g = _sync(client, hdr, book.id).json()
    datetime.strptime(g["server_time"], _KO_DT_FMT)  # parseable, present
