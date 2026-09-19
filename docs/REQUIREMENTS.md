# REQUIREMENTS.md — SOC 교대근무 인수인계·업무관리 플랫폼

> 문서 버전: 1.0 (Phase 0)
> 작성일: 2026-09-16
> 원본 요구사항: 사용자 제시 사양서 §0 ~ §92

---

## 1. 시스템 정의

**SOC 교대근무 업무 연속성 확보를 위한 인수인계·할일·일정·검색·이력관리 통합 플랫폼**

게시판도 아니고 AI 업무관리 도구도 아니다. 핵심 가치는 다음 10개이며, 모든 설계 판단의 tie-breaker로 사용한다.

```
빠르게 찾는다 / 놓치지 않는다 / 누가 담당하는지 안다 / 다음 교대자에게 정확히 전달한다 /
확인 여부가 남는다 / 모든 수정 이력이 남는다 / 과거 시점 상태를 복원할 수 있다 /
감사 시 증적을 제공한다 / AI 없이 완전하게 사용한다
```

## 2. 절대 우선순위 (§92)

| 순위 | 항목 | 설계 반영 |
|---|---|---|
| 1 | 업무 누락 방지 | Version 기준 확인(ack), 재확인 강제, Carry Forward, 미확인 배너 |
| 2 | 검색 편의성 | Excel Auto Filter 동등 이상 Column Filter + Global Search + Saved View |
| 3 | 교대 인수인계 명확성 | Shift Cockpit, 인계 Basket, 항목별 Version Pin |
| 4 | 업무 처리 편의성 | Drawer 기반 처리, Quick Add, My Work, Keyboard Shortcut |
| 5 | 수정/Version 추적 | Append-only HandoverVersion, Diff, Restore-as-new-version |
| 6 | 감사 증적 | AuditLog(행위) + VersionHistory(내용) 분리 |
| 7 | 성능 | 100k~500k rows, 서버사이드 전부, 인덱스 설계 |
| 8 | 사용 편의성 | Dense/Professional UI, 저소음 |
| 9 | ~~AI 기능~~ | **범위에서 제외**(2026-09-19, ASSUMPTIONS E-01) |

## 3. 사용자 및 역할 (§67)

| Role | 설명 | 핵심 권한 |
|---|---|---|
| ADMIN | 전체 관리 | 사용자/설정/상태코드/공용 View/Import/삭제데이터 조회/Audit 전체 |
| MANAGER | 근무 관리자 | 전체 조회, 담당자 지정, 중요업무 관리, 공용 View 생성, Audit 조회 |
| ANALYST | SOC 근무자 | 인수인계 CRUD, 확인, Task, 일정, 개인 View, Export |

향후 LDAP/AD 연동을 위해 인증(Authentication)과 인가(Authorization)를 분리한다.

## 4. 기능 요구사항 (Functional Requirements)

### FR-A. 인수인계 (Handover) — §7~§26

| ID | 요구사항 | 수용기준(AC) |
|---|---|---|
| FR-A-01 | Excel 유사 Dense Data Grid 목록 | 게시판 UI 금지. 기본 Row Density=Compact, Normal/Comfortable 전환 |
| FR-A-02 | 기본 컬럼 14종 표시 | ★/관계사/등록일/수행일/상태/중요도/제목/내용/전달자/담당자/확인자/확인상태/최근수정/비고/Tag |
| FR-A-03 | Column Filter (값 선택형) | 관계사·담당자·상태·전달자·중요도·태그: 실제 값 목록 + 검색 + 다중선택 + 건수 |
| FR-A-04 | Column Filter (텍스트형) | 포함/미포함/정확일치/시작/끝/비어있음/비어있지않음 |
| FR-A-05 | Column Filter (날짜형) | 오늘·어제·이번주·지난주·이번달·지난달·최근7일·최근30일·올해·작년·직접선택 |
| FR-A-06 | 복합 AND 검색 + Chip 표시 | 적용 필터가 Chip으로 노출, 개별 ×, 전체 초기화 |
| FR-A-07 | Global Search | 제목·내용·비고·관계사·전달자·담당자·확인자·태그 통합, Column Filter와 동시 사용 |
| FR-A-08 | 정렬/컬럼 제어 | 다중 Sort, Hide/Show, Resize, Reorder, Pinning, Header Freeze, Page Size |
| FR-A-09 | 건수 표시 | "전체 N건 / 현재 검색결과 M건" |
| FR-A-10 | Quick Filter 버튼 | 오늘·내담당·진행중·미완료·확인필요·중요·지연 |
| FR-A-11 | Saved View | Filter+Sort+Group+VisibleColumns+ColumnOrder+ColumnWidth+RowDensity+ViewType 저장, 개인/공용 구분 |
| FR-A-12 | 상세는 Right Side Drawer | 목록 컨텍스트 유지. Tab: 상세/할일/일정/전달이력/변경이력/첨부(+댓글) |
| FR-A-13 | 상태 관리 | 신규·진행중·확인필요·조치예정·대기·보류·완료·취소, 관리자 편집 가능 |
| FR-A-14 | 중요도 | 긴급·높음·보통·낮음. 색상 단독 사용 금지(Icon+Text 병행) |
| FR-A-15 | Soft Delete | deleted/deleted_at/deleted_by/delete_reason. Version/Audit 유지, 관리자 조회 가능 |
| FR-A-16 | 즐겨찾기(★)/상단고정 | 개인 즐겨찾기(star)와 전역 상단고정(pinned) 구분 |

### FR-B. Version / 이력 — §21~§26, §58~§59

| ID | 요구사항 | AC |
|---|---|---|
| FR-B-01 | 모든 수정은 Version 생성 | UPDATE로 과거 내용 소실 금지 |
| FR-B-02 | Version 레코드 필드 | handover_id, version_no, before_data, after_data, changed_fields, changed_by, changed_at, change_reason, client_ip, user_agent |
| FR-B-03 | Version Diff UI | 필드 단위 before→after, 장문 텍스트는 word-level diff 하이라이트 |
| FR-B-04 | 과거 Version 조회 | "⚠ 과거 버전 vN 조회 중" 배너 |
| FR-B-05 | 복원 = 새 Version | v7에서 v4 복원 시 v8 생성, change_type=RESTORE, restored_from_version=4 |
| FR-B-06 | Optimistic Lock | 409 Conflict + 현재 버전 + 내 변경 비교 제공, 무단 덮어쓰기 금지 |
| FR-B-07 | Activity Timeline | Version/Ack/Transfer/Task/Comment/Attachment를 시간순 통합 표시 |
| FR-B-08 | Version History ≠ Audit Log | 분리 구현 |

### FR-C. 교대 인수인계 (Shift Handover) — §27~§34

| ID | 요구사항 | AC |
|---|---|---|
| FR-C-01 | Shift Cockpit 전용 화면 | 6영역: 근무중 신규/진행중/확인필요/다음근무 예정/중요/지연 |
| FR-C-02 | 인계 Basket | 항목 선택 → Basket 담기, Basket 별도 패널, Draft 상태 유지 |
| FR-C-03 | 인계 실행 | ShiftHandover Session 생성: shift, 전달자, 수신자, 전달시간, 항목, 항목별 version, 확인여부/시간 |
| FR-C-04 | 미확인 배너 | 로그인 시 "⚠ 확인하지 않은 인수인계 N건" + 이동 |
| FR-C-05 | Version 기준 확인 | confirmed=true 금지. acked_version_no 기록 |
| FR-C-06 | 재확인 필요 자동 전환 | 지정 필드 변경 시 기존 ack → REACK_REQUIRED |
| FR-C-07 | 재확인 대상 필드 설정화 | 기본: 제목·내용·수행일·상태·중요도·담당자. 관리자 변경 가능 |
| FR-C-08 | Carry Forward | 미완료 업무는 데이터 복제 없이 다음 교대에 계속 노출, carry 횟수 추적 |
| FR-C-09 | 일괄 확인 | 선택 항목 확인 / 전체 확인 |

### FR-D. My Work / Task — §35~§41

| ID | 요구사항 | AC |
|---|---|---|
| FR-D-01 | My Work 통합 | 내 담당 Handover + 내 Task + 내가 확인해야 할 Handover + 내 일정 |
| FR-D-02 | 버킷 | 오늘/지연/이번주/예정/대기/완료 + 상단 카운터 |
| FR-D-03 | View 전환 | List / Board / Calendar |
| FR-D-04 | Task 필드 | §38 전체 |
| FR-D-05 | Kanban Drag&Drop 상태변경 | 변경은 Audit 기록 |
| FR-D-06 | Handover에서 Task Quick Add | 관계사·연관 Handover·내용 일부 자동 채움 |
| FR-D-07 | Checklist | Task 내부 소작업, 진행률 표시 |
| FR-D-08 | Task Comment / Attachment | 본문과 분리 |

### FR-E. 일정 (Schedule) — §42~§43

| ID | 요구사항 | AC |
|---|---|---|
| FR-E-01 | Month/Week/Day 뷰 | |
| FR-E-02 | 일정 유형 | 일반·작업예정·점검·회의·보안작업·반복업무 |
| FR-E-03 | Handover/Task 연계 | 상세에서 일정 생성, Event 클릭 시 원본 이동 |
| FR-E-04 | Drag&Drop 일자 변경 | Audit 기록 필수 |

### FR-F. Excel Import/Export — §44~§49

| ID | 요구사항 | AC |
|---|---|---|
| FR-F-01 | 8-Step Wizard | 파일→Sheet분석→Mapping→Preview→Validation→중복검사→Import→결과 |
| FR-F-02 | 연도별 Sheet 처리 | Sheet당 5,000행, 총 수십만행 |
| FR-F-03 | 원본 컬럼 무손실 | 관계사·날짜·수행날짜·진행상황·내용·전달자·확인자·비고 + 미매핑 컬럼은 raw JSON 보존 |
| FR-F-04 | 원본 추적 | source_file / source_sheet / source_row / import_job_id |
| FR-F-05 | Fingerprint 중복 검사 | 정규화 해시, 자동 삭제 금지, 사용자 선택 |
| FR-F-06 | Import 진행률/결과 리포트 | 성공/중복의심/실패 건수 + 실패 사유 다운로드 |
| FR-F-07 | Export | 전체 + **현재 Filter/Sort 적용 결과만** Export, Audit 기록 |

### FR-G. 검색 아키텍처 — §50~§51

| ID | 요구사항 | AC |
|---|---|---|
| FR-G-01 | 우선순위 준수 | ColumnFilter > QuickFilter > GlobalSearch > SavedView > Advanced > FTS |
| FR-G-02 | 전량 서버사이드 | Pagination/Filter/Sort/Search/Aggregation. 전체 데이터 클라이언트 전송 금지 |
| FR-G-03 | Full Text Search | PostgreSQL FTS + 한글 전략(trigram 병행) |
| FR-G-04 | Facet 값 조회 | 값이 많으면 서버사이드 검색 |

### FR-H. AI — §52~§57 · **범위에서 제외**

AI(자연어 검색 · 임베딩 · 요약 · 태그 추천)는 만들지 않는다(2026-09-19 사용자 결정, ASSUMPTIONS E-01).
FR-H-01~05 는 적용하지 않는다. 원래 요구사항은 git 기록의 이 문서 이전 판에 있다.

### FR-I. 감사/관리 — §60~§66

| ID | 요구사항 | AC |
|---|---|---|
| FR-I-01 | Audit 이벤트 30종 이상 | §60 목록 전체 |
| FR-I-02 | Audit 필드 | §61 전체 (before/after, result, error_message 포함) |
| FR-I-03 | Audit UI = Excel Style Grid | 기간/사용자/Action/Resource/IP/성공실패 필터, Export |
| FR-I-04 | 첨부파일 | 확장자 allowlist, 최대크기, 저장경로 설정, 업로드/삭제 Audit, 백신 연동 확장점 |
| FR-I-05 | Comment/Note | 본문 Version과 분리, 댓글 수정/삭제도 Audit |
| FR-I-06 | Notification Center | 7종 알림, 내부 알림만으로 동작 |

### FR-J. 운영 — §2, §82

| ID | 요구사항 | AC |
|---|---|---|
| FR-J-01 | Windows 10 네이티브 실행 | Docker 필수 금지, Linux 전용 금지 |
| FR-J-02 | PowerShell 스크립트 6종 | install / start / stop / backup / restore / status |
| FR-J-03 | 복사-붙여넣기 설치 문서 | README.md, INSTALL_WINDOWS.md |
| FR-J-04 | Backup/Restore Audit 기록 | |

## 5. 비기능 요구사항 (NFR)

| ID | 항목 | 목표 |
|---|---|---|
| NFR-01 | 데이터 규모 | Handover 500,000행, Version 1,500,000행, Audit 5,000,000행 |
| NFR-02 | 검색 응답 | 50만건 기준 필터+정렬+페이징 P95 < 800ms (로컬 PG, 인덱스 적중) |
| NFR-03 | 목록 첫 페이지 | P95 < 1.5s (네트워크 포함, 내부망) |
| NFR-04 | Import 처리량 | 분당 10,000행 이상, 30만행 무중단 |
| NFR-05 | 동시 사용자 | 20~50명 동시 접속 |
| NFR-06 | 브라우저 | Chrome / Edge 최신 2개 버전 |
| NFR-07 | 오프라인 | 인터넷 없이 동작(설치 시 1회 의존성 확보 또는 오프라인 번들) |
| NFR-08 | 가용성 | 단일 노드. 재기동 5분 이내, 일 1회 백업 |
| NFR-09 | 감사 보존 | Audit 최소 1년, Version 영구(삭제 금지) |
| NFR-10 | 접근성 | 색상 단독 의미전달 금지, 키보드 조작 가능 |

## 6. 범위 외 (Out of Scope)

- 모바일 전용 앱 / 모바일 최적화(태블릿 이상만 고려)
- 외부 SMTP 메일 발송, SMS, 메신저 연동
- 다중 노드 HA, 분산 검색엔진(Elasticsearch)
- SSO(SAML/OIDC) — AuthProvider 인터페이스로 확장점만 확보
- SIEM/TI 플랫폼 직접 연동

## 7. §89 자기검증 질문에 대한 설계 응답

| 질문 | 설계 응답 |
|---|---|
| 다음 근무자가 중요한 업무를 놓칠 가능성은? | Basket 인계 + 미확인 배너 + Carry Forward + 지연/중요 전용 영역. 확인 전까지 계속 노출 |
| 확인 후 내용이 바뀌면 알 수 있는가? | ack는 version_no 기준. 재확인 대상 필드 변경 시 REACK_REQUIRED 자동 전환 + 알림 |
| 과거 내용이 수정으로 사라지는가? | 사라지지 않음. append-only version, after_data 전체 스냅샷 보존 |
| 몇 년 전 업무를 쉽게 찾는가? | 연도 무관 단일 테이블 + 날짜 Quick Filter + FTS + Saved View |
| Excel보다 불편하지 않은가? | 컬럼 헤더 필터 = Excel Auto Filter 동등. 추가로 Chip/SavedView/Global Search |
| 오늘 할 일을 한눈에? | Dashboard 6 KPI + My Work 버킷 |
| 누가 누구에게 무엇을 전달했는가? | ShiftHandover(Session) - Item - Ack 3계층 기록 |
| 누가 어느 Version을 확인했는가? | handover_acknowledgements.acked_version_no |
| 누가 언제 무엇을 수정했는가? | handover_versions.changed_by/at/changed_fields + audit_logs |
| 감사 시 변경 전 내용 재현? | after_data 전체 스냅샷으로 임의 시점 복원 가능 |
| 10만건 이상 검색 가능한가? | 서버사이드 + 복합 인덱스 + tsvector/trgm + keyset 페이징 |
| Windows 10 운영 가능한가? | 네이티브 프로세스 + PowerShell 6종 스크립트 + 단일 포트 서비스 |
