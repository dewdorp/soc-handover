"""오프라인 설치 패키지 마무리 도구 — package.ps1 이 부른다.

  python pack_helper.py normalize <bundle>      .ps1 → UTF-8 BOM, .cmd → CRLF + ASCII 검사, .txt → UTF-8 BOM
  python pack_helper.py manifest <bundle>       MANIFEST.sha256 (설치 프로그램이 복사 손상 여부를 검사)
  python pack_helper.py zip <bundle> <out.zip>  zip + <out.zip>.sha256

Windows PowerShell 5.1 은 BOM 없는 UTF-8 스크립트를 시스템 코드페이지(한국어 cp949)로 읽어 한글이 깨지고,
cmd.exe 는 배치 파일을 OEM 코드페이지로 읽는다 — 그래서 .ps1 에는 BOM 을 붙이고 .cmd 는 ASCII 만 허용한다.
zip 항목 이름은 '/' 구분 · ASCII 만(한글 파일 이름은 탐색기 압축 풀기에서 깨질 수 있다).
"""
from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

BOM = bytes([0xEF, 0xBB, 0xBF])
CRLF = bytes([13, 10])
LF = bytes([10])
MANIFEST = "MANIFEST.sha256"


def normalize(bundle: Path) -> None:
    fixed = 0
    for p in bundle.rglob("*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        # 메모장이 인코딩을 헷갈리지 않게 안내문(README-KO.txt)에도 BOM
        if suffix == ".ps1" or p.name in ("README-KO.txt", "README-PATCH.txt"):
            data = p.read_bytes()
            if not data.startswith(BOM):
                data.decode("utf-8")  # UTF-8 이 아니면 여기서 실패
                p.write_bytes(BOM + data)
                fixed += 1
        elif suffix == ".cmd":
            data = p.read_bytes()
            if any(b > 127 for b in data):
                raise SystemExit(f"{p}: .cmd 파일에 ASCII 가 아닌 글자가 있습니다(cmd.exe 가 깨뜨림)")
            normalized = data.replace(CRLF, LF).replace(LF, CRLF)
            if normalized != data:
                p.write_bytes(normalized)
                fixed += 1
    print(f"normalize: {fixed} files")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(bundle: Path) -> None:
    lines = []
    for p in sorted(bundle.rglob("*")):
        if not p.is_file() or p.name == MANIFEST:
            continue
        rel = str(p.relative_to(bundle)).replace("/", os.sep)
        if not rel.isascii():
            raise SystemExit(f"파일 이름에 ASCII 가 아닌 글자가 있습니다: {rel}")
        lines.append(f"{_sha256(p)}  {rel}")
    (bundle / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"manifest: {len(lines)} files")


def make_zip(bundle: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    top = bundle.name
    n = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():
                z.write(p, f"{top}/{p.relative_to(bundle).as_posix()}")
                n += 1
    digest = _sha256(out)
    Path(str(out) + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="ascii")
    print(f"zip: {n} files, {out.stat().st_size / 1e6:.1f} MB, sha256 {digest}")


def main() -> None:
    cmd, bundle = sys.argv[1], Path(sys.argv[2]).resolve()
    if cmd == "normalize":
        normalize(bundle)
    elif cmd == "manifest":
        manifest(bundle)
    elif cmd == "zip":
        make_zip(bundle, Path(sys.argv[3]).resolve())
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
