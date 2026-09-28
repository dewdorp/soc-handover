"""비밀번호 암호화 (app/core/crypto.py).

여기서 보는 것은 네 가지다 — 되읽기, 같은 값도 매번 다른 암호문, 한 글자만 바뀌어도 거절,
다른 항목의 암호문을 옮겨 붙여도 안 열림.
"""
from __future__ import annotations

import pytest

from app.core import crypto
from app.core.config import settings


def test_roundtrip_keeps_korean_and_symbols():
    secret = "방화벽#1 관리자 P@ssw0rd!  끝"
    blob = crypto.encrypt(secret, aad="credential:1")
    assert secret.encode() not in blob, "평문이 암호문 안에 그대로 있으면 안 된다"
    assert crypto.decrypt(blob, aad="credential:1") == secret


def test_same_secret_gives_different_ciphertext():
    a = crypto.encrypt("같은값", aad="credential:1")
    b = crypto.encrypt("같은값", aad="credential:1")
    assert a != b, "nonce 가 매번 달라야 같은 비밀번호인지 들키지 않는다"
    assert crypto.decrypt(a, aad="credential:1") == crypto.decrypt(b, aad="credential:1")


def test_tampered_ciphertext_is_refused():
    blob = bytearray(crypto.encrypt("원래값", aad="credential:1"))
    blob[-1] ^= 0x01
    with pytest.raises(crypto.VaultKeyMismatch):
        crypto.decrypt(bytes(blob), aad="credential:1")


def test_ciphertext_of_another_row_does_not_open():
    """1번 항목의 암호문을 2번 항목에 옮겨 넣어도 열리지 않는다(AAD)."""
    blob = crypto.encrypt("1번 비밀번호", aad="credential:1")
    with pytest.raises(crypto.VaultKeyMismatch):
        crypto.decrypt(blob, aad="credential:2")


def test_truncated_blob_is_refused():
    with pytest.raises(crypto.VaultKeyMismatch):
        crypto.decrypt(b"\x01short", aad="credential:1")


def test_wrong_key_is_refused(monkeypatch):
    blob = crypto.encrypt("원래값", aad="credential:1")
    monkeypatch.setattr(settings, "VAULT_KEY", crypto.generate_key())
    with pytest.raises(crypto.VaultKeyMismatch):
        crypto.decrypt(blob, aad="credential:1")


def test_key_rotation_reads_old_and_writes_new(monkeypatch):
    old_blob = crypto.encrypt("옛 키로 넣은 값", aad="credential:7")
    monkeypatch.setattr(settings, "VAULT_KEY_NEXT", crypto.generate_key())

    new_blob = crypto.encrypt("새 키로 넣은 값", aad="credential:7", version=crypto.NEXT_VERSION)
    assert crypto.key_version_of(new_blob) == crypto.NEXT_VERSION
    # 키 버전이 암호문에 들어 있어 옛 값과 새 값을 섞어 두어도 각각 열린다
    assert crypto.decrypt(old_blob, aad="credential:7") == "옛 키로 넣은 값"
    assert crypto.decrypt(new_blob, aad="credential:7") == "새 키로 넣은 값"


def test_prod_without_key_disables_the_feature(monkeypatch):
    """운영에서는 키를 만들어 쓰지 않는다 — SECRET_KEY 를 바꾸면 전부 잠기기 때문."""
    monkeypatch.setattr(settings, "VAULT_KEY", "")
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    assert crypto.is_available() is False
    with pytest.raises(crypto.VaultUnavailable):
        crypto.encrypt("x", aad="credential:1")


def test_bad_key_length_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_KEY", "dG9vLXNob3J0")   # 9바이트
    with pytest.raises(crypto.VaultUnavailable):
        crypto.encrypt("x", aad="credential:1")
