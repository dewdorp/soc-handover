"""테스트용 Excel 을 만든다. 실제 원본 파일을 아직 받지 못해(ASSUMPTIONS G-03)
현장 Excel 에서 흔한 모양을 일부러 섞는다.

  · 맨 위에 제목 배너 + 빈 줄이 있고 헤더는 3행에 있다
  · 연도별 Sheet 마다 헤더 표기가 조금씩 다르다(진행 상황 / 진행상황)
  · 날짜가 datetime · '2025.03.05' · '3월 7일' · 엑셀 일련번호 · '24-12-30' 로 제각각
  · '전달자/확인자' 한 칸에 두 사람
  · 안내용 Sheet, 빈 행, 같은 행 반복, 날짜 없는 행, 내용 없는 행
"""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook

HEADERS_2025 = ["관계사", "날짜", "수행날짜", "진행 상황", "내용", "전달자/확인자", "비고", "담당부서"]
HEADERS_2024 = ["관계사", "날짜", "진행상황", "내용", "전달자", "확인자", "비고"]

ROWS_2025 = [
    ["A보안", datetime(2025, 3, 2), "3/4", "완료", "방화벽 정책 변경\n10.0.0.1 허용",
     "홍길동/김철수", None, "보안팀"],
    ["B금융", "2025.03.05", None, "진행중", "EDR 경고 조사", "김철수 → 홍길동", "회신대기", None],
    ["신규업체", "3월 7일", None, "확인필요", "SSL VPN 이상징후", "홍길동", None, None],
    ["A보안", 45720, None, "보류됨", "DDoS 임계치 조정", "홍길동", None, None],
    [None, None, None, None, None, None, None, None],                         # 빈 행
    ["A보안", datetime(2025, 3, 2), "3/4", "완료", "방화벽 정책 변경\n10.0.0.1 허용",
     "홍길동/김철수", None, "보안팀"],                                          # 같은 행 반복
    ["A보안", "날짜모름", None, "완료", "날짜 없는 행", "홍길동", None, None],   # 날짜 오류
    ["A보안", datetime(2025, 3, 10), None, "완료", None, "홍길동", None, None],  # 내용 없음
]

ROWS_2024 = [
    ["B금융", "24-12-30", "완료", "연말 점검 결과 보고", "김철수", "홍길동", None],
    ["a보안 ", "2024년 12월 31일", "취소", "보안 장비 교체 계획 철회", "홍길동", None, None],
]


def build_workbook() -> bytes:
    wb = Workbook()
    notes = wb.active
    notes.title = "안내"
    notes["A1"] = "이 파일은 SOC 인수인계 기록입니다."
    notes["A2"] = "작성 요령: 매일 교대 시 작성"

    ws = wb.create_sheet("2025")
    ws["A1"] = "2025년 SOC 인수인계 대장"
    ws.append([])
    ws.append(HEADERS_2025)
    for row in ROWS_2025:
        ws.append(row)

    ws24 = wb.create_sheet("2024년")
    ws24.append(HEADERS_2024)
    for row in ROWS_2024:
        ws24.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_large(rows_per_sheet: int, sheets: int = 2) -> bytes:
    """성능 측정용. 서로 다른 내용이라 중복으로 걸리지 않는다."""
    wb = Workbook(write_only=True)
    for s in range(sheets):
        ws = wb.create_sheet(f"{2020 + s}")
        ws.append(["관계사", "날짜", "진행상황", "내용", "전달자", "비고"])
        for i in range(rows_per_sheet):
            ws.append([
                "A보안" if i % 2 else "B금융",
                datetime(2020 + s, 1 + i % 12, 1 + i % 28),
                "완료" if i % 3 else "진행중",
                f"{2020 + s}-{i:06d} 정기 점검 결과 이상 없음 · 장비 {i % 97}번 로그 확인",
                "홍길동" if i % 2 else "김철수",
                None,
            ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --------------------------------------------------------------------------- CSV

CSV_HEADERS = ["관계사", "날짜", "진행상황", "내용", "전달자", "확인자", "비고"]
CSV_ROWS = [
    ["A보안", "2025-03-02", "완료", "방화벽 정책 변경", "홍길동", "김철수", ""],
    ["B금융", "2025.03.05", "진행중", 'EDR 경고 조사, "우선순위 높음"', "김철수", "", "회신대기"],
    ["", "", "", "", "", "", ""],                                    # 빈 줄
    ["A보안", "3월 7일", "확인필요", "SSL VPN 이상징후", "홍길동", "", ""],
]


def build_csv(encoding: str = "utf-8-sig", delimiter: str = ",", *, banner: bool = True) -> bytes:
    """현장 CSV 를 흉내 낸다 — 위에 제목 줄이 있고, 따옴표 · 쉼표가 값 안에 들어 있다."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    writer = _csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    if banner:
        writer.writerow(["2025년 SOC 인수인계 대장"])
        writer.writerow([])
    writer.writerow(CSV_HEADERS)
    for row in CSV_ROWS:
        writer.writerow(row)
    return buf.getvalue().encode(encoding)


CSV_MIME = "text/csv"
