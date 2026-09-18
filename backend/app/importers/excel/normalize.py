"""staging raw → 정규화된 인수인계 값 + 경고 + 오류.

원칙
  · raw 는 절대 바꾸지 않는다. 정규화는 매번 raw 에서 다시 계산한다(값 매핑을 바꾸고
    다시 돌려도 결과가 결정적이다).
  · 막을 것(오류)과 알릴 것(경고)을 구분한다.
      오류 = 이 행을 인수인계로 만들 수 없음 → 기본 SKIP
      경고 = 만들 수는 있지만 사람이 알아야 함 → 기본 IMPORT
  · 인명은 항상 *_name_raw 로 원문을 남긴다. 사용자 매칭은 덤이다(B-10).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.importers.excel import aliases as al
from app.importers.excel.parsing import (auto_title, clean_text, parse_date, split_people,
                                         year_from_sheet)
from app.utils.fingerprint import fingerprint, norm

CREATE_COMPANY = "__CREATE__"

MAX_TITLE = 300
MAX_NAME = 100


@dataclass
class Lookups:
    """정규화에 필요한 기준정보. 행마다 DB 를 조회하지 않도록 job 단위로 한 번 만든다."""
    companies: dict[str, int]                 # norm(이름/약칭/코드) → id
    statuses: dict[str, str]                  # norm(별칭/이름/코드) → code
    priorities: dict[str, str]                # norm(별칭/이름/코드) → code
    users: dict[str, int]                     # norm(표시이름/계정) → id
    company_value_map: dict[str, Any] = field(default_factory=dict)   # 원문 → id | __CREATE__
    status_value_map: dict[str, str] = field(default_factory=dict)    # 원문 → code
    default_status: str = "DONE"
    default_year: int | None = None


@dataclass
class Result:
    normalized: dict[str, Any]
    warnings: list[dict[str, str]]
    errors: list[dict[str, Any]]
    fingerprint: str | None


def _pick(raw: dict[str, Any], mapping: dict[str, str | None], target: str) -> tuple[str | None, Any]:
    for header, mapped in mapping.items():
        if mapped == target and header in raw:
            return header, raw[header]
    return None, None


def normalize_row(raw: dict[str, Any], mapping: dict[str, str | None], sheet_name: str,
                  lk: Lookups) -> Result:
    warnings: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    def error(code: str, message: str, column: str | None, value: Any) -> None:
        errors.append({"code": code, "message": message, "column": column,
                       "raw_value": None if value is None else str(value)[:500]})

    year_hint = year_from_sheet(sheet_name) or lk.default_year

    # ---- 텍스트
    content_col, content_raw = _pick(raw, mapping, al.F_CONTENT)
    title_col, title_raw = _pick(raw, mapping, al.F_TITLE)
    remark_col, remark_raw = _pick(raw, mapping, al.F_REMARK)
    content = clean_text(content_raw) or ""
    title = clean_text(title_raw)
    remark = clean_text(remark_raw)
    title_auto = False
    if not title:
        title = auto_title(content)
        title_auto = title is not None
    if not title:
        error("EMPTY_CONTENT", "제목과 내용이 모두 비어 있습니다.", content_col, content_raw)
    elif len(title) > MAX_TITLE:
        title = title[: MAX_TITLE - 1] + "…"
        warn("TITLE_TRUNCATED", f"제목이 {MAX_TITLE}자를 넘어 잘렸습니다.")

    # ---- 날짜
    reg_col, reg_raw = _pick(raw, mapping, al.F_REGISTERED)
    work_col, work_raw = _pick(raw, mapping, al.F_WORK)
    reg = parse_date(reg_raw, fallback_year=year_hint)
    work = parse_date(work_raw, fallback_year=year_hint)
    date_inferred = reg.inferred or work.inferred
    if work.error:
        warn("WORK_DATE_INVALID", f"수행일을 해석하지 못해 비워 둡니다 — {work.error}")
    registered = reg.value
    if registered is None:
        if work.value is not None:
            registered = work.value
            warn("REGISTERED_FROM_WORK", "등록일이 없어 수행일로 채웠습니다.")
        else:
            error("DATE_INVALID", reg.error or "등록일이 없습니다.", reg_col, reg_raw)
    if date_inferred:
        warn("DATE_INFERRED", f"연도가 없어 시트 이름에서 {year_hint}년으로 추정했습니다.")

    # ---- 관계사
    comp_col, comp_raw = _pick(raw, mapping, al.F_COMPANY)
    company_name = clean_text(comp_raw)
    company_id: int | None = None
    company_action = "NONE"
    if company_name:
        mapped = lk.company_value_map.get(company_name)
        if mapped == CREATE_COMPANY:
            company_action = "CREATE"
        elif isinstance(mapped, int):
            company_id = mapped
        else:
            company_id = lk.companies.get(norm(company_name))
        if company_id is None and company_action != "CREATE":
            company_action = "UNMATCHED"
            warn("COMPANY_UNMATCHED",
                 f"등록되지 않은 관계사 '{company_name}' — 값 매핑에서 연결하거나 생성하십시오. "
                 "그대로 가져오면 '미지정'으로 들어가고 원래 이름은 비고에 남습니다.")
    else:
        company_action = "UNMATCHED"
        warn("COMPANY_EMPTY", "관계사가 비어 있어 '미지정'으로 들어갑니다.")

    # ---- 상태
    status_col, status_raw = _pick(raw, mapping, al.F_STATUS)
    status_text = clean_text(status_raw)
    status_code = lk.default_status
    if status_text:
        status_code = (lk.status_value_map.get(status_text)
                       or lk.statuses.get(norm(status_text)))
        if status_code is None:
            status_code = lk.default_status
            warn("STATUS_UNMATCHED",
                 f"진행상황 '{status_text}' 을(를) 알 수 없어 기본 상태({lk.default_status})로 둡니다.")

    # ---- 중요도
    _, prio_raw = _pick(raw, mapping, al.F_PRIORITY)
    prio_text = clean_text(prio_raw)
    priority_code = lk.priorities.get(norm(prio_text)) if prio_text else None
    if prio_text and priority_code is None:
        warn("PRIORITY_UNMATCHED", f"중요도 '{prio_text}' 을(를) 알 수 없어 '보통'으로 둡니다.")
    priority_code = priority_code or "NORMAL"

    # ---- 인명(원문은 항상 보존)
    _, sender_raw = _pick(raw, mapping, al.F_SENDER)
    _, checker_raw = _pick(raw, mapping, al.F_CHECKER)
    _, both_raw = _pick(raw, mapping, al.F_SENDER_CHECKER)
    _, assignee_raw = _pick(raw, mapping, al.F_ASSIGNEE)
    sender_name = clean_text(sender_raw)
    checker_name = clean_text(checker_raw)
    if both_raw is not None:
        s, c = split_people(both_raw)
        sender_name = sender_name or s
        checker_name = checker_name or c
    assignee_name = clean_text(assignee_raw)

    def person(name: str | None) -> tuple[str | None, int | None]:
        if not name:
            return None, None
        return name[:MAX_NAME], lk.users.get(norm(name))

    sender_name, sender_id = person(sender_name)
    checker_name, checker_id = person(checker_name)
    assignee_name, assignee_id = person(assignee_name)

    # ---- 매핑되지 않은 컬럼은 버리지 않는다
    mapped_headers = {h for h, t in mapping.items() if t}
    extra = {h: v for h, v in raw.items() if h not in mapped_headers}

    normalized = {
        "company_name": company_name,
        "company_id": company_id,
        "company_action": company_action,
        "title": title,
        "title_auto_generated": title_auto,
        "content": content,
        "remark": remark,
        "status_code": status_code,
        "status_raw": status_text,
        "priority_code": priority_code,
        "registered_date": registered.isoformat() if registered else None,
        "work_date": work.value.isoformat() if work.value else None,
        "date_inferred": date_inferred,
        "sender_name_raw": sender_name,
        "sender_id": sender_id,
        "checker_name_raw": checker_name,
        "checker_id": checker_id,
        "assignee_name_raw": assignee_name,
        "assignee_id": assignee_id,
        "extra": extra,
    }
    fp = None
    if not errors:
        fp = fingerprint(company_name, normalized["registered_date"], content or title,
                         sender_name)
    return Result(normalized, warnings, errors, fp)
