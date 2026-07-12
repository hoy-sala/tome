"""Models for reading sessions, positions, and annotations."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base


class ReadingSession(Base):
    __tablename__ = "reading_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    progress_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    progress_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pages_turned: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    device: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_uuid: Mapped[Optional[str]] = mapped_column(String(36), unique=True, nullable=True)

    user: Mapped["User"] = relationship("User")

    book: Mapped[Optional["Book"]] = relationship("Book")


class TomeSyncPosition(Base):
    __tablename__ = "tome_sync_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_tspos_user_book"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    progress: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    device: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User")
    book: Mapped["Book"] = relationship("Book")


class Annotation(Base):
    __tablename__ = "annotations"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", "anchor", name="uq_annotation_user_book_anchor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    anchor: Mapped[str] = mapped_column(String(512), nullable=False)
    anchor_end: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    chapter: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    highlighted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    cfi: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    koreader_datetime: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    koreader_datetime_updated: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    server_minted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User")
    book: Mapped["Book"] = relationship("Book")

    @property
    def effective_mtime(self) -> str:
        return self.koreader_datetime_updated or self.koreader_datetime or ""


class AnnotationTombstone(Base):
    __tablename__ = "annotation_tombstones"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", "anchor", name="uq_tombstone_user_book_anchor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    anchor: Mapped[str] = mapped_column(String(512), nullable=False)
    client_deleted_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    server_minted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
