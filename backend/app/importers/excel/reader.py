"""Excel 읽기 — 헤더 탐지 · Sheet 요약 · 행 순회 · 매핑 제안.

openpyxl read_only=True 로 연다. 파일 전체를 메모리에 올리지 않으므로 수십만 행도
메모리가 일정하다. data_only=True 로 수식 대신 **계산된 값**을 읽는다(수식 문자열이
내용으로 들어가는 사고 방지).
"""
from __future__ import annotations

import difflib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.importers.excel import aliases as al
from app.importers.excel import csv_source
from app.importers.excel.parsing import clean_text, to_json, year_from_sheet
from app.utils.fingerprint import norm

HEADER_SCAN_ROWS = 15
SAMPLE_ROWS = 5


def open_workbook(path: Path):
    return load_workbook(filename=str(path), read_only=True, data_only=True)


def _row_values(row) -> list[Any]:
    return [cell.value if hasattr(cell, "value") else cell for cell in row]


def _header_score(values: list[Any], lookup: dict[str, str]) -> int:
    return sum(1 for v in values if v is not None and norm(v) in lookup)


def detect_header(rows: list[list[Any]], lookup: dict[str, str]) -> int:
    """헤더로 보이는 행 번호(0 기반). 알려진 컬럼 이름이 가장 많이 나오는 행을 고른다.

    제목 행·빈 행·병합된 안내문이 위에 몇 줄 있어도 헤더를 찾는다.
    """
    best, best_score = -1, 0
    for i, values in enumerate(rows):
        score = _header_score(values, lookup)
        if score > best_score:
            best, best_score = i, score
    if best_score >= 2:
        return best
    for i, values in enumerate(rows):  # 아는 이름이 없으면 값이 2개 이상인 첫 행
        if sum(1 for v in values if clean_text(v)) >= 2:
            return i
    return 0


def header_names(values: list[Any]) -> list[str]:
    """빈 헤더는 '열N', 같은 이름이 또 나오면 '비고_2' 처럼 구분한다(원본 무손실)."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for i, value in enumerate(values, start=1):
        base = clean_text(value) or f"열{i}"
        base = base.replace("\n", " ")
        count = seen.get(base, 0) + 1
        seen[base] = count
        names.append(base if count == 1 else f"{base}_{count}")
    return names


def analyze(path: Path, *, db=None, original_name: str | None = None) -> list[dict[str, Any]]:
    """Sheet 별 행 수 · 헤더 · 샘플. 전체를 읽지 않고 앞부분만 본다.

    CSV · TSV 는 Sheet 가 하나인 파일로 본다 — 마법사 이후 단계는 Excel 과 똑같이 돈다.
    """
    lookup = al.build_lookup(al.header_aliases(db))
    if csv_source.is_csv(path):
        return [_analyze_csv(path, lookup, original_name)]
    wb = open_workbook(path)
    try:
        sheets = []
        for ws in wb.worksheets:
            head = [_row_values(r) for r in ws.iter_rows(max_row=HEADER_SCAN_ROWS)]
            if not any(any(v is not None for v in r) for r in head):
                sheets.append({"name": ws.title, "header_row": None, "headers": [],
                               "estimated_rows": 0, "samples": [], "recognized": 0,
                               "year_hint": year_from_sheet(ws.title)})
                continue
            h = detect_header(head, lookup)
            headers = header_names(head[h])
            samples = []
            for values in head[h + 1: h + 1 + SAMPLE_ROWS]:
                if any(clean_text(v) for v in values):
                    samples.append({headers[i]: to_json(v)
                                    for i, v in enumerate(values[: len(headers)])})
            max_row = ws.max_row or 0
            sheets.append({
                "name": ws.title,
                "header_row": h + 1,                       # 사람이 보는 1 기반 행 번호
                "headers": headers,
                "estimated_rows": max(0, max_row - (h + 1)),
                "samples": samples,
                "recognized": _header_score(head[h], lookup),
                "year_hint": year_from_sheet(ws.title),
            })
        return sheets
    finally:
        wb.close()



def _analyze_csv(path: Path, lookup: dict[str, str], original_name: str | None) -> dict[str, Any]:
    head = csv_source.read_rows(path, limit=HEADER_SCAN_ROWS)
    name = csv_source.sheet_name(path, original_name)
    if not head:
        return {"name": name, "header_row": None, "headers": [], "estimated_rows": 0,
                "samples": [], "recognized": 0, "year_hint": year_from_sheet(name)}
    h = detect_header(head, lookup)
    headers = header_names(head[h])
    samples = [{headers[i]: to_json(v) for i, v in enumerate(values[:len(headers)])}
               for values in head[h + 1: h + 1 + SAMPLE_ROWS] if any(clean_text(v) for v in values)]
    return {
        "name": name,
        "header_row": h + 1,
        "headers": headers,
        "estimated_rows": max(0, csv_source.count_rows(path) - (h + 1)),
        "samples": samples,
        "recognized": _header_score(head[h], lookup),
        "year_hint": year_from_sheet(name),
    }


def suggest_mapping(sheet_headers: list[list[str]], *, db=None) -> dict[str, str | None]:
    """헤더 → 시스템 필드 제안. 정확 일치 → 별칭 → 유사도 순. 확신 없으면 None(원본 보존).

    '한 필드에 컬럼 하나' 는 **Sheet 단위** 제약이다. 연도별 Sheet 마다 표기가 달라
    2024 는 '진행상황', 2025 는 '진행 상황' 이어도 둘 다 상태로 연결돼야 한다.
    """
    aliases = al.header_aliases(db)
    lookup = al.build_lookup(aliases)
    vocabulary = {norm(word): target for target, words in aliases.items() for word in words}

    def guess(header: str) -> str | None:
        key = norm(header)
        target = lookup.get(key)
        if target is None and key:
            close = difflib.get_close_matches(key, list(vocabulary), n=1, cutoff=0.8)
            target = vocabulary[close[0]] if close else None
        return target

    out: dict[str, str | None] = {}
    for headers in sheet_headers:
        # 앞 Sheet 에서 이미 정해진 헤더가 이 Sheet 에서 차지한 필드
        used = {out[h] for h in headers if out.get(h)}
        for header in headers:
            if header in out:
                continue
            target = guess(header)
            if target in used:
                target = None  # 같은 Sheet 에 같은 필드가 또 나오면 뒤의 것은 원본 보존
            if target:
                used.add(target)
            out[header] = target
    return out


def iter_rows(path: Path, sheet_name: str, header_row: int) -> Iterator[tuple[int, dict[str, Any]]]:
    """(엑셀 행 번호, {헤더: 값}) 를 흘려보낸다. 행 번호는 원본 추적(source_row)에 그대로 쓴다.

    완전히 빈 행은 빈 dict 로 흘려보낸다. 적재는 하지 않지만 호출자가 '빈 행 N건'을
    보고서에 남길 수 있게 한다(행이 조용히 사라지면 누락처럼 보인다).
    """
    if csv_source.is_csv(path):
        head = csv_source.read_rows(path, limit=header_row)
        headers = header_names(head[header_row - 1]) if len(head) >= header_row else []
        yield from csv_source.iter_rows(path, header_row, headers)
        return

    wb = open_workbook(path)
    try:
        ws = wb[sheet_name]
        header_values: list[Any] | None = None
        for excel_row, row in enumerate(ws.iter_rows(min_row=header_row), start=header_row):
            values = _row_values(row)
            if header_values is None:
                header_values = values
                headers = header_names(values)
                continue
            if not any(clean_text(v) for v in values[: len(headers)]):
                yield excel_row, {}
                continue
            yield excel_row, {headers[i]: to_json(v)
                              for i, v in enumerate(values[: len(headers)])
                              if v is not None}
    finally:
        wb.close()
