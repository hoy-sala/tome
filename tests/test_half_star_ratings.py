"""Half-star ratings: validation, and legacy-int / new-float coexistence.

The rating columns keep their original INTEGER declaration; SQLite NUMERIC
affinity stores 4.5 as REAL. These tests pin the mixed-type behaviors the
migration relies on (avg/filter/sort/group across int and float rows).
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import func, text

from backend.core.ratings import validate_rating
from backend.models.user_book_status import UserBookStatus
from backend.models.user_series_rating import UserSeriesRating


# ── validator ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ok", [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 1.0, 5.0, None])
def test_validate_rating_accepts_half_steps(ok):
    validate_rating(ok)  # must not raise


@pytest.mark.parametrize("bad", [0, 0.5, 5.5, 4.3, 4.25, -1, 100,
                                 float("inf"), float("-inf"), float("nan")])
def test_validate_rating_rejects(bad):
    # inf/nan must 400 like any bad value, not OverflowError into a 500
    # (Pydantic floats accept Infinity/NaN by default).
    with pytest.raises(HTTPException):
        validate_rating(bad)


# ── endpoint validation ───────────────────────────────────────────────────────

def test_put_rating_half_star_roundtrip(client, make_book):
    book = make_book(title="Halves")
    r = client.put(f"/api/books/{book.id}/rating", json={"rating": 4.5})
    assert r.status_code == 200
    assert r.json()["rating"] == 4.5
    # whole star still works and comes back whole-valued
    r = client.put(f"/api/books/{book.id}/rating", json={"rating": 3})
    assert r.status_code == 200
    assert r.json()["rating"] == 3


@pytest.mark.parametrize("bad", [4.3, 0.5, 5.5, 0])
def test_put_rating_rejects_off_step(client, make_book, bad):
    book = make_book(title=f"Bad {bad}")
    r = client.put(f"/api/books/{book.id}/rating", json={"rating": bad})
    assert r.status_code == 400


def test_series_rating_half_star(client, make_book):
    make_book(title="Vol 1", series="Halved", series_index=1)
    r = client.put("/api/series/Halved/rating", json={"rating": 3.5})
    assert r.status_code == 200
    assert r.json()["rating"] == 3.5
    assert r.json()["display"] == 3.5
    r = client.put("/api/series/Halved/rating", json={"rating": 4.3})
    assert r.status_code == 400


# ── mixed int/float coexistence (the migration's core claim) ─────────────────

def test_legacy_integer_column_stores_halves_losslessly(db):
    """The PROD shape: the physical column was created as INTEGER (old model).
    SQLite NUMERIC affinity must store 4.5 as REAL, not truncate it, and
    aggregate/compare mixed rows correctly."""
    db.execute(text("CREATE TABLE _legacy_rating_probe (id INTEGER PRIMARY KEY, rating INTEGER)"))
    db.execute(text("INSERT INTO _legacy_rating_probe (rating) VALUES (4)"))
    db.execute(text("INSERT INTO _legacy_rating_probe (rating) VALUES (4.5)"))
    types = {r[0] for r in db.execute(text("SELECT typeof(rating) FROM _legacy_rating_probe"))}
    assert types == {"integer", "real"}
    vals = [r[0] for r in db.execute(
        text("SELECT rating FROM _legacy_rating_probe ORDER BY rating DESC"))]
    assert vals == [4.5, 4]
    avg = db.execute(text("SELECT avg(rating) FROM _legacy_rating_probe")).scalar()
    assert avg == pytest.approx(4.25)
    above4 = db.execute(
        text("SELECT count(*) FROM _legacy_rating_probe WHERE rating > 4")).scalar()
    assert above4 == 1
    db.execute(text("DROP TABLE _legacy_rating_probe"))


def test_mixed_int_and_float_rows_coexist(db, admin_user, make_book):
    """The fresh-DB shape (column declared FLOAT by create_all): whole-star and
    half-star rows aggregate/filter/sort uniformly through the ORM."""
    user, _ = admin_user
    b1 = make_book(title="Legacy Int")
    b2 = make_book(title="New Half")
    db.add(UserBookStatus(user_id=user.id, book_id=b1.id, status="read", rating=4))
    db.add(UserBookStatus(user_id=user.id, book_id=b2.id, status="read", rating=4.5))
    db.flush()

    # avg, comparison filters, and sorting all treat them uniformly.
    avg = db.query(func.avg(UserBookStatus.rating)).filter(
        UserBookStatus.user_id == user.id).scalar()
    assert avg == pytest.approx(4.25)

    at_least_4 = db.query(UserBookStatus).filter(
        UserBookStatus.user_id == user.id, UserBookStatus.rating >= 4).count()
    assert at_least_4 == 2
    above_4 = db.query(UserBookStatus).filter(
        UserBookStatus.user_id == user.id, UserBookStatus.rating > 4).count()
    assert above_4 == 1

    ordered = [r.rating for r in db.query(UserBookStatus).filter(
        UserBookStatus.user_id == user.id).order_by(UserBookStatus.rating.desc())]
    assert ordered == [4.5, 4]

    # Python-side grouping: int and float keys collapse (4 == 4.0, same hash).
    assert len({4, 4.0}) == 1


def test_series_volume_average_with_mixed_ratings(client, db, admin_user, make_book):
    user, _ = admin_user
    v1 = make_book(title="Mix Vol 1", series="MixSeries", series_index=1)
    v2 = make_book(title="Mix Vol 2", series="MixSeries", series_index=2)
    db.add(UserBookStatus(user_id=user.id, book_id=v1.id, status="read", rating=3))
    db.add(UserBookStatus(user_id=user.id, book_id=v2.id, status="read", rating=4.5))
    db.flush()

    r = client.get("/api/series/MixSeries/rating")
    assert r.status_code == 200
    body = r.json()
    assert body["volume_average"] == pytest.approx(3.75)
    assert body["rated_volumes"] == 2


def test_series_rating_model_accepts_float(db, admin_user):
    user, _ = admin_user
    db.add(UserSeriesRating(user_id=user.id, series_name="S", rating=2.5))
    db.flush()
    row = db.query(UserSeriesRating).filter_by(user_id=user.id, series_name="S").one()
    assert row.rating == 2.5
