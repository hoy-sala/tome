from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

VALID_STATUSES = {"ongoing", "finished", "hiatus", "unknown"}


class SeriesMetaOut(BaseModel):
    series_name: str
    status: str
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SeriesMetaUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v
