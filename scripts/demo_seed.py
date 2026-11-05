# -*- coding: utf-8 -*-
"""화면 확인용 시연 데이터 — **빈 DB 에만** 넣는다.

왜 따로 두는가
  새 기능(열람 그룹 · 근무표 · 교대 마감 점검 · 내 일정)은 자료가 없으면 빈 화면만 보인다.
  화면을 보여 주거나 받아보기를 할 때마다 손으로 20분씩 만들 수는 없다.

안전장치
  · 업무가 이미 하나라도 있으면 **아무것도 하지 않고 멈춘다**(운영 DB 보호).
  · 사람 이름 · 관계사는 모두 가짜다. 실제 명단을 넣지 않는다.
  · 비밀번호는 실행할 때 만들어 파일로 적어 둔다(소스에 두지 않는다).

쓰는 법
    python scripts/demo_seed.py http://127.0.0.1:8099 admin <관리자비밀번호>
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta, timezone

import httpx

KST = timezone(timedelta(hours=9))

COMPANIES = ["가람은행", "나래카드", "다온증권", "라온캐피탈"]

#: (계정, 이름, 역할, 조)
PEOPLE = [
    ("kim.dh", "김도현", "MANAGER", "A"),
    ("lee.sj", "이서진", "ANALYST", "A"),
    ("park.mj", "박민준", "ANALYST", "A"),
    ("choi.ys", "최유신", "ANALYST", "A"),
    ("jung.hw", "정하윤", "MANAGER", "B"),
    ("kang.sy", "강수연", "ANALYST", "B"),
    ("yoon.jh", "윤지훈", "ANALYST", "B"),
    ("shin.ar", "신아람", "ANALYST", "B"),
    ("oh.tk", "오태경", "MANAGER", "C"),
    ("han.ye", "한예은", "ANALYST", "C"),
    ("seo.jw", "서준우", "ANALYST", "C"),
    ("bae.sh", "배소희", "ANALYST", "C"),
    ("nam.gm", "남건우", "MANAGER", "D"),
    ("ko.dy", "고다연", "ANALYST", "D"),
    ("moon.sb", "문시우", "ANALYST", "D"),
    ("im.hj", "임현주", "ANALYST", "D"),
]

GROUPS = [
    ("관제1팀", "가람은행 · 나래카드 관제"),
    ("관제2팀", "다온증권 · 라온캐피탈 관제"),
    ("CERT", "침해사고 대응 — 전 관계사"),
]

#: (관계사 index, 제목, 내용, 상태, 중요도, 그룹 index, 중요 여부)
WORK = [
    (0, "방화벽 정책 변경 요청 (10.20.1.0/24 → DMZ)",
     "변경 요청서 접수. 승인 대기 중이며 작업은 야간에 수행 예정.\n"
     "- 요청자: 인프라팀\n- 영향: 운영계 웹 3대\n- 롤백: 변경 전 정책 백업 보관",
     "NEED_CHECK", "HIGH", 0, False),
    (0, "IPS 시그니처 오탐 — SQL Injection 룰 조정",
     "결제 API 정상 요청이 차단됨. 임시로 해당 룰 탐지 전환, 영구 조치는 벤더 확인 후.",
     "IN_PROGRESS", "NORMAL", 0, False),
    (1, "랜섬웨어 의심 트래픽 탐지 (외부 C2 통신)",
     "내부 PC 1대에서 알려진 C2 도메인으로 반복 질의. 해당 PC 망분리 완료.\n"
     "포렌식 이미지 확보 후 CERT 로 이관.",
     "IN_PROGRESS", "URGENT", 2, True),
    (1, "VPN 계정 다중 지역 로그인",
     "동일 계정이 10분 내 서로 다른 국가 IP 로 접속. 계정 임시 잠금 후 본인 확인 진행.",
     "ACTION_PLANNED", "HIGH", 0, True),
    (2, "WAF 장비 메모리 사용률 92% — 재기동 협의",
     "지난주부터 상승 추세. 다음 정기 점검 시간에 재기동하기로 협의.",
     "WAITING", "NORMAL", 1, False),
    (2, "DDoS 모의 훈련 결과 공유",
     "훈련 중 임계값 조정 필요 구간 확인. 보고서 첨부 예정.",
     "DONE", "LOW", 1, False),
    (3, "계정 권한 정기 점검 (분기)",
     "휴직자 3명 계정 비활성, 퇴직자 1명 삭제 요청 완료.",
     "DONE", "NORMAL", 1, False),
    (3, "메일 피싱 신고 12건 — 동일 발신 도메인",
     "발신 도메인 차단 등록. 사용자 공지 발송 요청.",
     "IN_PROGRESS", "HIGH", 2, False),
    (0, "야간 백업 실패 (로그 서버)",
     "디스크 여유 부족. 보존기간 조정 후 재시도 성공.",
     "DONE", "NORMAL", 0, False),
    (1, "신규 관제 대상 서버 10대 등록",
     "에이전트 설치 및 수집 확인 완료. 대시보드 반영 대기.",
     "NEW", "NORMAL", 0, False),
]

SCHEDULES = [
    ("WAF 정기 점검", "INSPECTION", 1, 10, 2),
    ("월간 보안 회의", "MEETING", 2, 14, 1),
    ("방화벽 정책 작업 (야간)", "SECURITY_WORK", 3, 22, 3),
    ("일일 관제 현황 점검", "RECURRING", 1, 9, 0),
]


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    base, username, password = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]

    with httpx.Client(base_url=f"{base}/api/v1", timeout=30) as c:
        r = c.post("/auth/login", json={"username": username, "password": password})
        if r.status_code != 200:
            print(f"로그인 실패: {r.status_code} {r.text[:200]}")
            return 1
        c.headers["X-CSRF-Token"] = c.cookies.get("soc_csrf")

        existing = c.get("/handovers", params={"size": 1}).json()
        if existing.get("total_all"):
            print(f"이미 업무가 {existing['total_all']}건 있습니다 — 아무것도 넣지 않고 멈춥니다.")
            return 0

        # 관계사
        have = {x["name"]: x["id"] for x in c.get("/companies").json()}
        for name in COMPANIES:
            if name not in have:
                have[name] = c.post("/companies", json={"name": name}).json()["id"]
        company_ids = [have[n] for n in COMPANIES]
        print(f"관계사 {len(company_ids)}개")

        # 열람 그룹
        group_ids = []
        existing_groups = {g["name"]: g["id"] for g in c.get("/groups").json()}
        for name, desc in GROUPS:
            if name in existing_groups:
                group_ids.append(existing_groups[name])
                continue
            made = c.post("/groups", json={"name": name, "description": desc})
            made.raise_for_status()
            group_ids.append(made.json()["id"])
        print(f"열람 그룹 {len(group_ids)}개")

        # 사람 + 그룹 소속
        user_ids: dict[str, int] = {}
        for account, name, role, team in PEOPLE:
            made = c.post("/users", json={
                "username": account, "display_name": name, "role_code": role,
                "password": f"Soc#{account.replace('.', '')}2026!", "must_change_password": False})
            if made.status_code in (200, 201):
                user_ids[account] = made.json()["id"]
            else:
                found = c.get("/users", params={"q": account}).json()["items"]
                if found:
                    user_ids[account] = found[0]["id"]
        print(f"계정 {len(user_ids)}개")

        for account, _name, _role, team in PEOPLE:
            uid = user_ids.get(account)
            if uid is None:
                continue
            # A·B 조는 관제1팀, C·D 조는 관제2팀. 조장은 CERT 도 함께 본다.
            mine = [group_ids[0] if team in ("A", "B") else group_ids[1]]
            if _role == "MANAGER":
                mine.append(group_ids[2])
            c.put(f"/users/{uid}/groups",
                  json={"group_ids": mine, "default_group_id": mine[0]})

        # 관리자도 세 그룹을 모두 본다(시연 화면에서 전부 보이게)
        me = c.get("/auth/me").json()
        c.put(f"/users/{me['id']}/groups",
              json={"group_ids": group_ids, "default_group_id": group_ids[0]})

        # 근무조 편성
        teams = {t["code"]: t["id"] for t in c.get("/roster/teams").json()}
        for code in "ABCD":
            members = [user_ids[a] for a, _n, _r, t in PEOPLE if t == code and a in user_ids]
            if not members or code not in teams:
                continue
            c.put(f"/roster/teams/{teams[code]}/members",
                  json={"user_ids": members, "leader_id": members[0]})
        print(f"근무조 {len(teams)}개 편성")

        # 기준일 — 주기가 맞물리는 날로 맞춘다(이번 주 월요일)
        today = datetime.now(KST).date()
        monday = today - timedelta(days=today.weekday())
        c.post("/roster/epoch", params={"value": monday.isoformat()})

        # 업무
        made_ids = []
        for idx, (cidx, title, content, status, priority, gidx, important) in enumerate(WORK):
            reg = today - timedelta(days=len(WORK) - idx)
            payload = {
                "company_id": company_ids[cidx], "title": title, "content": content,
                "status_code": status, "priority_code": priority,
                "registered_date": reg.isoformat(),
                "work_date": (reg + timedelta(days=2)).isoformat(),
                "is_important": important,
                "group_ids": [group_ids[gidx]],
                "assignee_id": list(user_ids.values())[idx % max(1, len(user_ids))] if user_ids else None,
            }
            r = c.post("/handovers", json=payload)
            if r.status_code == 201:
                made_ids.append(r.json()["id"])
        print(f"업무 {len(made_ids)}건")

        # 교대 인계 — 다음 근무자에게 몇 건 넘겨 '인수 확인함'이 비어 있지 않게
        nxt = c.get("/roster/next-shift").json()
        if nxt.get("user_ids") and made_ids:
            c.post("/shift-handovers/basket/items", json={"handover_ids": made_ids[:4]})
            c.post("/shift-handovers/basket/send",
                   json={"to_user_ids": nxt["user_ids"][:2], "confirm_window": True,
                         "summary_note": "야간 중 발생한 건 공유합니다. 방화벽 작업은 승인 확인 후 진행하십시오."})
            print(f"교대 인계 1건 → {', '.join(nxt['names'][:2])}")

        # 바구니에 몇 건 남겨 둔다(마감 점검의 '보내지 않은 바구니'가 보이게)
        if len(made_ids) > 5:
            c.post("/shift-handovers/basket/items", json={"handover_ids": made_ids[5:7]})

        # 일정 + 내 알림
        for title, kind, day_offset, hour, reminder in SCHEDULES:
            start = datetime.combine(today + timedelta(days=day_offset), time(hour, 0), tzinfo=KST)
            body = {"title": title, "event_type": kind, "start_at": start.isoformat(),
                    "end_at": (start + timedelta(hours=2)).isoformat()}
            if kind == "RECURRING":
                body["recurrence_rule"] = "FREQ=DAILY"
            r = c.post("/schedules", json=body)
            if r.status_code == 201 and reminder:
                c.put(f"/schedules/{r.json()['id']}/reminder", json={"minutes_before": reminder * 10})
        print(f"일정 {len(SCHEDULES)}건")

        # 복수 담당 · CERT 전파 · 분석 의뢰 (§5)
        if made_ids and len(user_ids) >= 4:
            people = list(user_ids.values())
            ransom = made_ids[2]          # 랜섬웨어 의심 건
            c.put(f"/handovers/{ransom}/participants", json={"participants": [
                {"user_id": people[0], "role": "OWNER"},
                {"user_id": people[1], "role": "CO_OWNER"},
                {"user_id": people[4], "role": "REQUIRED"},
            ], "note": "야간 대응조"})
            # CERT 그룹에 참고로 전파 — 미리보기와 같은 계산으로 들어간다
            c.post(f"/handovers/{ransom}/propagate", json={
                "group_ids": [group_ids[2]], "role": "FYI", "note": "침해사고 공유"})
            # 분석 의뢰 → 접수까지(회신은 남겨 둬서 '답을 기다리는 중'이 보이게)
            c.post(f"/handovers/{ransom}/request", json={
                "to_user_ids": [people[8]],
                "note": "확보한 포렌식 이미지에서 C2 통신 흔적과 초기 침투 경로를 확인해 주십시오."})
            phish = made_ids[7]           # 피싱 신고 건 — 회신까지 끝난 예
            c.post(f"/handovers/{phish}/request", json={
                "to_user_ids": [people[9]], "note": "발신 도메인 평판 확인 부탁드립니다."})
            c.post(f"/handovers/{phish}/request/answer", json={
                "note": "해당 도메인은 3일 전 등록된 신규 도메인이며 다수 기관에서 악성으로 분류. 차단 권고."})
            print("담당 · 전파 · 의뢰 설정")

        # 개인 메모
        c.post("/me/notes", json={
            "title": "인계 전 확인 목록",
            "body": "- 방화벽 변경 승인 여부 확인\n- 랜섬웨어 의심 PC 포렌식 진행 상황\n"
                    "- WAF 재기동 시간 재확인 (다음 점검창)\n- 피싱 발신 도메인 차단 반영 확인"})

        # 대근 한 건 — 근무표에 '실근무자'가 보이게
        if nxt.get("user_ids"):
            busy = set(nxt["user_ids"])
            for day_row in c.get("/roster/day", params={"work_date": nxt["work_date"]}).json():
                busy |= set(day_row["actual_user_ids"])
            prev = (date.fromisoformat(nxt["work_date"]) - timedelta(days=1)).isoformat()
            for day_row in c.get("/roster/day", params={"work_date": prev}).json():
                busy |= set(day_row["actual_user_ids"])
            spare = next((uid for uid in user_ids.values() if uid not in busy), None)
            if spare is not None:
                c.post("/roster/overrides", json={
                    "work_date": nxt["work_date"], "shift_code": nxt["shift_code"],
                    "off_user_id": nxt["user_ids"][0], "on_user_id": spare, "reason": "병가"})
                print("대근 1건")

    print("시연 데이터 준비 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
