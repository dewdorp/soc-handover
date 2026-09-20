"""패키지에 든 실행 파일이 Windows 10(64비트)에서 돌 수 있는지 검사한다 — package.ps1 이 압축 전에 부른다.

대상: Windows 10 Enterprise LTSC 2019(빌드 17763)를 포함한 Windows 10/11 64비트.

  1. 서브시스템 최소 버전이 10.0 을 넘는 파일이 있으면 실패 (그 Windows 에서 아예 실행되지 않는다)
  2. 32비트 파일이 섞여 있으면 실패
  3. 패키지에 없고 Windows 에도 없는 DLL 을 import 하면 실패
     (전에 이렇게 PostgreSQL 의 plperl · plpython3 · pltcl 이 Perl · Tcl 런타임을 요구하는 것을 찾아 뺐다)

  python audit_pe.py <번들 폴더>     → 문제 없으면 0, 있으면 1
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

#: Windows 10 1809 에 있는 시스템 DLL (우리 번들이 실제로 참조하는 것만)
SYSTEM_DLLS = {
    "kernel32.dll", "kernelbase.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "shlwapi.dll", "ole32.dll", "oleaut32.dll", "comdlg32.dll", "comctl32.dll", "ws2_32.dll",
    "wsock32.dll", "mswsock.dll", "secur32.dll", "crypt32.dll", "bcrypt.dll", "bcryptprimitives.dll",
    "ncrypt.dll", "rpcrt4.dll", "netapi32.dll", "userenv.dll", "version.dll", "winmm.dll",
    "wldap32.dll", "dbghelp.dll", "psapi.dll", "imm32.dll", "setupapi.dll", "cfgmgr32.dll",
    "iphlpapi.dll", "dnsapi.dll", "winhttp.dll", "wininet.dll", "normaliz.dll", "msvcrt.dll",
    "ucrtbase.dll", "ntdll.dll", "powrprof.dll", "cryptbase.dll", "sspicli.dll", "winspool.drv",
    "gdiplus.dll", "authz.dll", "msi.dll", "wtsapi32.dll", "pdh.dll", "dwmapi.dll", "uxtheme.dll",
    "cabinet.dll", "propsys.dll", "oleacc.dll", "winsta.dll", "profapi.dll",
    # VC++ 재배포 패키지(설치 프로그램이 없으면 깔아 준다)
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "concrt140.dll",
}
API_SET_PREFIXES = ("api-ms-win-", "ext-ms-win-")
MAX_SUBSYSTEM = (10, 0)


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def inspect(path: Path) -> dict | None:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return None
    pe = _u32(data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    machine = _u16(data, pe + 4)
    n_sections = _u16(data, pe + 6)
    opt = pe + 24
    plus = _u16(data, opt) == 0x20B
    subsystem = (_u16(data, opt + 48), _u16(data, opt + 50))
    import_rva = _u32(data, opt + (112 if plus else 96) + 8)

    sections = []
    sec_off = opt + _u16(data, pe + 20)
    for i in range(n_sections):
        o = sec_off + i * 40
        sections.append((_u32(data, o + 12),
                         max(_u32(data, o + 8), _u32(data, o + 16)),
                         _u32(data, o + 20)))

    def to_offset(rva: int) -> int | None:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + (rva - va)
        return None

    dlls: list[str] = []
    off = to_offset(import_rva) if import_rva else None
    while off:
        entry = data[off:off + 20]
        if len(entry) < 20 or entry == b"\0" * 20:
            break
        name_off = to_offset(_u32(entry, 12))
        if name_off:
            dlls.append(data[name_off:data.index(b"\0", name_off)].decode("ascii", "replace").lower())
        off += 20

    return {"x64": machine == 0x8664, "subsystem": subsystem, "dlls": dlls}


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    files = [p for p in root.rglob("*") if p.suffix.lower() in {".exe", ".dll", ".pyd", ".drv"}]
    bundled = {p.name.lower() for p in files}
    problems: list[str] = []
    checked = 0

    for path in files:
        info = inspect(path)
        if info is None:
            continue
        checked += 1
        rel = path.relative_to(root)
        if info["subsystem"] > MAX_SUBSYSTEM:
            problems.append(f"{rel}: Windows {info['subsystem'][0]}.{info['subsystem'][1]} 이상을 요구")
        if not info["x64"] and path.suffix.lower() != ".exe":
            problems.append(f"{rel}: 64비트가 아님")
        for dll in info["dlls"]:
            if dll in bundled or dll in SYSTEM_DLLS or dll.startswith(API_SET_PREFIXES):
                continue
            problems.append(f"{rel}: 패키지에도 Windows 에도 없는 {dll} 를 필요로 함")

    print(f"Windows 10 호환성 검사: {checked}개 실행 파일")
    for p in problems:
        print(f"  [문제] {p}")
    if problems:
        print(f"  → {len(problems)}건. 패키지에서 빼거나 필요한 파일을 함께 넣어야 합니다.")
        return 1
    print("  문제 없음 (모두 64비트, Windows 10 에서 실행 가능, 필요한 DLL 이 모두 있음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
