"""CSV · TSV 읽기 — Excel(xlsx)과 같은 모양으로 넘겨 마법사가 구분 없이 쓰게 한다.

현장에서 내려받는 CSV 는 만든 곳마다 제각각이라 두 가지를 알아서 맞춘다.

  · 인코딩: Excel 에서 'CSV(쉼표로 분리)'로 저장하면 한국어 Windows 는 cp949 로 쓴다.
            메모장·시스템에서 뽑으면 UTF-8(BOM 있기도 없기도). 순서대로 시도해 한글이 깨지지 않는 것을 고른다.
  · 구분자: 쉼표 · 탭 · 세미콜론 · 파이프. 헤더 부근에서 가장 일정하게 나오는 것을 고른다.

행 번호는 파일의 줄 번호(1부터)를 그대로 쓴다 — 원본 추적(source_row)이 Excel 과 같은 뜻이 되도록.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SUFFIXES = (".csv", ".tsv")
#: 한국어 환경에서 실제로 나오는 순서. 앞에서 성공하면 그것으로 읽는다.
ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "cp1252")
DELIMITERS = (",", "\t", ";", "|")
SAMPLE_BYTES = 64 * 1024


def is_csv(path: Path) -> bool:
    return path.suffix.lower() in SUFFIXES


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:SAMPLE_BYTES]
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # cp949 로도 '읽히기는' 하지만 깨진 한글이 되는 경우가 있어, 치환 문자가 있으면 다음 후보로
        if "�" not in text:
            return enc
    return "cp949"


def detect_delimiter(sample: str) -> str:
    lines = [ln for ln in sample.splitlines()[:20] if ln.strip()]
    if not lines:
        return ","
    try:
        return csv.Sniffer().sniff("\n".join(lines[:10]), delimiters="".join(DELIMITERS)).delimiter
    except csv.Error:
        # 줄마다 개수가 일정하고 가장 많이 나오는 구분자
        best, best_score = ",", 0
        for d in DELIMITERS:
            counts = [ln.count(d) for ln in lines]
            if counts[0] and len(set(counts)) == 1 and counts[0] > best_score:
                best, best_score = d, counts[0]
        return best


def open_text(path: Path) -> io.TextIOWrapper:
    return path.open("r", encoding=detect_encoding(path), errors="replace", newline="")


def read_rows(path: Path, limit: int | None = None) -> list[list[str]]:
    """앞부분 몇 줄을 표 형태로. 헤더 탐지 · 미리보기에 쓴다."""
    with open_text(path) as f:
        sample = f.read(SAMPLE_BYTES)
        f.seek(0)
        reader = csv.reader(f, delimiter=detect_delimiter(sample))
        rows: list[list[str]] = []
        for row in reader:
            rows.append([c.strip() for c in row])
            if limit and len(rows) >= limit:
                break
        return rows


def count_rows(path: Path, cap: int = 2_000_000) -> int:
    """대략 몇 줄인가(미리보기의 '예상 행 수'). 따옴표 안의 줄바꿈까지 정확히 세지는 않는다."""
    n = 0
    with path.open("rb") as f:
        for _ in f:
            n += 1
            if n >= cap:
                break
    return n


def sheet_name(path: Path, original_name: str | None = None) -> str:
    """CSV 는 Sheet 가 없다 — 파일 이름을 Sheet 이름처럼 쓴다(화면·기록에서 출처가 보이게)."""
    return Path(original_name or path.name).stem[:100] or "CSV"


def iter_rows(path: Path, header_row: int, headers: list[str]) -> Iterator[tuple[int, dict[str, Any]]]:
    """(줄 번호, {헤더: 값}). 헤더 줄 다음부터 흘려보낸다. 빈 줄은 빈 dict."""
    with open_text(path) as f:
        sample = f.read(SAMPLE_BYTES)
        f.seek(0)
        reader = csv.reader(f, delimiter=detect_delimiter(sample))
        for index, row in enumerate(reader, start=1):
            if index <= header_row:
                continue
            values = [c.strip() for c in row]
            if not any(values):
                yield index, {}
                continue
            yield index, {headers[i]: v for i, v in enumerate(values[:len(headers)]) if v != ""}
