"""비밀번호 보관용 암호화 (FR-V, ASSUMPTIONS B-16).

관계사 장비 비밀번호는 DB 에 **암호문으로만** 들어간다. 규칙은 네 가지다.

  · AES-256-GCM. 항목마다 무작위 nonce(12바이트)를 새로 만든다 — 같은 비밀번호라도 암호문이 다르다.
  · 인증 태그(GCM)가 붙으므로 DB 안에서 한 글자만 바꿔도 복호화가 **실패**한다(조용히 깨진 값이 나오지 않는다).
  · AAD 로 '이 암호문이 어느 항목의 것인지'를 묶는다. 다른 항목의 암호문을 복사해 넣어도 열리지 않는다.
  · 키는 DB 가 아니라 `.env`(VAULT_KEY)에 둔다. DB 백업만 유출되어도 비밀번호는 나오지 않는다.
    반대로 **`.env` 를 잃으면 되살릴 수 없다** — 운영 문서에 그렇게 적었다(docs/OPERATIONS.md).

키 교체: 암호문 앞에 키 버전을 1바이트로 붙여 둔다. 새 키를 `VAULT_KEY_NEXT` 로 넣고
`manage.py vault-rekey` 를 돌리면 모든 항목을 새 키로 다시 암호화한다(옛 키로 읽고 새 키로 쓴다).

개발 · 테스트(APP_ENV != prod)에서 VAULT_KEY 가 비어 있으면 SECRET_KEY 에서 만들어 쓴다 —
서버를 다시 켜도 같은 키가 나와야 넣어 둔 값을 계속 읽을 수 있다. 운영에서는 만들어 쓰지 않는다:
SECRET_KEY 는 유출 시 바꾸라고 안내하는 값인데, 거기서 파생하면 바꾸는 순간 비밀번호가 전부 잠긴다.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.errors import AppError

NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32
#: 지금 새로 암호화할 때 쓰는 키 버전(암호문 첫 바이트로 들어간다)
CURRENT_VERSION: Final = 1
NEXT_VERSION: Final = 2


class VaultUnavailable(AppError):
    """키가 없어 비밀번호 기능을 쓸 수 없다."""

    code = "vault_unavailable"
    status_code = 503
    message = ("비밀번호 보관 기능이 아직 준비되지 않았습니다(.env 의 VAULT_KEY 없음). "
               "설치 폴더에서 manage.py vault-key 로 키를 만든 뒤 앱을 다시 시작하십시오.")


class VaultKeyMismatch(AppError):
    """암호문은 있는데 열리지 않는다 — 키가 바뀌었거나 값이 깨졌다."""

    code = "vault_key_mismatch"
    status_code = 500
    message = ("저장된 비밀번호를 열지 못했습니다. .env 의 VAULT_KEY 가 이 데이터를 만든 키와 다릅니다. "
               "예전 .env 를 복구하십시오(키 없이는 되살릴 수 없습니다).")


def generate_key() -> str:
    """`.env` 에 넣을 새 키(base64 32바이트)."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()


def _decode_key(raw: str) -> bytes:
    raw = (raw or "").strip()
    if not raw:
        return b""
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError) as exc:
        raise VaultUnavailable("VAULT_KEY 형식이 올바르지 않습니다(base64 32바이트).") from exc
    if len(key) != KEY_BYTES:
        raise VaultUnavailable(f"VAULT_KEY 는 32바이트여야 합니다(지금 {len(key)}바이트).")
    return key


def _key_for(version: int) -> bytes:
    if version == NEXT_VERSION:
        key = _decode_key(settings.VAULT_KEY_NEXT)
        if not key:
            raise VaultKeyMismatch("새 키(VAULT_KEY_NEXT)로 암호화된 값인데 그 키가 없습니다.")
        return key
    key = _decode_key(settings.VAULT_KEY)
    if key:
        return key
    if settings.APP_ENV == "prod":
        raise VaultUnavailable()
    # 개발 · 테스트: SECRET_KEY 에서 만들어 쓴다(다시 켜도 같은 키)
    return hashlib.sha256(f"soc-handover-vault:{settings.SECRET_KEY}".encode()).digest()


def is_available() -> bool:
    try:
        _key_for(CURRENT_VERSION)
    except AppError:
        return False
    return True


def encrypt(plaintext: str, *, aad: str, version: int = CURRENT_VERSION) -> bytes:
    """(키버전 1바이트) + (nonce 12바이트) + (암호문+태그)."""
    nonce = os.urandom(NONCE_BYTES)
    blob = AESGCM(_key_for(version)).encrypt(nonce, plaintext.encode(), aad.encode())
    return bytes([version]) + nonce + blob


def decrypt(blob: bytes, *, aad: str) -> str:
    if not blob or len(blob) <= 1 + NONCE_BYTES:
        raise VaultKeyMismatch("저장된 비밀번호가 비어 있거나 잘렸습니다.")
    version, nonce, body = blob[0], blob[1:1 + NONCE_BYTES], blob[1 + NONCE_BYTES:]
    try:
        return AESGCM(_key_for(version)).decrypt(nonce, body, aad.encode()).decode()
    except InvalidTag as exc:
        # 키가 다르거나, DB 안에서 값이 바뀌었거나, 다른 항목의 암호문을 옮겨 붙였다
        raise VaultKeyMismatch() from exc


def key_version_of(blob: bytes) -> int:
    return blob[0] if blob else 0
