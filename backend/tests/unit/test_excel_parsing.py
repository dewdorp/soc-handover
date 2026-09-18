"""Excel 셀 해석 · 헤더 탐지 · 매핑 제안 · 지문 단위 테스트."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.importers.excel.normalize import Lookups, normalize_row
from app.importers.excel.parsing import (auto_title, parse_date, split_people, to_json,
                                         year_from_sheet)
from app.importers.excel.reader import detect_header, header_names, suggest_mapping
from app.importers.excel import aliases as al
from app.utils.fingerprint import fingerprint, norm


class TestParseDate:
    @pytest.mark.parametrize("value,expected", [
        (datetime(2026, 9, 16, 14, 30), date(2026, 9, 16)),
        (date(2026, 9, 16), date(2026, 9, 16)),
        ("2026-09-16", date(2026, 9, 16)),
        ("2026.09.16", date(2026, 9, 16)),
        ("2026. 9. 16.", date(2026, 9, 16)),
        ("2026/9/16", date(2026, 9, 16)),
        ("20260916", date(2026, 9, 16)),
        (20260916, date(2026, 9, 16)),
        ("2026년 9월 16일", date(2026, 9, 16)),
        ("2026-09-16(화)", date(2026, 9, 16)),
        ("2026-09-16 14:30", date(2026, 9, 16)),
        ("26-09-16", date(2026, 9, 16)),
        ("2026-09-16T00:00:00", date(2026, 9, 16)),   # staging raw 에 보존된 datetime
        ("2026-09-16T14:30:00+09:00", date(2026, 9, 16)),
        (46281, date(2026, 9, 16)),          # 엑셀 일련번호
        (46281.5, date(2026, 9, 16)),
    ])
    def test_accepted_formats(self, value, expected):
        parsed = parse_date(value)
        assert parsed.value == expected
        assert parsed.inferred is False

    @pytest.mark.parametrize("value,expected", [
        ("9/16", date(2025, 9, 16)),
        ("09-16", date(2025, 9, 16)),
        ("9월 16일", date(2025, 9, 16)),
        ("9월16일(화)", date(2025, 9, 16)),
    ])
    def test_year_is_borrowed_and_flagged(self, value, expected):
        parsed = parse_date(value, fallback_year=2025)
        assert parsed.value == expected
        assert parsed.inferred is True, "연도를 추정했으면 추정했다고 남겨야 한다"

    def test_missing_year_without_hint_is_an_error(self):
        parsed = parse_date("9/16")
        assert parsed.value is None and parsed.error

    @pytest.mark.parametrize("value", ["2026-02-30", "13/40", "날짜모름", 12, "abc"])
    def test_garbage_is_an_error_not_a_guess(self, value):
        parsed = parse_date(value, fallback_year=2026)
        assert parsed.value is None
        assert parsed.error

    def test_blank_is_just_empty(self):
        assert parse_date(None) == (None, False, None)
        assert parse_date("   ").value is None


class TestSheetYear:
    @pytest.mark.parametrize("name,year", [
        ("2024", 2024), ("2024년", 2024), ("24년 인수인계", 2024), ("인수인계_2023", 2023),
    ])
    def test_year_found(self, name, year):
        assert year_from_sheet(name) == year

    @pytest.mark.parametrize("name", ["Sheet12", "참고자료", "", None, "12345"])
    def test_no_false_year(self, name):
        """'Sheet12' 를 2012년으로 읽으면 날짜가 전부 틀어진다."""
        assert year_from_sheet(name) is None


class TestPeople:
    @pytest.mark.parametrize("value,expected", [
        ("홍길동/김철수", ("홍길동", "김철수")),
        ("홍길동 / 김철수", ("홍길동", "김철수")),
        ("홍길동 → 김철수", ("홍길동", "김철수")),
        ("홍길동->김철수", ("홍길동", "김철수")),
        ("홍길동", ("홍길동", None)),
        (None, (None, None)),
        ("  ", (None, None)),
    ])
    def test_split(self, value, expected):
        assert split_people(value) == expected


class TestTextHelpers:
    def test_auto_title_uses_first_line(self):
        assert auto_title("방화벽 정책 변경\n세부 내용") == "방화벽 정책 변경"

    def test_auto_title_truncates(self):
        title = auto_title("가" * 100)
        assert len(title) == 60 and title.endswith("…")

    def test_to_json_keeps_original_shape(self):
        assert to_json(3.0) == 3
        assert to_json(datetime(2026, 9, 16, 1, 2)) == "2026-09-16T01:02:00"
        assert to_json("그대로") == "그대로"


class TestFingerprint:
    def test_notation_noise_is_absorbed(self):
        a = fingerprint("A사 ", "2026-09-16", "방화벽  정책, 변경!", "홍 길동")
        b = fingerprint("a사", "2026-09-16", "방화벽정책변경", "홍길동")
        assert a == b

    def test_different_day_is_different(self):
        assert fingerprint("A사", "2026-09-16", "x", "y") != fingerprint("A사", "2026-09-17", "x", "y")

    def test_only_first_500_chars_count(self):
        base = "가" * 500
        assert fingerprint("A", "d", base + "나", "s") == fingerprint("A", "d", base + "다", "s")

    def test_norm(self):
        assert norm(" 진행 상황 ") == norm("진행상황") == norm("진행-상황")


class TestHeaderDetection:
    lookup = al.build_lookup(al.HEADER_ALIASES)

    def test_skips_banner_and_blank_rows(self):
        rows = [["2025년 인수인계 대장", None, None], [None, None, None],
                ["관계사", "날짜", "내용"], ["A사", "2025-01-01", "x"]]
        assert detect_header(rows, self.lookup) == 2

    def test_duplicate_and_empty_headers_are_disambiguated(self):
        assert header_names(["비고", None, "비고"]) == ["비고", "열2", "비고_2"]


class TestSuggestMapping:
    def test_common_headers(self):
        mapping = suggest_mapping([["관계사", "날짜", "수행날짜", "진행 상황", "내용",
                                    "전달자/확인자", "비고", "담당부서"]])
        assert mapping == {
            "관계사": "company", "날짜": "registered_date", "수행날짜": "work_date",
            "진행 상황": "status", "내용": "content", "전달자/확인자": "sender_checker",
            "비고": "remark", "담당부서": None,
        }

    def test_spelling_can_differ_between_sheets(self):
        """연도별 Sheet 마다 '진행 상황'/'진행상황' 이 달라도 둘 다 상태여야 한다."""
        mapping = suggest_mapping([["진행 상황", "내용"], ["진행상황", "내용"]])
        assert mapping["진행 상황"] == "status"
        assert mapping["진행상황"] == "status"

    def test_same_field_twice_in_one_sheet_keeps_only_first(self):
        mapping = suggest_mapping([["전달자", "작성자", "내용"]])
        assert mapping["전달자"] == "sender"
        assert mapping["작성자"] is None, "뒤의 것은 원본 보존으로 남긴다"


class TestNormalizeRow:
    def _lk(self, **kw) -> Lookups:
        base = dict(
            companies={norm("A사"): 1}, statuses=dict(al.build_lookup(al.STATUS_ALIASES)),
            priorities=dict(al.build_lookup(al.PRIORITY_ALIASES)), users={norm("홍길동"): 7},
        )
        base.update(kw)
        return Lookups(**base)

    MAP = {"관계사": "company", "날짜": "registered_date", "진행": "status",
           "내용": "content", "전달": "sender", "부서": None}

    def test_clean_row(self):
        r = normalize_row({"관계사": "A사", "날짜": "2026-09-16", "진행": "완료",
                           "내용": "점검 완료", "전달": "홍길동", "부서": "보안팀"},
                          self.MAP, "2026", self._lk())
        assert r.errors == [] and r.warnings == []
        n = r.normalized
        assert (n["company_id"], n["status_code"], n["sender_id"]) == (1, "DONE", 7)
        assert n["title"] == "점검 완료" and n["title_auto_generated"] is True
        assert n["extra"] == {"부서": "보안팀"}, "매핑하지 않은 컬럼도 버리지 않는다"
        assert r.fingerprint

    def test_unknown_company_is_a_warning_not_an_error(self):
        r = normalize_row({"관계사": "처음보는사", "날짜": "2026-09-16", "내용": "x"},
                          self.MAP, "2026", self._lk())
        assert r.errors == []
        assert [w["code"] for w in r.warnings] == ["COMPANY_UNMATCHED"]
        assert r.normalized["company_action"] == "UNMATCHED"

    def test_value_map_can_create_company(self):
        r = normalize_row({"관계사": "처음보는사", "날짜": "2026-09-16", "내용": "x"},
                          self.MAP, "2026", self._lk(company_value_map={"처음보는사": "__CREATE__"}))
        assert r.warnings == []
        assert r.normalized["company_action"] == "CREATE"

    def test_unknown_status_falls_back_with_warning(self):
        r = normalize_row({"관계사": "A사", "날짜": "2026-09-16", "진행": "애매함", "내용": "x"},
                          self.MAP, "2026", self._lk(default_status="DONE"))
        assert r.normalized["status_code"] == "DONE"
        assert r.warnings[0]["code"] == "STATUS_UNMATCHED"

    def test_missing_date_is_an_error(self):
        r = normalize_row({"관계사": "A사", "날짜": "모름", "내용": "x"}, self.MAP, "2026", self._lk())
        assert r.errors[0]["code"] == "DATE_INVALID"
        assert r.fingerprint is None, "오류 행은 중복 판정 대상이 아니다"

    def test_empty_content_and_title_is_an_error(self):
        r = normalize_row({"관계사": "A사", "날짜": "2026-09-16"}, self.MAP, "2026", self._lk())
        assert r.errors[0]["code"] == "EMPTY_CONTENT"

    def test_unmatched_person_keeps_raw_name(self):
        r = normalize_row({"관계사": "A사", "날짜": "2026-09-16", "내용": "x", "전달": "외부인"},
                          self.MAP, "2026", self._lk())
        assert r.normalized["sender_name_raw"] == "외부인"
        assert r.normalized["sender_id"] is None
