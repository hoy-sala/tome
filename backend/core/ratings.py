"""Half-star rating validation, shared by every rating write path.

Ratings are 1.0–5.0 in 0.5 steps (floats; 0.5 values are exactly representable
in binary so equality checks are safe). Legacy whole-star Integer rows coexist:
SQLite NUMERIC affinity stores halves as REAL, and Python treats 4 == 4.0 /
hash(4) == hash(4.0), so mixed values compare, sort, group, and average
correctly everywhere.
"""
import math

from fastapi import HTTPException

RATING_ERROR = "rating must be between 1 and 5 in half-star steps, or null to clear"


def validate_rating(rating: float | None) -> None:
    """Raise 400 unless rating is None or a valid half-star value."""
    if rating is None:
        return
    # Pydantic floats accept Infinity/NaN by default; int(inf) would raise
    # OverflowError (a 500) before the range check ran.
    if not math.isfinite(rating):
        raise HTTPException(400, RATING_ERROR)
    doubled = rating * 2
    if doubled != int(doubled) or not (1 <= rating <= 5):
        raise HTTPException(400, RATING_ERROR)
