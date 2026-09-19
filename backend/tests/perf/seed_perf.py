"""성능 측정용 대량 데이터 (NFR-01: 인수인계 50만 · 버전 150만 · 감사로그 500만).

마이그레이션 · bootstrap 이 끝난 **측정 전용 PostgreSQL DB** 에 COPY 로 넣는다(운영 DB 에 쓰지 말 것).

    set DATABASE_URL=postgresql+psycopg://soc_perf:...@127.0.0.1:55440/soc_perf
    python -m tests.perf.seed_perf --handovers 500000 --audit 5000000

인수인계 문장은 SOC 업무 문구 · IP · 장비명 · 관계사 이름을 섞어 검색(trigram · tsvector)이 실제처럼 걸리게 한다.
"""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg

from app.core.config import settings
from app.core.security import hash_password

KST = timezone(timedelta(hours=9))
rng = random.Random(20260919)

COMPANIES = [f"{p}{s}" for p in ("한빛", "누리", "가온", "다솜", "라온", "미르", "바른", "새솔")
             for s in ("금융", "증권", "카드", "생명", "캐피탈")]
SURNAMES = "김이박최정강조윤장임한오서신권황안송류홍"
GIVEN = ["민준", "서연", "도윤", "지우", "하준", "서윤", "시우", "지민", "주원", "하은", "예준", "수아"]
EVENTS = ["DDoS 공격 탐지", "EDR 악성코드 차단", "방화벽 정책 변경 요청", "VPN 이상 접속", "WAF SQL Injection 탐지",
          "계정 무차별 대입 시도", "랜섬웨어 의심 행위", "피싱 메일 신고", "IPS 시그니처 업데이트", "서버 이상 트래픽",
          "APT 의심 C2 통신", "DLP 개인정보 유출 의심", "웹셸 업로드 시도", "취약점 스캔 탐지", "로그 수집 장애"]
ACTIONS = ["차단 조치 완료", "고객사 담당자 통보", "추가 모니터링 필요", "정책 반영 대기", "원인 분석 중",
           "오탐 판정 후 종결", "장비 재기동 후 정상화", "관련 IP 블랙리스트 등록", "엔지니어 에스컬레이션"]
DEVICES = ["FW-CORE-01", "IPS-DMZ-02", "WAF-WEB-03", "EDR-MGR", "SIEM-01", "VPN-GW-01", "DLP-01", "NAC-02"]
STATUS_W = [("DONE", 62), ("CANCELED", 3), ("IN_PROGRESS", 12), ("NEW", 6), ("NEED_CHECK", 5),
            ("ACTION_PLANNED", 4), ("WAITING", 5), ("HOLD", 3)]
PRIO_W = [("NORMAL", 70), ("HIGH", 20), ("URGENT", 5), ("LOW", 5)]
AUDIT_W = [("HANDOVER_VIEW", 55), ("LOGIN_SUCCESS", 10), ("HANDOVER_UPDATE", 10), ("HANDOVER_CREATE", 6),
           ("HANDOVER_ACKNOWLEDGE", 6), ("HANDOVER_TRANSFER", 3), ("TASK_UPDATE", 3), ("EXCEL_EXPORT", 2),
           ("LOGIN_FAILURE", 2), ("LOGOUT", 3)]


def pick(weighted):
    return rng.choices([k for k, _ in weighted], [w for _, w in weighted])[0]


def ip() -> str:
    return f"{rng.choice([10, 172, 192, 203, 211])}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


def conninfo() -> str:
    return settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def seed(n_handovers: int, n_audit: int, years: int) -> None:
    t0 = time.time()
    with psycopg.connect(conninfo(), autocommit=False) as conn:
        cur = conn.cursor()
        # 참조 데이터
        company_ids = []
        for i, name in enumerate(COMPANIES):
            cur.execute("INSERT INTO companies (code, name, short_name, is_active, sort_order, created_at, updated_at) "
                        "VALUES (%s, %s, %s, true, %s, now(), now()) ON CONFLICT DO NOTHING RETURNING id",
                        (f"P{i:02d}", name, name[:2], i))
            row = cur.fetchone()
            if row:
                company_ids.append(row[0])
        cur.execute("SELECT id, name FROM companies")
        companies = dict(cur.fetchall())
        company_ids = list(companies)

        pw = hash_password("Perf#Bench2026!zq")
        users = []
        for i in range(60):
            name = rng.choice(SURNAMES) + rng.choice(GIVEN)
            role = "MANAGER" if i < 6 else "ANALYST"
            cur.execute("INSERT INTO users (username, display_name, password_hash, auth_provider, role_code, is_active, "
                        "must_change_password, failed_login_count, created_at, updated_at) "
                        "VALUES (%s, %s, %s, 'local', %s, true, false, 0, now(), now()) "
                        "ON CONFLICT (username) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id, display_name",
                        (f"perf{i:02d}", name, pw, role))
            users.append(cur.fetchone())
        conn.commit()
        print(f"참조 데이터: 관계사 {len(company_ids)} · 사용자 {len(users)}")

        # 인수인계 + 버전
        today = date.today()
        cur.execute("SELECT coalesce(max(id), 0) FROM handovers")
        next_id = cur.fetchone()[0] + 1
        h_cols = ("id, company_id, title, content, remark, status_code, priority_code, registered_date, work_date, "
                  "completed_at, sender_id, assignee_id, checker_id, is_important, is_pinned, is_recurring, "
                  "current_version_no, ack_state_cache, carry_count, fingerprint, created_by, updated_by, is_deleted, "
                  "search_text, created_at, updated_at")
        v_cols = "handover_id, version_no, change_type, before_data, after_data, changed_fields, changed_at, changed_by"
        versions = 0
        batch = 50_000
        for start in range(0, n_handovers, batch):
            hrows, vrows = [], []
            for k in range(start, min(start + batch, n_handovers)):
                hid = next_id + k
                # 최근일수록 많게(업무량 증가)
                days_ago = int((rng.random() ** 1.6) * years * 365)
                reg = today - timedelta(days=days_ago)
                work = reg + timedelta(days=rng.choice([0, 0, 0, 1, 1, 2, 3]))
                comp = rng.choice(company_ids)
                status = pick(STATUS_W)
                event = rng.choice(EVENTS)
                device = rng.choice(DEVICES)
                title = f"[{companies[comp]}] {event} - {device} {ip()}"
                content = (f"{reg:%m/%d} {rng.randint(0, 23):02d}시경 {device} 에서 {event}. 출발지 {ip()} → 목적지 {ip()}"
                           f" ({rng.randint(1, 9999)}건). {rng.choice(ACTIONS)}. 참고 티켓 SOC-{rng.randint(10000, 99999)}.")
                remark = rng.choice([None, None, None, "고객사 회신 대기", "야간 재확인 필요", "정기 점검 항목"])
                sender, assignee, checker = (rng.choice(users) for _ in range(3))
                n_ver = rng.choice([1, 2, 3, 3, 4, 5])
                created = datetime.combine(reg, datetime.min.time(), KST) + timedelta(minutes=rng.randint(0, 1439))
                done_at = created + timedelta(hours=rng.randint(1, 72)) if status in ("DONE", "CANCELED") else None
                search = " ".join(filter(None, [title, content, remark, companies[comp], sender[1], assignee[1], checker[1]]))
                hrows.append((hid, comp, title, content, remark, status, pick(PRIO_W), reg, work, done_at,
                               sender[0], assignee[0], checker[0], rng.random() < 0.05, False, False,
                               n_ver, "NONE", 0, uuid.uuid4().hex, sender[0], assignee[0], False,
                               search, created, created + timedelta(hours=n_ver)))
                snap = {"title": title, "status_code": status, "company_id": comp}
                for v in range(1, n_ver + 1):
                    vrows.append((hid, v, "CREATE" if v == 1 else "UPDATE",
                                  None if v == 1 else json.dumps({"status_code": "IN_PROGRESS"}),
                                  json.dumps(snap, ensure_ascii=False),
                                  json.dumps([] if v == 1 else ["status_code"]),
                                  created + timedelta(hours=v - 1), assignee[0]))
            with cur.copy(f"COPY handovers ({h_cols}) FROM STDIN") as cp:
                for r in hrows:
                    cp.write_row(r)
            with cur.copy(f"COPY handover_versions ({v_cols}) FROM STDIN") as cp:
                for r in vrows:
                    cp.write_row(r)
            versions += len(vrows)
            conn.commit()
            print(f"  인수인계 {start + len(hrows):>7,} / {n_handovers:,}  버전 {versions:,}  ({time.time() - t0:.0f}s)")
        cur.execute("SELECT setval(pg_get_serial_sequence('handovers', 'id'), (SELECT max(id) FROM handovers))")
        conn.commit()

        # 감사로그
        a_cols = ("event_uuid, occurred_at, user_id, username, role_code, client_ip, action, resource_type, "
                  "resource_id, result")
        now = datetime.now(KST)
        for start in range(0, n_audit, 200_000):
            with cur.copy(f"COPY audit_logs ({a_cols}) FROM STDIN") as cp:
                for _ in range(start, min(start + 200_000, n_audit)):
                    u = rng.choice(users)
                    action = pick(AUDIT_W)
                    cp.write_row((uuid.uuid4().hex, now - timedelta(seconds=rng.randint(0, years * 365 * 86400)),
                                  u[0], f"perf{u[0] % 60:02d}", "ANALYST", f"10.10.{rng.randint(0, 20)}.{rng.randint(1, 254)}",
                                  action, "HANDOVER" if action.startswith("HANDOVER") else "USER",
                                  str(rng.randint(1, max(1, n_handovers))), "FAILURE" if action == "LOGIN_FAILURE" else "SUCCESS"))
            conn.commit()
            print(f"  감사로그 {min(start + 200_000, n_audit):>9,} / {n_audit:,}  ({time.time() - t0:.0f}s)")

        conn.autocommit = True
        for table in ("handovers", "handover_versions", "audit_logs", "users", "companies"):
            cur.execute(f"VACUUM ANALYZE {table}")
    print(f"완료 ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--handovers", type=int, default=500_000)
    ap.add_argument("--audit", type=int, default=5_000_000)
    ap.add_argument("--years", type=int, default=5)
    a = ap.parse_args()
    seed(a.handovers, a.audit, a.years)
