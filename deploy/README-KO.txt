SOC 교대근무 인수인계 플랫폼 — 오프라인 설치 안내
=====================================================

인터넷이 없는 PC 에 설치하는 패키지입니다. 필요한 프로그램(Python, PostgreSQL,
Visual C++ 런타임)이 모두 들어 있어 따로 받을 것이 없습니다.

대상: Windows 10 / 11 (64비트), 디스크 여유 3GB 이상, 관리자 권한


1. 설치
-------
 1) zip 파일을 PC 로 복사한 뒤 압축을 풉니다(예: 바탕화면이나 D:\ 아래).
    ※ 압축 파일 안에서 바로 실행하지 말고 반드시 "압축 풀기"를 먼저 하십시오.
 2) 푼 폴더의 INSTALL.cmd 를 더블클릭합니다.
    "이 앱이 디바이스를 변경할 수 있도록 허용하시겠어요?" → [예]
 3) 화면 안내에 따라 Y 입력 → 관리자(admin) 비밀번호를 두 번 입력합니다.
    규칙: 12자 이상, 영문 대문자·소문자·숫자·특수문자 중 3종 이상, "admin" 포함 불가
 4) "설치 완료"가 나오면 끝입니다. 접속 주소가 함께 표시됩니다.

 설치 위치: C:\SOC-Handover  (다른 곳: INSTALL.cmd -InstallDir D:\SOC-Handover)
 포트     : 8080             (다른 포트: INSTALL.cmd -AppPort 8090)

 설치 프로그램이 해 주는 일
   - Visual C++ 런타임 설치(없을 때만)
   - DB(PostgreSQL) 초기화 · Windows 서비스 등록(SOC-Handover-DB, 자동 시작)
   - 앱 자동 시작 등록(작업 스케줄러 SOC-Handover — 부팅하면 켜지고, 죽으면 다시 켬)
   - 매일 03:00 자동 백업 등록(작업 스케줄러 SOC-Handover-Backup, 30일 보관)
   - Windows 방화벽에 8080 포트 허용 — 다른 PC 에서 접속 가능
   - 바탕화면에 "SOC 인수인계" 바로가기


2. 접속
-------
 - 이 PC      : http://localhost:8080/
 - 다른 PC    : http://<이 PC 이름 또는 IP>:8080/   (설치 완료 화면에 표시)
 - 브라우저   : Chrome 또는 Microsoft Edge (Internet Explorer 불가)
 - 처음 로그인하면 비밀번호를 한 번 더 바꿉니다.


3. 켜고 끄기 (설치 폴더 C:\SOC-Handover 안의 파일)
------------------------------------------------
 - 평소에는 아무것도 할 필요가 없습니다. PC 를 켜면 자동으로 켜집니다.
 - start.cmd    켜기(꺼 두었을 때)
 - stop.cmd     끄기(다음 부팅 때는 다시 자동으로 켜짐)
 - status.cmd   상태 보기(실행 여부 · DB · 최근 백업 · 디스크)
 - backup.cmd   지금 백업
 - restore.cmd  백업에서 복구(현재 데이터를 대체 — 확인 문구 입력)
 - uninstall.cmd  제거(기본은 데이터를 남김)

 자동 시작 없이 필요할 때만 켜고 끄려면 "수동 모드"로 설치합니다:
     INSTALL.cmd -Manual
   → start.cmd 로 켜고 stop.cmd 로 끕니다. 로그오프하거나 PC 를 끄면 함께 꺼집니다.

 자세한 운영 방법 · 문제 해결: C:\SOC-Handover\docs\OPERATIONS.md


4. 업그레이드
-------------
 새 버전 zip 을 풀고 INSTALL.cmd 를 실행하면 됩니다. 데이터와 설정은 그대로이며,
 교체 전에 DB 를 자동으로 백업합니다.


5. 설치가 안 될 때
------------------
 - 설치 기록: 오류 화면에 표시된 파일, 또는 C:\SOC-Handover\logs\soc-handover-install-*.log
 - "설치 파일이 없거나 손상" → zip 을 다시 복사해 압축을 푸십시오(USB 복사 오류).
 - "포트 8080 을 다른 프로그램이 사용" → INSTALL.cmd -AppPort 8090
 - Visual C++ 설치 뒤 "재부팅 필요" → 재부팅 후 INSTALL.cmd 다시 실행(이어서 진행됩니다).
 - 설치를 다시 실행해도 안전합니다. 끝난 단계는 건너뛰고 이어서 진행합니다.


포함된 외부 프로그램과 라이선스
------------------------------
 - Python 3.12 (PSF License)         : payload\runtime\python\LICENSE.txt
 - PostgreSQL 16 (PostgreSQL License): payload\runtime\pgsql\server_license.txt
 - Microsoft Visual C++ 재배포 패키지 : Microsoft 재배포 조건에 따라 원본 그대로 포함
 - Python 라이브러리(FastAPI 등)      : 각 패키지의 라이선스(payload\runtime\python\Lib\site-packages\*.dist-info)
