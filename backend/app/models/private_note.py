"""개인 메모. 공유 문서 및 검색 색인과 독립적으로 보관한다."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PrivateNote(Base, TimestampMixin):
    __tablename__ = "private_notes"
    __table_args__ = (
        Index("ix_private_notes_owner_updated", "owner_id", "updated_at", "id"),
        CheckConstraint("length(trim(title)) > 0 AND length(title) <= 200", name="ck_private_notes_title"),
        CheckConstraint("length(body) <= 50000", name="ck_private_notes_body"),
        CheckConstraint("version_no > 0", name="ck_private_notes_version"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    version_no: Mapped[int] = mapped_column(server_default="1")
