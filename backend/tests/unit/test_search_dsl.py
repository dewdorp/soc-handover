"""필터 DSL 검증 — 화이트리스트가 실제로 막는지."""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationFailed
from app.search import dsl, fields as reg, quick
from app.search.backends.base import escape_like
from app.search.dsl import Filter, SearchRequest, Sort

ALL_PERMS = frozenset({"handover:read_deleted"})


def _validate(**kwargs):
    dsl.validate(SearchRequest(**kwargs), permissions=ALL_PERMS)


class TestFieldWhitelist:
    def test_known_field_passes(self):
        _validate(filters=[Filter(field="company_id", op="in", value=[1, 2])])

    @pytest.mark.parametrize("bad", [
        "password_hash",                       # 다른 테이블의 민감 컬럼
        "users.password_hash",
        "id; DROP TABLE handovers",            # SQL 주입 시도
        "1=1",
        "search_tsv",                          # 내부 전용 컬럼
    ])
    def test_unknown_field_is_rejected(self, bad):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field=bad, op="eq", value="x")])

    def test_empty_field_is_rejected_by_schema(self):
        """빈 필드명은 레지스트리까지 가기 전에 스키마가 막는다(둘 다 422)."""
        with pytest.raises(PydanticValidationError):
            Filter(field="", op="eq", value="x")

    def test_rejection_tells_what_is_allowed(self):
        with pytest.raises(ValidationFailed) as exc:
            _validate(filters=[Filter(field="nope", op="eq", value=1)])
        assert "company_id" in exc.value.detail["allowed"]

    def test_restricted_field_needs_permission(self):
        flt = [Filter(field="is_deleted", op="eq", value=True)]
        dsl.validate(SearchRequest(filters=flt), permissions=ALL_PERMS)
        with pytest.raises(ValidationFailed):
            dsl.validate(SearchRequest(filters=flt), permissions=frozenset())


class TestOperatorGuard:
    def test_text_op_on_date_field_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="work_date", op="contains", value="8월")])

    def test_between_on_text_field_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="title", op="between", value=["a", "b"])])

    def test_unknown_operator_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="title", op="regex", value=".*")])

    def test_tags_only_accepts_tag_operators(self):
        _validate(filters=[Filter(field="tags", op="any_of_tags", value=["EDR"])])
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="tags", op="contains", value="EDR")])


class TestValueGuard:
    def test_in_requires_non_empty_list(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="company_id", op="in", value=[])])

    def test_in_rejects_scalar(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="company_id", op="in", value=1)])

    def test_eq_rejects_list(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="title", op="eq", value=["a", "b"])])

    def test_between_needs_two_values(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="work_date", op="between", value=["2026-01-01"])])

    def test_between_accepts_quick_range_token(self):
        _validate(filters=[Filter(field="work_date", op="between", value="THIS_WEEK")])

    def test_between_rejects_unknown_token(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="work_date", op="between", value="LAST_DECADE")])

    def test_is_null_needs_no_value(self):
        _validate(filters=[Filter(field="assignee_id", op="is_null")])

    def test_missing_value_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="title", op="contains")])

    def test_too_many_values_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(filters=[Filter(field="company_id", op="in",
                                      value=list(range(dsl.MAX_VALUES + 1)))])


class TestSortGuard:
    def test_sortable_field_passes(self):
        _validate(sort=[Sort(field="registered_date", dir="desc")])

    def test_non_sortable_field_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(sort=[Sort(field="content", dir="asc")])

    def test_unknown_sort_field_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(sort=[Sort(field="; DROP TABLE x", dir="asc")])


class TestQuickFilters:
    def test_all_tokens_expand(self):
        for token in quick.QUICK_FILTERS:
            expanded = quick.expand([token], user_id=7)
            assert expanded, f"{token} 이 빈 필터로 펼쳐졌다"
            for flt in expanded:
                assert reg.get_field(flt.field) is not None

    def test_expanded_quick_filters_pass_validation(self):
        for token in quick.QUICK_FILTERS:
            dsl.validate(SearchRequest(filters=quick.expand([token], 7)),
                         permissions=ALL_PERMS)

    def test_unknown_quick_token_is_rejected(self):
        with pytest.raises(ValidationFailed):
            _validate(quick=["DROP_EVERYTHING"])

    def test_open_uses_status_category_not_hardcoded_codes(self):
        """미완료 판정이 상태 코드 나열이면 관리자가 상태를 추가할 때 어긋난다."""
        fields = {f.field for f in quick.expand(["OPEN"], 1)}
        assert fields == {"status_category"}

    def test_mine_binds_to_the_caller(self):
        assert quick.expand(["MINE"], 42)[0].value == 42


class TestEscaping:
    @pytest.mark.parametrize("term,expected", [
        ("100%", "100\\%"),
        ("a_b", "a\\_b"),
        ("back\\slash", "back\\\\slash"),
        ("보통", "보통"),
    ])
    def test_like_wildcards_are_escaped(self, term, expected):
        assert escape_like(term) == expected


class TestRegistry:
    def test_every_non_special_field_has_a_column(self):
        special = {"status_category", "my_ack_state", "is_starred", "tags"}
        for name, definition in reg.HANDOVER_FIELDS.items():
            if name not in special:
                assert definition.column is not None, f"{name} 에 컬럼이 없다"

    def test_facetable_fields_are_exposed(self):
        assert "company_id" in reg.facetable_fields()
        assert "tags" in reg.facetable_fields()
        assert "content" not in reg.facetable_fields()

    def test_public_shape_lists_operators(self):
        public = reg.HANDOVER_FIELDS["title"].to_public()
        assert "contains" in public["ops"]
        assert "between" not in public["ops"]
