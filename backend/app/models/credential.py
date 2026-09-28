"""장비 비밀번호 보관 (§FR-V).

관계사 · 장비명 · 접속 방법 · 계정은 그대로 두고, **비밀번호만** 암호문으로 저장한다
(app/core/crypto.py). 목록 · 검색은 평문 항목으로만 하므로 비밀번호는 어디서도 새지 않는다.

범위(scope)
  · SHARED   — 교대 근무자 전원이 본다. 장비 비밀번호는 교대하며 같이 쓰는 정보다.
  · PERSONAL — 등록한 사람만 본다(목록에도 남에게 보이지 않는다).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, ForeignKey, Index, Integer, LargeBinary, SmallInteger,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StrListType, TimestampMixin, TZDateTime

SCOPE_SHARED = "SHARED"
SCOPE_PERSONAL = "PERSONAL"
SCOPES = (SCOPE_SHARED, SCOPE_PERSONAL)

#: 비밀번호를 바꾼 이력은 최근 몇 개까지 값을 들고 있을지(그보다 오래된 것은 값을 지운다)
KEEP_VERSIONS = 5


class Credential(Base, TimestampMixin):
    __tablename__ = "credentials"
    __table_args__ = (
        Index("ix_cred_scope_owner", "scope", "owner_id", "is_deleted"),
        Index("ix_cred_device", "device_name"),
        Index("ix_cred_company", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default=SCOPE_SHARED)
    #: 등록한 사람. PERSONAL 이면 이 사람만 본다. 고치기 · 지우기는 이 사람과 관리자.
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    device_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 접속 방법 — SSH 10.0.0.1:22 · 웹 https://… · 콘솔 직접 등, 사람이 읽는 문장 그대로
    access_method: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(200))
    #: AES-256-GCM 암호문(키버전 + nonce + 본문). 평문은 DB 어디에도 없다.
    secret_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    #: 비밀번호를 마지막으로 바꾼 때 · 사람(항목 자체의 수정과 구분한다)
    rotated_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    rotated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    current_version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    versions = relationship("CredentialVersion", cascade="all, delete-orphan",
                            order_by="CredentialVersion.version_no.desc()", lazy="selectin")


class CredentialVersion(Base, TimestampMixin):
    """바꾸기 **전**의 내용. 최근 KEEP_VERSIONS 개만 옛 비밀번호를 들고 있는다.

    장비에 새 비밀번호가 안 먹혔을 때 직전 값으로 돌아갈 수 있어야 해서 값까지 남긴다.
    옛 값을 보는 것도 지금 값과 똑같이 감사에 남는다.
    """

    __tablename__ = "credential_versions"
    __table_args__ = (Index("ix_credver_cred", "credential_id", "version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[int] = mapped_column(ForeignKey("credentials.id", ondelete="CASCADE"),
                                               nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 그때의 비밀번호(암호문). 오래되어 정리된 이력은 NULL 이고 '값 없음'으로 보여 준다.
    secret_cipher: Mapped[bytes | None] = mapped_column(LargeBinary)
    #: 무엇이 바뀌었나 — secret · device_name · access_method · username · company · note · scope
    changed_fields: Mapped[list[str] | None] = mapped_column(StrListType)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    change_note: Mapped[str | None] = mapped_column(Text)
    #: 그 시점의 나머지 항목(장비명 등) — 이력에서 무엇이 어떻게 바뀌었는지 보여 주기 위해
    device_name: Mapped[str | None] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(200))
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
