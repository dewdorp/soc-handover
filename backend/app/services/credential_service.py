"""장비 비밀번호 보관 (FR-V) — 등록 · 수정 · 열람 · 변경 이력.

원칙
  · 비밀번호는 **암호문으로만** 오간다. 목록 · 검색 · 이력 어디에도 평문이 없고,
    `POST /credentials/{id}/reveal` 한 곳에서만 풀어서 내보낸다.
  · 열어 볼 때마다 **본인 비밀번호를 다시 확인**하고, 한 건씩 감사에 남긴다
    (누가 · 언제 · 어느 장비 · 지금 값인지 옛 값인지).
  · 범위: SHARED 는 교대 근무자 전원, PERSONAL 은 등록한 사람만. 목록 질의부터 갈라 놓아
    남의 PERSONAL 은 개수에도 잡히지 않는다.
  · 고치기 · 지우기는 등록한 사람과 관리자(MANAGER+) — 인수인계 · 할일과 같은 규칙.
  · 비밀번호를 바꾸면 바꾸기 **전** 값을 이력에 남긴다(장비에 안 먹혔을 때 되돌리려고).
    최근 KEEP_VERSIONS 개만 값을 들고 있고, 그보다 오래된 이력은 값을 지운다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from app.audit import actions
from app.audit.recorder import record
from app.core import crypto
from app.core.context import RequestContext
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.security import verify_password
from app.core.time import now
from app.models.credential import (KEEP_VERSIONS, SCOPE_PERSONAL, SCOPE_SHARED, SCOPES,
                                   Credential, CredentialVersion)
from app.models.reference import Company
from app.models.user import User

#: 이력에 '무엇이 바뀌었나'로 남기는 이름
FIELDS = ("scope", "company_id", "device_name", "access_method", "username", "note")
MANAGER_ROLES = ("MANAGER", "ADMIN")


def _aad(credential_id: int) -> str:
    """이 암호문이 어느 항목의 것인지 묶어 둔다 — 다른 항목의 암호문을 옮겨 붙여도 열리지 않는다."""
    return f"credential:{credential_id}"


def _visible(actor: User) -> Any:
    """내가 볼 수 있는 것: 공용 전부 + 내 개인 것."""
    return or_(Credential.scope == SCOPE_SHARED, Credential.owner_id == actor.id)


def _can_modify(actor: User, row: Credential) -> bool:
    return row.owner_id == actor.id or actor.role_code in MANAGER_ROLES


def get_or_404(db: Session, actor: User, credential_id: int) -> Credential:
    row = db.get(Credential, credential_id)
    if row is None or row.is_deleted:
        raise NotFound("비밀번호 항목을 찾을 수 없습니다.")
    if row.scope == SCOPE_PERSONAL and row.owner_id != actor.id:
        # 남의 개인 항목은 '없는 것'으로 답한다 — 있다는 사실조차 알려 주지 않는다
        raise NotFound("비밀번호 항목을 찾을 수 없습니다.")
    return row


def _check_scope(scope: str | None) -> str:
    scope = (scope or SCOPE_SHARED).upper()
    if scope not in SCOPES:
        raise ValidationFailed("공개 범위는 SHARED · PERSONAL 중 하나여야 합니다.",
                               detail={"field": "scope"})
    return scope


def _check_company(db: Session, company_id: int | None) -> int | None:
    if company_id is None:
        return None
    if db.get(Company, company_id) is None:
        raise ValidationFailed("존재하지 않는 관계사입니다.", detail={"field": "company_id"})
    return company_id


def list_for(db: Session, actor: User, *, scope: str | None = None, company_id: int | None = None,
             q: str | None = None, limit: int = 200) -> list[Credential]:
    stmt: Select = select(Credential).where(Credential.is_deleted == false(), _visible(actor))
    if scope:
        stmt = stmt.where(Credential.scope == _check_scope(scope))
    if company_id is not None:
        stmt = stmt.where(Credential.company_id == company_id)
    if q:
        like = f"%{q.strip()}%"
        # 비밀번호는 검색 대상이 아니다(암호문이라 검색할 수도 없다)
        stmt = stmt.where(or_(Credential.device_name.ilike(like),
                              Credential.username.ilike(like),
                              Credential.access_method.ilike(like)))
    return list(db.scalars(stmt.order_by(Credential.device_name, Credential.id).limit(limit)))


def create(db: Session, actor: User, data: dict[str, Any],
           ctx: RequestContext | None = None) -> Credential:
    secret = (data.get("secret") or "").strip()
    if not secret:
        raise ValidationFailed("비밀번호를 입력하십시오.", detail={"field": "secret"})
    device = (data.get("device_name") or "").strip()
    if not device:
        raise ValidationFailed("장비명을 입력하십시오.", detail={"field": "device_name"})

    row = Credential(
        scope=_check_scope(data.get("scope")), owner_id=actor.id,
        company_id=_check_company(db, data.get("company_id")), device_name=device,
        access_method=data.get("access_method"), username=data.get("username"),
        note=data.get("note"), rotated_at=now(), rotated_by=actor.id, current_version_no=1,
        secret_cipher=b"",
    )
    db.add(row)
    db.flush()
    # 암호문에 id 를 묶으므로 id 가 정해진 뒤에 암호화한다
    row.secret_cipher = crypto.encrypt(secret, aad=_aad(row.id))
    db.flush()
    record(db, action=actions.CREDENTIAL_CREATE, ctx=ctx, user=actor,
           resource_type="CREDENTIAL", resource_id=row.id,
           after={"device_name": row.device_name, "scope": row.scope,
                  "company_id": row.company_id, "username": row.username})
    return row


def _trim_versions(db: Session, credential_id: int) -> None:
    """오래된 이력의 **값만** 지운다(누가 언제 바꿨는지는 남긴다)."""
    old = db.scalars(select(CredentialVersion)
                     .where(CredentialVersion.credential_id == credential_id,
                            CredentialVersion.secret_cipher.is_not(None))
                     .order_by(CredentialVersion.version_no.desc())
                     .offset(KEEP_VERSIONS)).all()
    for row in old:
        row.secret_cipher = None


def update(db: Session, actor: User, credential_id: int, changes: dict[str, Any],
           ctx: RequestContext | None = None) -> Credential:
    row = get_or_404(db, actor, credential_id)
    if not _can_modify(actor, row):
        raise Forbidden("등록한 사람과 관리자만 고칠 수 있습니다.")

    changed: list[str] = []
    before: dict[str, Any] = {}
    for field in FIELDS:
        if field not in changes:
            continue
        value = changes[field]
        if field == "scope":
            value = _check_scope(value)
        if field == "company_id":
            value = _check_company(db, value)
        if field == "device_name":
            value = (value or "").strip()
            if not value:
                raise ValidationFailed("장비명을 비울 수 없습니다.", detail={"field": "device_name"})
        if getattr(row, field) != value:
            before[field] = getattr(row, field)
            setattr(row, field, value)
            changed.append(field)

    secret = changes.get("secret")
    secret = secret.strip() if isinstance(secret, str) else None
    if secret:
        # 바꾸기 전 값을 이력에 남긴다 — 새 비밀번호가 장비에 안 먹었을 때 되돌린다
        db.add(CredentialVersion(
            credential_id=row.id, version_no=row.current_version_no,
            secret_cipher=row.secret_cipher, changed_fields=changed + ["secret"],
            changed_by=actor.id, change_note=changes.get("change_note"),
            device_name=row.device_name, username=row.username,
            key_version=crypto.key_version_of(row.secret_cipher)))
        row.secret_cipher = crypto.encrypt(secret, aad=_aad(row.id))
        row.current_version_no += 1
        row.rotated_at = now()
        row.rotated_by = actor.id
        changed.append("secret")
        db.flush()
        _trim_versions(db, row.id)
    elif changed:
        db.add(CredentialVersion(
            credential_id=row.id, version_no=row.current_version_no, secret_cipher=None,
            changed_fields=changed, changed_by=actor.id, change_note=changes.get("change_note"),
            device_name=before.get("device_name", row.device_name),
            username=before.get("username", row.username), key_version=0))

    if not changed:
        return row
    db.flush()
    record(db, action=actions.CREDENTIAL_UPDATE, ctx=ctx, user=actor,
           resource_type="CREDENTIAL", resource_id=row.id,
           detail={"changed_fields": changed},
           before=before or None,
           after={f: getattr(row, f) for f in changed if f != "secret"} or None)
    return row


def delete(db: Session, actor: User, credential_id: int,
           ctx: RequestContext | None = None) -> None:
    row = get_or_404(db, actor, credential_id)
    if not _can_modify(actor, row):
        raise Forbidden("등록한 사람과 관리자만 지울 수 있습니다.")
    row.is_deleted = True
    db.flush()
    record(db, action=actions.CREDENTIAL_DELETE, ctx=ctx, user=actor,
           resource_type="CREDENTIAL", resource_id=row.id,
           before={"device_name": row.device_name, "scope": row.scope,
                   "username": row.username})


def reveal(db: Session, actor: User, credential_id: int, password: str, *,
           version_no: int | None = None, ctx: RequestContext | None = None) -> dict[str, Any]:
    """비밀번호를 풀어서 돌려준다. **본인 확인 + 감사 기록**이 조건이다.

    version_no 를 주면 그때의 옛 비밀번호(이력)를 돌려준다.
    """
    row = get_or_404(db, actor, credential_id)
    if not verify_password(password or "", actor.password_hash):
        # 남의 자리에서 열어 보려 한 흔적도 남긴다.
        # 예외를 던지면 요청 트랜잭션이 롤백되므로 증적을 먼저 확정한다(auth_service.login 과 같은 규칙).
        record(db, action=actions.CREDENTIAL_REVEAL_DENIED, ctx=ctx, user=actor,
               resource_type="CREDENTIAL", resource_id=row.id, result="FAILURE",
               detail={"device_name": row.device_name, "reason": "password_mismatch"})
        db.commit()
        raise Forbidden("본인 비밀번호가 맞지 않습니다.")

    if version_no is None:
        blob, shown = row.secret_cipher, row.current_version_no
    else:
        version = db.scalar(select(CredentialVersion).where(
            CredentialVersion.credential_id == row.id,
            CredentialVersion.version_no == version_no))
        if version is None:
            raise NotFound("그 시점의 기록이 없습니다.")
        if version.secret_cipher is None:
            raise NotFound(f"오래된 이력이라 값은 남아 있지 않습니다(최근 {KEEP_VERSIONS}개만 보관).")
        blob, shown = version.secret_cipher, version_no

    secret = crypto.decrypt(blob, aad=_aad(row.id))
    record(db, action=actions.CREDENTIAL_REVEAL, ctx=ctx, user=actor,
           resource_type="CREDENTIAL", resource_id=row.id,
           detail={"device_name": row.device_name, "username": row.username,
                   "version_no": shown, "is_current": version_no is None})
    return {"credential_id": row.id, "version_no": shown, "secret": secret,
            "device_name": row.device_name, "username": row.username}


def history(db: Session, actor: User, credential_id: int) -> list[dict[str, Any]]:
    row = get_or_404(db, actor, credential_id)
    out = []
    for version in db.scalars(select(CredentialVersion)
                              .where(CredentialVersion.credential_id == row.id)
                              .order_by(CredentialVersion.version_no.desc())):
        user = db.get(User, version.changed_by) if version.changed_by else None
        out.append({
            "version_no": version.version_no,
            "changed_fields": version.changed_fields or [],
            "changed_by": user.display_name if user else None,
            "changed_at": version.created_at,
            "change_note": version.change_note,
            "device_name": version.device_name,
            "username": version.username,
            "has_secret": version.secret_cipher is not None,
        })
    return out


def to_out(db: Session, actor: User, row: Credential) -> dict[str, Any]:
    owner = db.get(User, row.owner_id)
    rotated_by = db.get(User, row.rotated_by) if row.rotated_by else None
    company = db.get(Company, row.company_id) if row.company_id else None
    return {
        "id": row.id, "scope": row.scope, "company_id": row.company_id,
        "company": company.name if company else None,
        "device_name": row.device_name, "access_method": row.access_method,
        "username": row.username, "note": row.note,
        "owner_id": row.owner_id, "owner": owner.display_name if owner else None,
        "rotated_at": row.rotated_at, "rotated_by": rotated_by.display_name if rotated_by else None,
        "current_version_no": row.current_version_no,
        "can_edit": _can_modify(actor, row),
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def rekey(db: Session) -> dict[str, int]:
    """모든 암호문을 지금 키(VAULT_KEY_NEXT)로 다시 암호화한다 — manage.py vault-rekey."""
    done = skipped = 0
    for row in db.scalars(select(Credential)):
        secret = crypto.decrypt(row.secret_cipher, aad=_aad(row.id))
        row.secret_cipher = crypto.encrypt(secret, aad=_aad(row.id), version=crypto.NEXT_VERSION)
        done += 1
    for version in db.scalars(select(CredentialVersion).where(
            CredentialVersion.secret_cipher.is_not(None))):
        secret = crypto.decrypt(version.secret_cipher, aad=_aad(version.credential_id))
        version.secret_cipher = crypto.encrypt(secret, aad=_aad(version.credential_id),
                                               version=crypto.NEXT_VERSION)
        version.key_version = crypto.NEXT_VERSION
        done += 1
    db.flush()
    return {"reencrypted": done, "skipped": skipped}
