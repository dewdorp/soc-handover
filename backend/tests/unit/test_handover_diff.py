"""Version diff 계산 단위 테스트."""
from __future__ import annotations

from app.models.handover import VERSIONED_FIELDS
from app.services.handover_service import changed_between
from app.utils.diff import field_diff, tokenize, word_diff


class TestTokenize:
    def test_reconstructs_original_exactly(self):
        text = "  방화벽 정책 변경 \n 10.0.0.1 → 10.0.0.2  "
        assert "".join(tokenize(text)) == text

    def test_empty(self):
        assert tokenize("") == []
        assert tokenize(None) == []


class TestWordDiff:
    def test_identical_returns_single_equal(self):
        ops = word_diff("같은 내용", "같은 내용")
        assert ops == [{"op": "equal", "text": "같은 내용"}]

    def test_both_empty_returns_nothing(self):
        assert word_diff("", "") == []
        assert word_diff(None, None) == []

    def test_korean_word_replacement(self):
        ops = word_diff("방화벽 정책 변경 완료", "방화벽 정책 변경 보류")
        assert {"op": "delete", "text": "완료"} in ops
        assert {"op": "insert", "text": "보류"} in ops
        # 바뀌지 않은 앞부분은 equal 로 남아야 한다
        assert any(o["op"] == "equal" and "방화벽" in o["text"] for o in ops)

    def test_insertion_only(self):
        ops = word_diff("IP 차단", "IP 차단 완료")
        assert [o for o in ops if o["op"] == "delete"] == []
        assert any(o["op"] == "insert" and "완료" in o["text"] for o in ops)

    def test_ops_reconstruct_both_sides(self):
        before, after = "가 나 다 라", "가 다 마 라"
        ops = word_diff(before, after)
        rebuilt_before = "".join(o["text"] for o in ops if o["op"] in ("equal", "delete"))
        rebuilt_after = "".join(o["text"] for o in ops if o["op"] in ("equal", "insert"))
        assert rebuilt_before == before
        assert rebuilt_after == after

    def test_huge_text_falls_back_to_whole_replace(self):
        before, after = "가" * 15_000, "나" * 15_000
        ops = word_diff(before, after)
        assert [o["op"] for o in ops] == ["delete", "insert"]


class TestChangedBetween:
    def test_preserves_versioned_field_order(self):
        before = {f: None for f in VERSIONED_FIELDS}
        after = dict(before)
        after["title"] = "새 제목"
        after["company_id"] = 2
        # VERSIONED_FIELDS 순서상 company_id 가 title 보다 앞이다
        assert changed_between(before, after) == ["company_id", "title"]

    def test_no_change_returns_empty(self):
        snap = {"title": "동일", "content": "동일"}
        assert changed_between(snap, dict(snap)) == []

    def test_missing_key_counts_as_change(self):
        assert "title" in changed_between({}, {"title": "값"})


class TestFieldDiff:
    def test_long_text_field_gets_ops(self):
        out = field_diff({"content": "가 나"}, {"content": "가 다"}, ["content"])
        assert out[0]["field"] == "content"
        assert "ops" in out[0]

    def test_scalar_field_has_no_ops(self):
        out = field_diff({"status_code": "NEW"}, {"status_code": "DONE"}, ["status_code"])
        assert out[0]["before"] == "NEW"
        assert out[0]["after"] == "DONE"
        assert "ops" not in out[0]
