"""Regression tests for the language facet + filter (dashboard "Language" dropdown).

`Book.language` is populated straight from per-file embedded metadata, so the
stored values are messy: en / eng / en-US / English all mean English. The facet
folds them to one canonical code with a human label, and the list filter matches
all raw variants that fold to the requested code.
"""
from backend.services.languages import normalize_language, language_label


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_normalize_folds_variants():
    for raw in ("en", "eng", "en-US", "English", "EN", "en_GB"):
        assert normalize_language(raw) == "en"
    assert normalize_language("de_DE") == "de"
    assert normalize_language("German") == "de"
    assert normalize_language("zh-Hant") == "zh"
    assert normalize_language("") is None
    assert normalize_language("   ") is None
    assert normalize_language(None) is None
    # Unknown codes pass through as their lowercased base token, still grouped.
    assert normalize_language("xx") == "xx"


def test_label_falls_back_to_upper_code():
    assert language_label("en") == "English"
    assert language_label("xx") == "XX"


def test_facet_dedupes_messy_values(client, admin_user, make_book):
    _, token = admin_user
    make_book(title="A", language="en")
    make_book(title="B", language="eng")
    make_book(title="C", language="English")
    make_book(title="D", language="de")
    make_book(title="E", language=None)

    r = client.get("/api/books/facets", headers=_hdr(token))
    assert r.status_code == 200
    langs = r.json()["languages"]
    # en collapses three variants into one; de is its own; None is excluded.
    assert {l["code"] for l in langs} == {"en", "de"}
    by_code = {l["code"]: l["label"] for l in langs}
    assert by_code["en"] == "English"
    assert by_code["de"] == "German"


def test_filter_matches_all_raw_variants(client, admin_user, make_book):
    _, token = admin_user
    make_book(title="A", language="en")
    make_book(title="B", language="eng")
    make_book(title="C", language="English")
    make_book(title="D", language="de")

    r = client.get("/api/books?language=en", headers=_hdr(token))
    assert r.status_code == 200
    assert {b["title"] for b in r.json()} == {"A", "B", "C"}

    r = client.get("/api/books?language=de", headers=_hdr(token))
    assert {b["title"] for b in r.json()} == {"D"}


def test_filter_unknown_language_returns_empty(client, admin_user, make_book):
    _, token = admin_user
    make_book(title="A", language="en")
    r = client.get("/api/books?language=ja", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json() == []
