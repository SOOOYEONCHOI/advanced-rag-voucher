# 배포 전 점검(보안·최적화·운영) 계획

> **상태(2026-10-13):** 발견 1~19 처리 완료, Task 10 운영 서버 점검은 DEPLOYMENT §9 로 옮김. 아래 체크박스는 점검 당시 그대로이고, 결과의 정본은 "발견 사항"·"처리 결과" 표다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영 서버에 올리기 전에 보안·성능·운영 준비를 빠짐없이 점검하고, 발견 사항을 심각도와 함께 한 표로 남긴다.

**Architecture:** 점검과 수정을 나눈다. 이 계획은 **점검만** 한다 — 코드를 고치지 않고 발견 사항(재현 명령·근거 포함)을 아래 "발견 사항" 표에 적는다. 수정은 표를 보고 사용자가 고른 것만 별도 작업으로 한다. 점검은 (A) 이 저장소·개발 서버에서 할 수 있는 것(T1~T9, T11)과 (B) 운영 서버가 서야 할 수 있는 것(T10)으로 나뉜다.

**Tech Stack:** Python 3.12.3 · Django 5.0.4 · PostgreSQL 16(RLS) · gunicorn 23 + nginx + systemd · whitenoise 6.9 · jQuery 3.7.1 · Bootstrap 5.3.6 · WeZonGrid

**Spec:** 사용자 요청(2026-10-07) "배포 전 꼭 점검해야 할 내용(최적화+보안 포함) 모두 점검". 기존 기준: [DEPLOYMENT §9 운영 점검 목록](../../../DEPLOYMENT.md)·[STATUS §2-2 운영 제약](../../../STATUS.md)·[계약 §13·§16](../../../client/SERVER_API_CONTRACT.md)

## Global Constraints

- 점검 중에 코드·설정·DB 스키마를 바꾸지 않는다. 임시 스크립트는 scratchpad 에 두고 저장소에 넣지 않는다(남길 가치가 있으면 발견 사항에 "검사 스크립트로 남김" 제안으로 적는다)
- 테스트는 `--settings=configurations.test_settings` 로 돌린다. e2e 는 `E2E-` 데이터만 만들고 지운다
- 비밀(API Key·비밀번호·토큰)을 결과 표·로그·커밋에 쓰지 않는다. 필요하면 끝 4자리만 적는다
- `X_FRAME_OPTIONS = 'SAMEORIGIN'`(W019)·인증 없는 배포물 4경로(DEC-024)는 **의도된 것**이다. 발견 사항으로 올리지 않는다
- 보안 점검 도구(pip-audit·bandit 등)는 프로젝트 `.venv` 에 설치하지 않는다. 임시 가상환경에서 돌린다 — 실행 전 사용자 승인
- 운영 DB·운영 서버에 쓰는 명령은 이 계획에 없다. T10 은 운영 서버에서 **읽기·확인만** 한다

## 심각도 기준

| 등급 | 뜻 | 예 |
|---|---|---|
| **차단** | 고치기 전에는 배포하지 않는다 | 인증 없이 검사 이미지가 열린다, 지원 끝난 프레임워크에 공개 취약점 |
| **높음** | 배포 일정 안에 고친다 | 긴 다운로드가 워커 타임아웃으로 끊긴다 |
| **보통** | 다음 배포 전에 고친다 | 화면마다 1MB 넘는 JS 를 캐시 없이 다시 받는다 |
| **낮음 / 수용** | 기록만 한다 | 사내망 전제의 위험을 받아들인다 |

## 발견 사항 (점검하며 채운다)

점검일 2026-10-07, 브랜치 `audit/predeploy`(기준 `b4f67a5`). "재현"은 개발 서버에서 실제로 일으켜 본 것, "코드"는 코드를 읽어 확인한 것이다.

| # | 영역(Task) | 등급 | 내용 | 근거 | 제안 |
|---|---|---|---|---|---|
| 1 | 인가·XSS (T5·T6) | **차단** | 레거시 `/api/files/*`(upload·download·image·excel_export)가 **로그인한 누구나** 쓸 수 있다(메뉴 매핑이 빈 목록 = 로그인만 확인). 작업자가 HTML 파일을 올리면 `/api/files/image` 가 같은 출처에서 `text/html; inline` 으로 내준다 → 관리자가 링크를 열면 관리자 권한으로 스크립트 실행(저장형 XSS). 첨부를 id 로 아무거나 받고(`download`), `file_id` 로 남의 첨부 행을 덮어쓴다. **화면은 이 경로를 쓰지 않는다** | 재현(`labeler1` 업로드 → 200 `text/html` inline, 정리함). `domain/gui.py:147-150`, `app/views/files/upload.py:40-101`, `app/views/__init__.py:63` | 경로 4개와 매핑을 지운다(쓰는 화면 없음). 남겨야 하면 관리자 메뉴 매핑 + 업로드 확장자 허용 목록 + `Content-Disposition: attachment` 고정 |
| 2 | 의존성 (T2) | **차단** | Django 5.0.4 — 5.0 계열 보안 지원 종료. 알려진 취약점 27건(QuerySet.values() SQL 주입 CVE-2024-42005 등) | `pip-audit -r requirements.txt` | **Django 5.2.17 이상(LTS, 2028-04 까지)**. 5.2 에서 27건 모두 해소. 5.1·5.2 하위 호환 변경 확인 + 전체 테스트 |
| 3 | XSS (T6) | **높음** | 공통 알림·확인창(`Alert.alert/confirm`)이 메시지를 이스케이프 없이 `.html()` 로 넣는다. 확인창 문구에 파일명·라벨 이름이 들어가 **작업자가 올린 파일명으로 관리자 화면에서 스크립트 실행** | 재현(파일명·라벨명 둘 다 `window.__xss=1`, E2E 데이터 정리됨). `common.js:706-711`·`861`·`884`. 같은 방식의 문자열 연결: `inspection.html:114-122`(검사항목명·Client ID)·`:187-192`(camera 등 클라이언트 값)·`model_mapping.html:80` | `_formatMessage` 에서 먼저 HTML 이스케이프 후 줄바꿈만 `<br>`. 옵션·표는 `$('<option>').text()` 로 |
| 4 | 인증 (T4) | **높음** | 로그인 잠금 키의 주소를 `X-Forwarded-For` **첫 값**(클라이언트가 정하는 값)에서 읽는다 → 값만 바꾸면 무한 대입. 또 실패 횟수가 `LocMemCache`(워커별)라 gunicorn 4워커면 4배 | 재현(같은 주소 5번째 LOCKED, XFF 바꾸면 8번 모두 통과). `domain/services/login_throttle.py:29-34`, `CACHES` 미설정 | nginx 가 넣는 `X-Real-IP`(또는 XFF 마지막 값)만 믿고, 실패 횟수는 공유 캐시(DB 캐시 테이블 등)에 |
| 5 | 성능·가용성 (T9) | **높음** | 큰 파일을 Django(sync 워커)가 직접 스트리밍 → `--timeout` 넘으면 워커가 죽어 **전송이 끊긴다**. 배포본 85MB·LGPL 소스 1GB·스냅샷 zip·이미지 원본. 받는 동안 워커 4개 중 하나를 붙잡는다 | 재현(timeout 30s 에서 85MB 중 37MB 후 `WORKER TIMEOUT`). 운영 120s 면 1GB 는 8.5MB/s 이상이어야 끝난다. `api_v1.py:590-620`, `files/media.py:26` | nginx `X-Accel-Redirect`(internal location)로 전송을 nginx 에 넘긴다(권한 확인은 Django 그대로) |
| 6 | 의존성 (T2) | **높음** | Pillow 10.3.0 알려진 취약점 17건. 사용자·클라이언트가 올린 이미지를 직접 연다 | `pip-audit` | Pillow 12.3 이상. 업로드·전처리·썸네일·Export 회귀 확인 |
| 7 | DB 성능 (T8) | **높음** | 라벨링 대기열이 검사항목의 **이미지 전부**를 주고 이미지마다 약 7쿼리(N+1). 클라이언트 검사 이미지가 자동으로 쌓이므로 금방 수천 장이 된다 | 재현(이미지 1장 17쿼리, 5장 45쿼리). `app/views/item/labeling.py:53-70`(ponytail 주석의 한계) | `detail_payload` 가 쓰는 작업·주석을 prefetch, 대기열 서버 페이징 |
| 8 | 입력 검증·계약 (T6·T11) | **높음** | 해상도만 거대한 작은 PNG(48KB, 4억 픽셀)를 Pillow 가 `DecompressionBombError` 로 거절하는데 이 예외를 잡지 않는다. 데이터 업로드는 500, `/api/v1/inspections` 는 `500 INTERNAL_ERROR retryable=true` → **계약 §6-6(422 `IMAGE_INVALID`) 위반, 클라이언트가 계속 재시도** | 데이터 업로드 재현(`ImageService._validate`), `/api/v1` 은 코드(`domain/services/vision/inspection.py:121-127` → `api_v1.py` dispatch except) | 두 곳에서 `Image.DecompressionBombError` 도 잡아 각각 400·422. `/api/v1` 에도 해상도 상한 |
| 9 | 메모리 (T9) | 보통 | Export 가 zip 전체를 `BytesIO` 에 만든 뒤 `getvalue()` 로 한 번 더 복사 → 워커 메모리가 zip 크기의 약 2배 | 코드 `domain/services/data/export/__init__.py:28-32` | 임시 파일(`tempfile.SpooledTemporaryFile`/디스크)에 쓰고 `File` 로 저장 |
| 10 | 웹 성능 (T9) | 보통 | 정적 파일 압축 없음·캐시 60초. 로그인 직후 13.5MB/94요청, 데이터 목록 한 화면 4.7MB. `vendor.min.js` 1.1MB·`wezongrid.js` 1MB·`xlsx` 0.9MB 를 탭마다. 셸이 쓰지 않는 apexcharts·jsvectormap(약 800KB)도 싣는다 | gunicorn(DEBUG=False) 실측 `Cache-Control: max-age=60`, `Content-Encoding` 없음. `index.html:237-242` | whitenoise `CompressedManifestStaticFilesStorage`(압축·해시·긴 캐시, 수동 `?v=` 도 필요 없어짐), 미사용 스크립트 제거, xlsx 는 [엑셀] 누를 때 |
| 11 | 의존성 (T2) | 보통 | `requests` 2.26.0(4건)·`urllib3` 1.26.20(7건) — 앱 코드는 쓰지 않는다(`scripts/send_inspections.py` 만). `sqlparse` 0.4.4(7건)는 Django 를 올리면 함께. `numpy`·`qrcode`·`six` 도 import 0 | `pip-audit`, `grep import` | 운영 requirements 에서 빼고(개발 스크립트용 분리), 나머지는 버전 갱신 |
| 12 | 의존성 (T2) | 보통 | jquery-validation 1.17.0(2017) — 1.19.x·1.20 에서 ReDoS·XSS 수정 | 파일 머리말 | 갱신하거나 쓰는 곳이 없으면 제거 |
| 13 | 설정 (T3) | 보통 | `DEBUG` 기본값이 `True` — `.env` 를 빠뜨리면 운영이 DEBUG + `ALLOWED_HOSTS='*'` 로 뜬다(가드는 DEBUG=False 일 때만) | `settings.py:23-33` | 기본값 `False`, 개발은 `.env` 에서 켠다 |
| 14 | 비밀 (T7) | 보통 | 원본 MES 의 DB 비밀번호 평문이 `docs/archive/01_CURRENT_STATE_ANALYSIS.md:232` 에 있다(git 이력 포함). **지금 이 프로젝트 DB 비밀번호와는 다르다**(값 비교만 함) | `git log -p` | 원본 MES 담당에게 그 비밀번호가 아직 쓰이는지 확인·교체. 문서 마스킹은 `docs/archive` 수정 금지 규칙과 충돌 — 결정 필요 |
| 15 | 인가 (T5) | 낮음·판단 | 검사 결과/이력은 메뉴 R 만으로 **모든 검사항목**의 목록·상세(검사항목명·Client ID·판정)가 보인다. 이미지는 검사항목 권한으로 403 | 재현(미배정 사용자 200, `/media/image` 403) | 의도(첫 화면)라면 수용. 아니면 배정 검사항목만 |
| 16 | 세션 (T4) | 낮음 | 브라우저를 닫으면 끝나지만 유휴 만료가 없다(현장 공용 PC). 로그아웃이 GET 이고, 로그인 기록 저장이 실패하면 `logout()` 이 실행되지 않는다 | `account.py:71`·`:96-126` | 유휴 만료(예: 8시간) 검토, `logout()` 을 try 밖으로 |
| 17 | 성능 (T9) | 낮음 | 썸네일·이미지 응답에 `Cache-Control`·`ETag` 가 없어 탭을 열 때마다 다시 받는다 | gunicorn 실측 | `Cache-Control: private, max-age=...` + `Last-Modified` |
| 18 | 설정 (T3) | 낮음 | `SECURE_BROWSER_XSS_FILTER`(Django 4.0 부터 무효), `django.contrib.admin`(URL 없음), CSP 없음(인라인 스크립트가 많아 수용) | `settings.py` | 정리 시 함께 |
| 19 | DB (T8) | 낮음 | 검사항목 관리 목록 N+1(항목당 약 7쿼리, 항목 수십 개라 영향 작음). DB 로그 테이블 보존정책 없음(`menu_use_log` 1만 건) | 재현 26쿼리/3항목 | 집계 annotate. 로그 테이블 보존 기간 |
| 20 | 운영 서버 (T10) | 대기 | 운영 서버가 아직 없다 — §9 목록·TLS·nginx·systemd·방화벽·백업 복구 리허설·감시·시간 동기화 | — | 서버를 세울 때 이 Task 를 그대로 진행. **워커 서비스가 실제로 떠 있는지** 꼭 확인(개발 서버에서 이 프로젝트 워커가 꺼져 있었다) |

### 처리 결과 (2026-10-07, 브랜치 `fix/predeploy-audit`)

1~8 은 사용자 결정으로 모두 고쳤다. 각 항목에 재현 테스트를 먼저 두고(RED) 고쳤다.

| # | 처리 | 커밋·검증 |
|---|---|---|
| 1 | `/api/files/*`·`common/attach_file` 삭제(+ `FilesView`·`FileService`·`serve_file`·`attach_path`). `attach_file` 테이블은 남김 | `2d3fb5f`. 개발 서버에서 같은 공격이 403 |
| 2 | Django 5.2.18(asgiref 3.8.1·sqlparse 0.6.0). `index_together` 12개 모델을 0014·0015 로 옮김 | `826e7e6`. pip-audit 에서 Django·sqlparse 0건, `check --deploy` W019 만 |
| 3 | `Alert`·`Notify` 를 글자로, 검사 이력 콤보·상세·모델 매핑 선택지를 `.text()` 로 | `b78caa3`. `tests/e2e/test_xss.py` |
| 4 | 같은 호스트 nginx 의 `X-Real-IP` 만 믿음, 실패 횟수는 파일 캐시 | `4ca00a4`. 개발 서버에서 XFF 를 바꿔도 5번째 잠금 |
| 5 | `FILE_ACCEL_REDIRECT` → `X-Accel-Redirect`(nginx internal location) | `a486980`. 헤더는 단위 테스트, **nginx 실전송은 운영 서버에서 확인**(이 머신에 nginx 없음, DEPLOYMENT §9) |
| 6 | Pillow 12.3.0. 첨부 삭제로 쓰지 않게 된 django-imagekit·pilkit·django-appconf 제거 | `826e7e6`. pip-audit 에서 Pillow 0건 |
| 7 | 대기열이 관계를 한 번에 읽음(prefetch), 관리자 여부 한 번 계산 | `75ce1a2`. 데모 45 → 14쿼리, 이미지 수와 무관(회귀 테스트) |
| 8 | `DecompressionBombError` 를 잡아 업로드는 거절 목록, `/api/v1` 은 422 `IMAGE_INVALID` | `bb06212`. 실행으로 500 retryable 확인 후 수정 |

### 후속 처리 (2026-10-07, 브랜치 `fix/audit-followup`, 계획 [2026-10-07-audit-followup.md](2026-10-07-audit-followup.md))

| # | 처리(사용자 결정) | 커밋 |
|---|---|---|
| 9 | Export zip 을 STORAGE_ROOT 아래 임시 파일에 만든다 | `e3d51b6` |
| 10 | 정적 파일 Manifest(해시·gzip·1년 immutable)·템플릿 `{% static %}`, 셸 미사용 JS 제거, 엑셀 라이브러리 지연 로드 | `5ecba8f`·`411495c` |
| 11 | `requirements-dev.txt` 분리 — 운영 requirements 취약점 0건 | `4bddb15` |
| 12 | jquery-validation 1.22.1(npm 공식 tarball 과 같음) | `65ba34a` |
| 13 | `DEBUG` 기본값 False | `4a222ac` |
| 14 | `docs/archive` 비밀번호 가림. 원본 MES 담당 교체 확인은 사용자 몫 | `f1f0da6` |
| 15 | 검사 이력은 모든 검사항목(수용, DECISIONS) | 문서 |
| 16 | 세션 유휴 8시간, 로그아웃 결함 수정(GET 유지) | `4a222ac` |
| 17 | 이미지 응답 `Last-Modified`·304 | `509607e` |
| 18 | 무효 설정·`admin` 앱 제거 | `4a222ac` |
| 19 | 검사항목 관리 N+1 묶음, DB 로그 보존(90일·365일) | `a8f1ce4`·`7c13389` |
| — | 라벨링 대기열 50장 페이징(결정 6 B), 임시 비밀번호 창, 품목단가 탭·팝업 모듈·벤더 정리, PostgreSQL 통합 테스트 설정(DB 대기) | `60a01c0`·`7467a5b`·`aa4cd54`·`61e07ee` |

### 양호로 확인된 것

- `check --deploy`(운영값) — `W019` 하나(의도). 응답 헤더 `X-Frame-Options: SAMEORIGIN`·`nosniff`·`Referrer-Policy`, `Server` 비움
- 로그인 없이 103경로 × GET/POST — 데이터가 열리는 곳 없음(`/error/`·`/logout/` 은 안내 화면)
- 미배정 사용자 — 데이터 API 5개·`/media/*` 6개 모두 403. R 권한 메뉴에 POST 403
- RLS — 정책 18테이블 모두 FORCE, 테넌트 밖 0건. DB 계정 superuser·BYPASSRLS 아님. 커넥션 100 중 약 17 사용
- SQL — 전부 바인딩(이어 붙인 곳 둘은 고정 함수명). bandit 고위험 0(경고 1건은 `count(*)` 감싸기 오탐)
- 그리드 엑셀 — `=` 로 시작하는 값도 문자열로 저장(수식 주입 없음)
- 배포물 경로 조작(`..`·인코딩·절대 경로·NUL) — 모두 404
- 업로드 — 확장자·MIME·Pillow verify·형식·해상도 상한(5천만) 검사(압축 폭탄 예외만 #8)
- `/api/v1` API Key — 32바이트 난수, SHA-256 해시 저장, `hmac.compare_digest`. 비밀번호 정책은 사용자·내 정보 화면 모두 적용
- 비밀 — 로그 파일·DB 시스템로그에 키·비밀번호 0건, 현행 비밀은 git 이력에 없음, 오류 응답에 트레이스·SQL·경로 없음(DEBUG=False)
- 인덱스 — 쌓이는 표의 목록 조건과 일치(검사 이력·이미지·주석·라벨링 작업·로그 3종)

### 점검이 남긴 것

- `static/`(collectstatic 결과 80MB, git 무시 대상)이 저장소 루트에 생겼다. 개발 서버에서 whitenoise 가 이 사본을 `app/static` 보다 먼저 낼 수 있으니 지운다(사용자 확인 후)
- 개발 DB: 점검용 사용자·첨부·E2E 검사항목은 모두 지웠다. 로그인 기록·시스템로그에 점검 흔적(실패 로그인 등)이 남아 있다

---

### Task 1: 기준선 — 지금 상태가 초록인지

**Files:** 읽기만 한다.

- [ ] **Step 1: 작업 트리와 마이그레이션 상태**

```bash
git status --short                                   # 기대: 빈 출력
.venv/bin/python manage.py makemigrations --check --dry-run   # 기대: No changes detected
.venv/bin/python manage.py migrate --check           # 기대: 종료 코드 0(미적용 없음)
```

- [ ] **Step 2: 테스트와 검사 스크립트 전부**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings   # 기대: OK (250건)
node scripts/verify_screen_js.js
for s in verify_menu verify_permission_map verify_response_keys verify_tokens verify_korean_only verify_links verify_naming verify_modals verify_buttons; do echo -n "$s: "; .venv/bin/python scripts/$s.py | tail -1; done
.venv/bin/python -m pytest tests/e2e -q              # 기대: 148 passed (약 12분, 서버 필요)
```

하나라도 실패하면 점검을 멈추고 발견 사항 1번으로 적는다(기준선이 깨진 상태의 점검은 의미가 없다).

---

### Task 2: 의존성·런타임 — 지원 기간과 알려진 취약점

**Files:** `requirements.txt`, `app/static/assets/js/vendor.min.js`, `app/static/assets/vendor/**`

- [ ] **Step 1: 프레임워크 지원 기간**

Django 5.0 은 2025-04 에 보안 지원이 끝났다(4.2 LTS 도 2026-04 종료). 현재 지원 중인 LTS 는 5.2(2028-04 까지)다.
<https://www.djangoproject.com/download/#supported-versions> 에서 오늘 기준을 다시 확인하고 적는다.
기대 결과: **차단** 후보 — "Django 5.0.4 → 5.2 LTS 업그레이드" (수정 작업은 별도. 5.1·5.2 의 하위 호환 변경 목록을 함께 적는다)

- [ ] **Step 2: Python 패키지 취약점 (임시 가상환경, 사용자 승인 후)**

```bash
python3 -m venv "$SCRATCH/audit-venv"
"$SCRATCH/audit-venv/bin/pip" install -q pip-audit
"$SCRATCH/audit-venv/bin/pip-audit" -r requirements.txt --desc
```

기대: 패키지별 CVE 목록. 특히 볼 것 — `sqlparse==0.4.4`, `requests==2.26.0`, `pillow==10.3.0`, `Django==5.0.4`. 각 CVE 를 "이 프로젝트가 그 기능을 쓰는가"로 나눠 등급을 매긴다.

- [ ] **Step 3: 화면 JS 라이브러리 버전**

```bash
grep -o "jQuery v[0-9.]*\|Bootstrap  *v[0-9.]*" app/static/assets/js/vendor.min.js | sort -u
grep -o 'version="[0-9.]*"' app/static/assets/vendor/xlsx/xlsx.full.min.js | head -1
ls app/static/assets/vendor/
```

지금 아는 값: jQuery 3.7.1, Bootstrap 5.3.6, SheetJS 0.20.3. 나머지(moment·daterangepicker·jquery-validation 1.17.0·JavaScript-Templates·ax5ui·bootstrap-maxlength 등)의 버전을 찾아 알려진 취약점과 대조한다. **실제로 화면이 싣는 것만** 등급을 매기고, 싣지 않는 벤더 파일은 "미사용 자산"으로 따로 적는다(STATUS 3-5 의 정리 항목과 합친다).

---

### Task 3: Django 운영 설정

**Files:** `configurations/settings.py`, `configurations/env.py`, `configurations/middleware/`

- [ ] **Step 1: 운영값으로 `check --deploy`**

```bash
DEBUG=False HTTPS_ENABLED=True ALLOWED_HOSTS=maip.example SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')" \
  .venv/bin/python manage.py check --deploy
```

기대: `security.W019` 하나(의도된 것). 그 밖의 경고는 전부 발견 사항이다.

- [ ] **Step 2: 설정 항목 검토** — `settings.py` 를 읽고 아래를 하나씩 확인해 적는다

| 항목 | 지금 | 볼 것 |
|---|---|---|
| `DEBUG` 기본값 | `True` | `.env` 를 빠뜨리면 운영이 DEBUG 로 뜬다. `ALLOWED_HOSTS`·`SECRET_KEY` 가드만으로 충분한지 |
| `SECURE_BROWSER_XSS_FILTER` | `True` | Django 4.0 에서 효과가 없어진 설정 — 정리 대상(낮음) |
| 세션 수명 | 기본(2주, `SESSION_COOKIE_AGE` 없음) | 현장 공용 PC 에서 2주 로그인 유지가 맞는지, `SESSION_EXPIRE_AT_BROWSER_CLOSE` |
| `CSRF_TRUSTED_ORIGINS` | 환경변수 | HTTPS 운영 주소가 들어가는지(빠지면 POST 가 403) |
| `CSRF_COOKIE_HTTPONLY` | 기본(False) | 화면 JS 가 쿠키에서 토큰을 읽는지 확인 후 판단 |
| `django.contrib.admin` | 설치됨, URL 없음 | 쓰지 않으면 앱 목록에서 빼도 되는지(낮음) |
| CSP 헤더 | 없음 | 인라인 스크립트가 많아 바로 넣기 어렵다 — 수용 여부를 적는다 |
| `FILE_UPLOAD_PERMISSIONS` | `0o640` | 서비스 계정·그룹 전제와 맞는지 |
| `CONN_MAX_AGE` | 60 | Task 8 의 커넥션 예산과 함께 본다 |

- [ ] **Step 3: 응답 헤더 실측** (개발 서버)

```bash
curl -sI http://127.0.0.1:8123/login/ | grep -iE "x-frame|x-content|referrer|set-cookie|server|cross-origin"
```

기대: `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, 세션 쿠키 `HttpOnly; SameSite=Lax`. `Server` 헤더에 버전이 새는지도 본다(`RemoveCriticalResponseHeader` 가 무엇을 지우는지 확인).

---

### Task 4: 인증·세션·CSRF

**Files:** `app/views/account.py`, `app/views/__init__.py`, `app/views/files/excel_export.py`, `app/views/api_v1.py`, `domain/services/login_throttle.py`

- [ ] **Step 1: `csrf_exempt` 전수 검토**

```bash
grep -rn "csrf_exempt" app domain configurations
```

지금 네 파일이다. 각 사용처마다 "왜 면제인가 · 세션 쿠키로 인증되는가"를 적는다. **세션으로 인증되는 쓰기 경로가 면제면 차단**이다(`/api/v1` 은 헤더 인증이라 면제가 맞다).

- [ ] **Step 2: 웹 로그인 보호**

- 같은 계정 5회 실패 → 300초 잠금이 실제로 걸리는지 개발 서버에서 확인(`E2E-` 계정을 만들어서). 잠금 중 응답 문구가 계정 존재 여부를 흘리지 않는지
- 로그인 성공 시 세션 키가 바뀌는지(세션 고정): 로그인 전후 `map` 쿠키 값 비교
- 로그아웃이 POST 인지 GET 인지(GET 이면 CSRF 로 강제 로그아웃 가능 — 낮음)
- 임시 비밀번호 흐름: STATUS 의 알려진 문제("사용자 화면이 임시 비밀번호를 안 보인다")와 비밀번호 정책(`AUTH_PASSWORD_VALIDATORS`)이 사용자 생성·변경 API 에서 실제로 적용되는지

- [ ] **Step 3: `/api/v1` 클라이언트 인증**

`app/views/api_v1.py` 와 클라이언트 인증 서비스를 읽고 확인한다.
- API Key 를 DB 에 **해시**로 두는가(평문이면 차단)
- 비교가 상수 시간(`hmac.compare_digest`·`check_password`)인가
- 비활성 클라이언트("사용" 해제)가 즉시 401 인가 — `curl` 로 확인
- 인증 실패 rate limit 없음 — 계약 §16 질문 4 의 결정 대기. **수용 또는 nginx `limit_req` 로 막을지** 적는다

---

### Task 5: 인가·데이터 격리

**Files:** `domain/gui.py`, `app/views/item/__init__.py`, `app/views/files/media.py`, `domain/migrations/0007_tenant_rls.py`

- [ ] **Step 1: 로그인 없이 모든 URL 찌르기** — scratchpad 스크립트

```python
# $SCRATCH/unauth_sweep.py — 개발 서버에 쿠키 없이 요청한다
import re, requests, django, os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configurations.settings')
django.setup()
from django.urls import get_resolver
from domain.gui import GUIConfiguration

BASE = 'http://127.0.0.1:8123'
ALLOW = {'/login/', '/api/alive', '/api/v1/health', '/api/v1/licenses/sources', '/api/v1/client-packages'}

def walk(patterns, prefix=''):
    for p in patterns:
        route = prefix + str(p.pattern)
        if hasattr(p, 'url_patterns'):
            yield from walk(p.url_patterns, route)
        else:
            yield '/' + re.sub(r'<[^>]+>', 'x', route).lstrip('^').rstrip('$')

paths = set(walk(get_resolver().url_patterns))
paths |= {f'/gui/{code}/' for code in GUIConfiguration.menu_init()}            # 화면 전부
paths |= {f'/api/{taskview}' for taskview in GUIConfiguration.taskview_menu_code_map()}  # MES API 매핑 전부
for path in sorted(paths):
    r = requests.get(BASE + path, allow_redirects=False, timeout=10)
    ok = r.status_code in (301, 302, 401, 403, 404) or path in ALLOW
    print(('OK  ' if ok else 'OPEN'), r.status_code, path)
```

(`taskview_menu_code_map()` 이 dict 를 돌려주는지 먼저 읽고 맞춘다 — `{'vision/client': ['wm_vis_client'], ...}` 모양이다.) 기대: `ALLOW` 밖은 전부 302(로그인)·401·403. **`OPEN` 이 하나라도 있으면 차단.**

- [ ] **Step 2: 검사항목 간 격리(IDOR)**

데모 계정 `labeler1`(검사항목 3·5 배정, 4 미배정 — 실제 배정은 화면에서 확인)로 로그인해, 배정되지 않은 검사항목의
- `/api/item/image?action=list&item_id=<미배정>` → 403
- 그 검사항목 이미지의 원본·썸네일 URL(`/media/image/...`, 관리자로 먼저 주소를 얻는다) → 403/404
- 스냅샷 zip 받기 URL(`/media/export/<id>/`) → 403/404
- `/api/item/item_home?action=update` (권한 없는 쓰기) → 403
를 확인한다. 하나라도 200 이면 **차단**.

- [ ] **Step 3: 메뉴 권한 R/W**

R 만 있는 그룹 사용자로 데이터 화면의 변경 action(POST)을 부르면 403 인지 — `scripts/verify_permission_map.py` 가 매핑만 보므로 실제 요청으로 2~3개 표본 확인.

- [ ] **Step 4: RLS 와 DB 계정**

```sql
-- 운영에 쓸 DB 계정으로 접속해서
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;       -- 기대: f, f
SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
 WHERE relname LIKE 'vision_data_%' AND relkind = 'r' ORDER BY 1;                         -- 기대: 18개 모두 t, t
SELECT count(*) FROM vision_data_imageasset;                                              -- 기대: 0 (테넌트 컨텍스트 없음)
```

개발 DB 계정이 superuser·BYPASSRLS 라면 "운영 계정은 따로 만든다"를 발견 사항으로 적는다.

---

### Task 6: 입력 검증·주입·파일

**Files:** `domain/services/**`(raw SQL), `app/templates/**`, `app/views/files/`, `app/views/api_v1.py`, `domain/services/data/image*.py`, `domain/services/data/export/`

- [ ] **Step 1: SQL 주입 — 문자열로 조립한 SQL 찾기**

```bash
grep -rnE "(execute|raw)\(\s*f['\"]|(execute|raw)\([^)]*%\s*\(|(execute|raw)\([^)]*\.format\(|sql\s*\+=\s*.*\+" app domain --include=*.py | grep -v migrations
grep -rnE "f\"\"\"|f'''" domain/services --include=*.py | head -50   # f-string 으로 만든 SQL 본문
```

찾은 것마다 끼워 넣는 값이 **사용자 입력에서 오는가**를 따라가 적는다. 사용자 입력이 그대로 들어가면 **차단**(파라미터 바인딩으로 고친다). 정렬 컬럼·테이블명처럼 바인딩이 안 되는 자리는 허용 목록 검사가 있는지 본다.

- [ ] **Step 2: XSS — 화면에 HTML 로 넣는 곳**

```bash
grep -rn "|safe\|mark_safe\|format_html" app --include=*.html --include=*.py
grep -rn "{%#" app/templates                                  # JavaScript-Templates 의 이스케이프 없는 출력
grep -rnE "\.html\(|innerHTML|type: 'html'" app/templates app/static/assets/js/common.js app/static/assets/js/grid.js | grep -v "\.html('')" 
```

그리드 `renderer: { type: 'html', template }` 가 **사용자가 정한 문자열**(파일명·라벨 이름·클라이언트 이름·검사항목명·메뉴명·사용자 이름)을 이스케이프 없이 붙이는 곳을 찾는다. 확인 방법: `E2E-<img src=x onerror=alert(1)>` 이름의 검사항목·라벨·파일을 만들어 각 화면을 열고 `page.on('dialog')` 로 alert 이 뜨는지 본다(끝나면 지운다). 뜨면 **높음**.

- [ ] **Step 3: 경로 조작**

- `/api/v1/client-packages/<filename>`·`/api/v1/licenses/sources/<filename>`: `..%2F..%2Fsettings.py`, `%2e%2e`, 절대 경로, 심볼릭 링크 → 404 인지 `curl` 로
- `/api/files/<view_name>`(`app/views/files/__init__.py`): 무엇을 열어 주는지 읽고, `view_name` 이 파일 경로로 이어지는지
- 업로드 원본 이름(`original_name`)이 저장 경로에 쓰이지 않는지(저장 키는 UUID 인지) — `ImageAsset.storage_key` 생성부
- 스냅샷 zip 안 경로가 `images/<sha256>.jpg` 처럼 서버가 만든 이름뿐인지(오늘 받은 v1.0 zip 이 그렇다 — 다른 형식 7종도 확인)

- [ ] **Step 4: 업로드 검증**

- 확장자만 바꾼 파일(`.png` 이름의 텍스트·zip)이 Pillow 검증에서 거절되는지(화면 업로드·`/api/v1/inspections`·대표 이미지·Overlay 네 경로)
- 압축 폭탄: 20000×20000 단색 PNG(파일은 작다)를 올려 `Image.MAX_IMAGE_PIXELS` 경고/거절이 나는지, 서버 메모리가 튀지 않는지
- 크기 한도: 30MB+1 바이트 → 거절 문구

- [ ] **Step 5: 엑셀 수식 주입**

`=HYPERLINK("http://x","y")` 로 시작하는 이름(검사항목명·파일명)을 만든 뒤 그리드 [엑셀]로 받아 셀이 수식으로 들어가는지 확인(`openpyxl` 로 열어 `cell.data_type == 'f'`). 수식이면 **보통**(앞에 `'` 를 붙이는 처리 제안).

---

### Task 7: 비밀·로그·오류 노출

**Files:** git 이력, `configurations/log.py`, `storage/logs/`, `domain/management/commands/seed_demo.py`

- [ ] **Step 1: 이력 속 비밀**

```bash
git log -p --all | grep -nE "(SECRET_KEY|PASSWORD|API_KEY|apikey|token)\s*[=:]\s*['\"][^'\"]{8,}" | grep -v "dev-insecure\|placeholder\|<" | head
git log --all --diff-filter=A --name-only --format= | grep -E "\.env$|\.admin_pw|\.demo_pw|\.demo_apikey|\.pem$|\.key$" | sort -u
```

기대: 둘 다 빈 출력. 나오면 그 비밀은 **유출로 보고 교체**(차단).

- [ ] **Step 2: 로그 속 비밀**

```bash
grep -rnE "X-API-Key|api_key|password" storage/logs/*.log | grep -vE "\*{4}|masked" | head
```

`/api/v1` 인증 실패·클라이언트 재발급·사용자 비밀번호 변경을 한 번씩 일으킨 뒤 다시 본다. 원문이 있으면 **높음**.

- [ ] **Step 3: 오류 응답**

DB 오류·예외를 일부러 일으켜(`/api/item/image?action=detail&item_id=3&image_id=abc` 등) 응답 본문에 트레이스·SQL·경로가 없는지 확인. DEBUG=False 로 띄운 임시 서버(Task 9 Step 3 의 gunicorn)에서 500 페이지도 본다.

- [ ] **Step 4: 개발 흔적**

운영 반입본에 `.admin_pw`·`.demo_pw`·`.demo_apikey`·`tmp/`·`storage/` 가 섞이지 않게 하는 방법이 DEPLOYMENT §9 에 있는지(지금은 "지운다" 한 줄). `git archive` 로 반입본을 만들면 무시 목록이 자동으로 빠진다 — 반입 절차 제안으로 적는다.

---

### Task 8: DB 성능·커넥션

**Files:** `app/views/item/*.py`, `app/views/vision/*.py`, `domain/services/**`

- [ ] **Step 1: API 별 쿼리 수 (N+1)** — 개발 DB, scratchpad 스크립트

```python
# $SCRATCH/query_count.py — manage.py shell < 이 파일
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

c = Client(); c.force_login(get_user_model().objects.get(username='admin'))
H = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
URLS = [
    '/api/item/image?action=list&item_id=3&page=1&page_size=20',
    '/api/item/item_home?action=detail&item_id=3',
    '/api/item/review?action=list&item_id=3',
    '/api/item/snapshot?action=list&item_id=3',
    '/api/item/labeling?action=queue&item_id=3',
    '/api/item/item_admin?action=list',
    '/api/vision/inspection?action=list&page=1&page_size=20',
    '/api/vision/client?action=list',
    '/api/vision/overlay?action=list',
    '/api/vision/model_mapping?action=list',
]
for url in URLS:
    with CaptureQueriesContext(connection) as q:
        r = c.get(url, **H)
    print(r.status_code, len(q.captured_queries), url)
```

행 수를 늘려도(예: 이미지 20 → 데모 5) **쿼리 수가 행 수에 비례하면 N+1** — 보통 이상.

- [ ] **Step 2: 쌓이는 표의 인덱스**

쌓이기만 하는 표: `vision_inspection`·`vision_data_imageasset`·`vision_data_annotation`·로그 3종(로그인·메뉴·시스템). 각 목록 화면의 WHERE/ORDER BY 를 읽고 맞는 인덱스가 있는지 `\d <table>` 로 대조한다. 검사 이력은 `0012` 로 해결됐다. 개발 DB 행이 적어 `EXPLAIN` 이 늘 Seq Scan 이므로, 인덱스 존재 여부와 조건 컬럼 일치만 본다.

- [ ] **Step 3: 커넥션 예산**

공유 PostgreSQL 의 `max_connections` 와 지금 사용량:

```sql
SHOW max_connections;
SELECT datname, application_name, count(*) FROM pg_stat_activity GROUP BY 1,2 ORDER BY 3 DESC;
```

운영 계산: gunicorn 워커 4 × 스레드 1 × `CONN_MAX_AGE` 지속 커넥션 + 워커 2 + 관리 작업 여유. 다른 프로젝트 몫과 합쳐 넘지 않는지 적는다(DEVELOPMENT §5.2).

---

### Task 9: 웹 성능·정적 파일·큰 파일 전송

**Files:** `configurations/settings.py`(정적), `app/templates/app/layout_page.html`, `app/views/api_v1.py:590-620`, `app/views/files/media.py`

- [ ] **Step 1: 화면 하나가 받는 양**

```bash
.venv/bin/python - <<'EOF'
from playwright.sync_api import sync_playwright
import pathlib
pw = pathlib.Path('.admin_pw').read_text().strip()
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto('http://127.0.0.1:8123/login/'); pg.fill('#loginId','admin'); pg.fill('#loginPwd',pw); pg.click('#login'); pg.wait_for_url('http://127.0.0.1:8123/')
    sizes = []
    pg.on('response', lambda r: sizes.append((len(r.body()) if r.ok else 0, r.url.split('?')[0])))
    pg.goto('http://127.0.0.1:8123/gui/wm_data_image/?project=3', wait_until='networkidle')
    print(sum(s for s, _ in sizes) // 1024, 'KB'); [print(s // 1024, 'KB', u) for s, u in sorted(sizes, reverse=True)[:8]]
    b.close()
EOF
```

알려진 것: `vendor.min.js` 1.1MB + `xlsx.full.min.js` 0.95MB 를 **모든 화면(iframe 탭마다)** 싣는다. 엑셀을 누를 때만 xlsx 를 싣는 방안을 제안 후보로 적는다.

- [ ] **Step 2: 정적 파일 캐시·압축**

```bash
curl -sI http://127.0.0.1:8123/static/assets/js/vendor.min.js | grep -iE "cache-control|content-encoding|etag"
curl -sI -H "Accept-Encoding: gzip, br" http://127.0.0.1:8123/static/assets/js/vendor.min.js | grep -i content-encoding
```

개발 서버는 runserver 가 정적 파일을 내므로 운영과 다르다 — Step 3 의 gunicorn 으로 다시 본다. `STORAGES`(whitenoise `CompressedManifestStaticFilesStorage`)가 없어 압축본·해시 이름·긴 캐시가 없을 것으로 예상한다. 맞으면 **보통**(수동 `?v=` 관리도 함께 없어진다 — DEVELOPMENT §5.19).

- [ ] **Step 3: 운영과 같은 방식으로 띄워 보기** (개발 머신, 포트 8002, 끝나면 종료)

```bash
DEBUG=False ALLOWED_HOSTS=127.0.0.1 SECRET_KEY=audit-only-$(date +%s) DB_CONN_MAX_AGE=0 \
  .venv/bin/python manage.py collectstatic --noinput -v0 && \
DEBUG=False ALLOWED_HOSTS=127.0.0.1 SECRET_KEY=audit-only-$(date +%s) DB_CONN_MAX_AGE=0 \
  .venv/bin/gunicorn configurations.wsgi:application --bind 127.0.0.1:8002 --workers 2 --timeout 30 &
```

(`collectstatic` 은 무시 목록인 `/static/` 에 쓴다 — 저장소를 더럽히지 않는다.) 여기서 Step 2 의 헤더를 다시 보고, Task 7 Step 3 의 500 응답도 본다.

- [ ] **Step 4: 큰 파일 전송이 워커 타임아웃에 걸리는가**

gunicorn sync 워커는 응답을 쓰는 동안 하트비트를 보내지 못해 `--timeout` 을 넘기면 죽을 수 있다. 배포본(85MB)·LGPL 소스(1GB)는 Django 가 직접 스트리밍한다(`api_v1.py` `StreamingHttpResponse`).

```bash
curl -s -o /dev/null -w "%{http_code} %{size_download} %{time_total}\n" --limit-rate 1M \
  http://127.0.0.1:8002/api/v1/client-packages/VisionInspectionClient-0.1.6-beta-20261006.zip
```

`--timeout 30` 에서 85MB 를 1MB/s 로 받으면 약 85초다. 끊기면(받은 크기 < 85MB) **높음** — 운영 `--timeout 120` 에서도 느린 현장망이면 끊긴다. 제안 후보: nginx `X-Accel-Redirect`(internal location)로 파일 전송을 nginx 에 넘기기. 같은 문제가 이미지 원본(`media.py` `FileResponse`)에도 있는지 크기로 판단한다.

- [ ] **Step 5: 이미지·썸네일 비용**

데이터 목록 20행을 열 때 썸네일 요청이 매번 원본을 다시 줄이는지(imagekit 캐시 파일이 생기는지 `storage/media/CACHE` 확인), 응답에 `Cache-Control`/`ETag` 가 있어 탭을 다시 열 때 재전송을 피하는지 본다.

- [ ] **Step 6: 워커 처리량**

`run_worker --interval 5` 가 Export 하나를 처리하는 시간(오늘 v1.0 은 이미지 2장)과, 이미지 수천 장일 때의 메모리(zip 을 메모리에 모으는지 디스크에 쓰는지)를 `domain/services/data/export/` 에서 읽어 적는다.

---

### Task 10: 운영 서버 구성 (서버가 선 뒤, 읽기·확인만)

**Files:** `docs/DEPLOYMENT.md` §1~§9 를 그대로 대조한다. 서버가 아직 없으면 이 Task 는 "대기"로 적고 넘어간다.

- [ ] **Step 1: DEPLOYMENT §9 "올리기 전" 목록을 한 줄씩 실행해 체크**(`.env` 권한 600, DB 계정 비superuser, `seed_demo` 미실행, 개발 흔적 파일 없음, 웹·워커 두 서비스 `active`, health 200 …)
- [ ] **Step 2: TLS** — `openssl s_client -connect <주소>:443 -servername <이름>` 로 인증서 체인·SAN(IP 접속이면 IP)·만료일, TLS 1.2 미만 거절. 평문 80 이 301 로 가는지(계약 §10-4: `licenses/sources` 경로는 리다이렉트를 남긴다)
- [ ] **Step 3: nginx** — `client_max_body_size`, 프록시 타임아웃(`proxy_read_timeout`)이 Task 9 Step 4 와 맞는지, `add_header X-Frame-Options DENY` 가 **없는지**, `/media/`·`STORAGE_ROOT` alias 가 **없는지**, `server_tokens off`
- [ ] **Step 4: systemd** — 서비스 계정 `maip`(로그인 셸 없음), `Restart=on-failure`, 워커 서비스가 실제로 떠 있는지(오늘 개발 서버에서 이 프로젝트 워커가 꺼져 있었고 다른 프로젝트 워커만 떠 있었다 — 같은 실수 방지)
- [ ] **Step 5: 방화벽** — 인증 없는 배포물 경로 때문에 내부망만 연다(`ufw status` / 보안그룹)
- [ ] **Step 6: 백업·복구 리허설** — DB 덤프 + `STORAGE_ROOT` + `DISTRIBUTION_ROOT` 를 받아 **다른 곳에 실제로 복구**해 로그인·이미지 표시까지 확인(백업만 있고 복구를 안 해 본 것은 백업이 아니다)
- [ ] **Step 7: 감시** — 디스크(이미지 보존정책 없음)·서비스 다운·health 실패를 누가 어떻게 알게 되는지. 없으면 **높음**
- [ ] **Step 8: 시간·시간대** — `USE_TZ=False`·`Asia/Seoul` 전제. 서버 시간대와 NTP 동기화(검사 시각·로그 날짜가 어긋나지 않게)

---

### Task 11: 클라이언트 계약 회귀

**Files:** `docs/client/SERVER_API_CONTRACT.md`, `tests/e2e/test_client_workflow.py`, `tests/test_api_v1*.py`

- [ ] **Step 1:** `test_client_workflow` 와 `/api/v1` 단위 테스트가 Task 1 에서 통과했는지 확인
- [ ] **Step 2:** 계약 §13(보안)·§16(확인 필요) 항목을 지금 구현과 대조 — 문서와 다른 동작이 있으면 **높음**(알리지 않고 바꾸면 현장 검사가 멈춘다, DEC-C2)
- [ ] **Step 3:** 운영 전환 때 API Key 전량 재발급 절차(STATUS 3-1)가 문서에 있고, 클라이언트에 새 Key 를 전달하는 경로가 정해졌는지

---

### Task 12: 결과 정리

**Files:**
- Modify: `docs/superpowers/plans/2026-10-07-predeploy-audit.md`(이 문서의 "발견 사항" 표)
- Modify: `docs/STATUS.md` §3(남은 일), `docs/DEPLOYMENT.md` §9(점검 목록에 새로 생긴 확인 항목)

- [ ] **Step 1:** 발견 사항 표를 등급순으로 정렬하고 항목마다 "제안"을 한 줄로 쓴다
- [ ] **Step 2:** 사용자에게 표를 보이고 항목별로 **고침 / 수용 / 보류**를 받는다
- [ ] **Step 3:** 수용·보류는 STATUS §2(알려진 제약)로, 고침은 STATUS §3 우선순위 표로 옮긴다. 반복해서 확인할 것은 DEPLOYMENT §9 에 한 줄로 더한다
- [ ] **Step 4:** 커밋

```bash
git add docs/superpowers/plans/2026-10-07-predeploy-audit.md docs/STATUS.md docs/DEPLOYMENT.md
git commit -m "docs: 배포 전 점검 결과와 후속 작업을 정리한다"
```
