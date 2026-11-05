# 개발 가이드

개발 환경을 띄우고, 테스트와 검증 스크립트를 돌리고, 자주 빠지는 함정을 피하는 법을 적는다.
구조와 API 규약은 [ARCHITECTURE.md](ARCHITECTURE.md), 운영 배포는 [DEPLOYMENT.md](DEPLOYMENT.md),
테이블·마이그레이션·시드는 [DATA_MODEL.md](DATA_MODEL.md), 화면 규칙은 [DESIGN.md](../DESIGN.md) 가 맡는다.

## 1. 개발 환경

### 1.1 준비

| 항목 | 값 |
|---|---|
| Python | 3.12 (`.venv`) |
| DB | PostgreSQL 16. 다른 프로젝트와 공유한다(§5.2) |
| 런타임 의존성 | `requirements.txt` |
| 검증 전용 의존성 | `requirements-dev.txt`(`pytest`·`playwright`·`requests`) — 운영 `requirements.txt` 에 없다. `openpyxl` 은 인터페이스 수신이 쓰므로 운영 의존성이다 |
| Node | `scripts/verify/verify_screen_js.js` 에만 쓴다 |

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
```

### 1.2 `.env`

`.env.example` 을 복사해 `.env` 를 만든다. `configurations/env.py` 가 프로젝트 루트의 `.env` 를
읽어 **셸에 없는 환경변수만** 채운다 — 셸에서 지정한 값이 이긴다. `.env` 는 커밋하지 않는다.

개발에서 정하거나 확인할 것만 적는다.

| 키 | 개발 값 | 이유 |
|---|---|---|
| `DB_CONN_MAX_AGE` | **`0`** | `runserver` 에서 커넥션이 샌다(§5.1). 예시 파일과 `settings.py` 기본값은 운영용 `60` 이다 |
| `DB_HOST`·`DB_NAME`·`DB_USER`·`DB_PASSWORD` | 개발 DB | 우리 DB 이름은 `yest` |
| `DEBUG` | `True` | |
| `STORAGE_ROOT` | 비움 | 비우면 저장소의 `storage/` 를 쓴다. 로그도 `storage/logs` 로 간다 |
| `API_AUTHZ_MODE` | `enforce` | 운영과 같게 둔다. `off`·`warn` 으로 두면 권한 매핑 누락을 놓친다 |
| `TENANT_RLS_ENABLED` | `True` | 운영과 같게 둔다 |
| `WEZARD_BASE_URL`·`WEZARD_API_KEY` | 개발 Wezard 주소·발급받은 키 | 비우면 추론이 Stub 이다(§5.12). `sample_inspection` 은 이것이 있어야 판정한다 |
| `WERAG_URL` | `http://10.10.10.109/` | 상단 바 We.RAG 로고의 주소. 비우면 로고가 보이지 않는다 |

키 전체 설명은 DEPLOYMENT.md 에 있다.

### 1.3 띄우기

근거: DECISIONS DEC-C7.

> **공유 개발 DB 를 쓰는 팀원은 `migrate`·`seed_*` 를 건너뛰고 서버만 띄운다** — DB 준비는 담당자 몫이다.

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_initial --admin-password '<비밀번호>'
.venv/bin/python manage.py seed_vision_items            # 검사 분류와 NEOCON C2 비전검사항목 16개. 멱등(없는 것만)
.venv/bin/python manage.py seed_dig_form                # 고객 양식 15종(디지털 양식)·비전 연결·분류 매핑. 멱등
.venv/bin/python manage.py seed_demo                    # 개발 전용 표본(표본 zip 의 이미지까지)
.venv/bin/python manage.py seed_demo --samples           # 선택. 이미지 표본만 다시 넣는다(검사 기록이 있으면 --force)
.venv/bin/python manage.py runserver                    # 기본 127.0.0.1:8123(domain/management/commands/runserver.py). 다른 PC 에서 열려면 0.0.0.0:8123
.venv/bin/python manage.py run_worker                   # 별도 터미널
```

| 명령 | 하는 일 |
|---|---|
| `seed_initial` | 사용자 그룹·메뉴·항목결과 코드 기본값·조직(YEST)·관리자 계정. 멱등이다. `--admin-password` 를 빼면 관리자 계정을 만들지 않는다. 메뉴를 고쳤으면 **다시 돌린다** |
| `seed_demo` | 개발 표본(냉각팬 패널 비전검사항목 3종·`CLIENT-001`·표본 이미지 — 작업자 계정은 만들지 않는다). **운영 DB 에서 돌리지 않는다**. 이미지만 다시 넣을 때는 `--samples`. id 는 DB 마다 달라 e2e(`tests/e2e/conftest.py` `demo`)·화면 검증 스크립트(`scripts/verify/demo_item.py`)는 코드로 찾는다 |
| `sample_inspection` | 표본 결함·정상 이미지를 시험 클라이언트 `PIPELINE-TEST` 로 `POST /api/v1/inspections` 에 보내 파일마다 정답·판정·점수를 찍는다(`--item`·`--defect`·`--normal`·`--seed`). 프로세스 안에서 부르므로 서버는 필요 없고, 모델 매핑과 Wezard 설정은 필요하다. 검사 기록·이미지가 남는다. `SUCCESS` 가 아닌 검사가 있으면 종료 코드 1이다. 표본이 학습에 쓴 이미지라 맞힌 비율은 모델 평가가 아니다 |
| `seed_vision_items` | 검사 분류(고정 대분류 수입검사·품질검사·미분류 + 중분류)와 NEOCON C2 비전검사항목 16개·라벨 클래스·측정점. 운영에서도 돈다. `--update-descriptions` 를 주면 검사항목·측정점 설명만 이 명령의 내용으로 바꾼다. 없는 것만 만들고 화면에서 고친 값은 덮지 않는다 |
| `seed_dig_form` | 완성된 고객 양식 DF0012~DF0026 15종(검사 분류에 매핑된 양식 포함)의 최신 버전·참고사진·고정 이미지 칸 그림. 이미지 칸을 비전검사항목 코드로 잇고 이름이 같은 중분류에 매핑한다. `seed_vision_items` 다음에 돌린다(없으면 잇지 않고 알린다). 운영에서도 돈다. 같은 양식코드·버전이 있으면 건너뛴다 |
| `export_dig_form` | **담당자 전용.** 아래 "고객 양식 뽑기" |
| `import_interface` | 외부 인터페이스 엑셀(xlsx)을 수신 테이블(`if_*`)에 원본 그대로 넣는다 — `plm_part_bom`(PLM 품목·BOM)·`erp_purchase_req`(ERP 구매요청). 읽지 못하거나 머리글이 다르면 수신 실패로 남긴다. 공유 개발 DB 에는 `if_*` 테이블만 쓴다 |
| `apply_interface` | 수신건을 마스터에 반영한다 — PLM 품목·BOM 은 품목(`mst_product`)·BOM(`mst_bom`), ERP 구매요청은 입고(`mst_receipt`). 다시 돌려도 결과가 같고, 검증이 틀리면 아무것도 바꾸지 않는다. 마지막 반영 결과(상태·건수 또는 사유)가 수신건에 남는다 |
| `run_worker` | 스냅샷 Export(zip)·DB 로그와 만료 세션 보존 정리. 띄우지 않으면 버튼은 눌리지만 작업이 대기로 남는다. e2e 는 공유 개발 DB 에서 `--once` 를 부른다 |

검증 스크립트와 e2e 는 주소 `http://127.0.0.1:8123` 을 전제로 한다. 포트를 바꾸지 않는다.

**고객 양식 뽑기(`export_dig_form`).** **담당자 전용.** 이 서버 DB(공유 개발 DB)에서 **중분류에 매핑된 양식의 최신 버전**을
`seed_dig_form` 데이터 파일과 참고사진 폴더(`dig_form_images/`, 파일 옆)로 뽑는다. 매핑한 양식을 공유 개발 DB 에서 고쳤으면 다시 뽑아 둘 다 커밋한다.

- DB 는 읽기만 한다. 양식 정의(섹션·칸·작업분류)만 뽑고 id·작성자·작성 결과는 뺀다
- 이미지 칸의 비전검사항목 연결은 항목 코드로, 매핑한 중분류는 이름으로 뽑는다(id 는 환경마다 다르다)
- 참고사진은 파일까지 뽑는다. 파일이 이 서버 저장소에 없는 사진은 본문에서 빼고 알린다 — 그 양식을 다시 저장하거나 파일을 받은 뒤 다시 뽑는다
- 고정 이미지 칸에 그림이 든 양식은 거절한다

```bash
python manage.py export_dig_form domain/management/samples/dig_form_forms.json
```

**다른 PC 에서 열기.** `127.0.0.1` 로 띄우면 그 PC 안에서만 열린다. `runserver 0.0.0.0:8123`(`maipctl.py` 는 `start --addr 0.0.0.0:8123`)으로 띄우고
`http://<서버 IP>:8123/` 로 연다. 그 IP 가 `.env` 의 `ALLOWED_HOSTS` 에 있어야 하고(없으면 400), 방화벽이 8123 을
막지 않아야 한다(`sudo ufw status`). `:8123` 은 TLS 없는 개발 서버라 내부망에서만 쓴다.

**띄우기·끄기 도구.** `scripts/maipctl.py start|stop|status|restart [web|worker|all] [--foreground]` 가 웹·워커를 백그라운드로
띄우고 끈다. 이 저장소에서 도는 `manage.py runserver`·`run_worker` 만 다룬다.

**끄기.** 터미널에서 띄웠으면 `Ctrl+C`. 백그라운드는 손으로 띄웠어도 `scripts/maipctl.py stop` 으로 끈다(작업 폴더가 이 저장소인 프로세스만 찾는다).

**정적 파일 캐시.** 개발 서버는 CSS·JS 에 `Cache-Control: no-cache` 를 붙인다(파일 이름에 해시가 없어 옛 CSS 를 쓰지 않게).
그래도 새 CSS 가 안 보이면 한 번 강력 새로고침(`Ctrl+Shift+R`)한다.

### 1.4 검증용 비밀번호 파일

e2e 와 화면 검증 스크립트는 저장소 루트의 다음 파일에서 비밀번호를 읽는다. 시드가 만들어 주지 않는다 —
시드에 준 비밀번호를 직접 적어 둔다. `.gitignore` 에 있다. 관리자가 아닌 작업자로 보는 e2e 는
테스트가 `e2e-worker` 계정·그룹을 만들고 끝나면 지운다(`tests/e2e/conftest.py` `worker`).

| 파일 | 내용 | 환경변수로 대신하기 |
|---|---|---|
| `.admin_pw` | `admin` 비밀번호 | `E2E_ADMIN_PASSWORD` (e2e 만) |

운영 서버에는 두지 않는다.

## 2. 테스트

평소에는 고친 범위의 모듈·파일만 돌린다. 전체 단위(`tests`)·전체 e2e 는 사용자 승인을 받고 돌린다.

### 2.1 단위 테스트

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
```

**`--settings=configurations.test_settings` 를 빼지 않는다.** 빼면 `.env` 의 PostgreSQL 에 테스트 DB 가 생긴다.

`configurations/test_settings.py` 가 바꾸는 것:

| 항목 | 값 | 뜻 |
|---|---|---|
| DB | SQLite `:memory:` | 운영 DB 를 건드리지 않는다 |
| `STORAGE_ROOT` | `tempfile.mkdtemp(prefix='map-test-')` | 업로드·임시·양식 경로를 임시 폴더로 |
| `MEDIA_ROOT` | `STORAGE_ROOT/media` 로 **다시 지정** | `settings.py` 가 이미 계산한 값이라 따로 덮어야 한다. 빼면 테스트가 실제 `storage/media/` 에 이미지·썸네일을 쌓는다 |
| `CACHES` | locmem | `settings.py` 의 `STORAGE_ROOT/cache` 파일 캐시를 쓰지 않는다 |
| `STORAGES` | staticfiles 를 manifest 없는 저장소로 | collectstatic 없이 템플릿을 그린다 |
| `TENANT_RLS_ENABLED` | `False` | SQLite 에는 RLS 가 없다 |
| `API_AUTHZ_MODE` | `enforce` | 운영과 같은 인가 |
| `WEZARD_BASE_URL`·`WEZARD_API_KEY` | 빈 값 | `.env` 의 Wezard 로 실제 요청이 나가지 않는다. 추론은 Stub 이다 |
| `WERAG_URL` | 빈 값 | `.env` 의 We.RAG 주소가 화면 테스트에 섞이지 않는다(로고는 테스트가 값을 줄 때만) |
| `LOGGING` | NullHandler | 테스트는 로그를 남기지 않는다 |

`settings.py` 에 `STORAGE_ROOT` 에서 파생되는 경로를 새로 더하면 `test_settings.py` 에서도 다시 지정한다.
`MEDIA_ROOT` 와 같은 누출이 생긴다.

SQLite 라서 못 보는 것(RLS·raw SQL)은 §2.1-1.

### 2.1-1 PostgreSQL 통합 테스트 (RLS·raw SQL)

단위 테스트(SQLite)는 RLS 와 PostgreSQL 전용 raw SQL(`to_char`·`fn_code_name` 같은 함수 포함)을 보지 못한다. 그중
RLS(테넌트 밖 0건·FORCE 14테이블), 메뉴 트리 재귀 SQL(`domain/services/system.py` 의 `with recursive`·`v_menu_folder`), 디지털 양식 조회 SQL·양식코드 시퀀스, 로그인·메뉴 로그 SQL, 사용자 목록 SQL(소속 부서) 을 실제 PostgreSQL 에서 본다(`tests/pg/`).

```bash
.venv/bin/python manage.py test tests.pg --settings=configurations.pg_test_settings --keepdb
```

- DB 는 **DBA 가 미리 만든 `maip_test`** 다(소유자 = `.env` 의 `DB_USER`). 이 계정은 DB 생성 권한이 없어, 없으면
  "permission denied to create database" 로 멈춘다. `--keepdb` 로 다시 쓰며 처음 한 번 마이그레이션을 적용한다
- `PG_TEST_DB_NAME` 이 `maip_test` 가 아니면 설정이 부팅을 거부한다(운영 DB 를 테스트로 쓰지 않게)
- 단위 테스트(`test_settings`, SQLite)에서는 `tests/pg` 를 통째로 건너뛴다(skip 1)
- 계정이 superuser·`BYPASSRLS` 이면 "테넌트 밖 0건" 이 실패한다 — PostgreSQL 이 FORCE RLS 도 건너뛴다. 운영과 같은 일반 계정으로 돌린다
- "테넌트 밖 0건" 은 `TransactionTestCase` 다. 요청처럼 `tenant_atomic` 이 가장 바깥 트랜잭션이어야 `SET LOCAL app.tenant_id` 가
  끝에 사라진다(`TestCase` 는 테스트 전체를 감싸 값이 남는다). 끝나면 `maip_test` 의 표를 비운다

### 2.2 e2e (Playwright)

```bash
# 서버를 먼저 띄운다. DB 에 seed_demo 표본이 있어야 한다(공유 개발 DB 는 담당자가 넣어 둔다)
.venv/bin/python -m pytest tests/e2e -q
```

| 항목 | 내용 |
|---|---|
| 대상 | 떠 있는 서버(`E2E_BASE_URL`, 기본 `http://127.0.0.1:8123`). Django 테스트 러너가 아니다 |
| 규모 | `tests/e2e/test_*.py`. 전체 약 15분 |
| 브라우저 | Chromium headless. `E2E_HEADED=1` 이면 창을 띄운다 |
| 콘솔 오류 | `page` 픽스처가 `pageerror`·콘솔 `error` 를 `page.console_errors` 에 모은다 |

**e2e 는 실제 DB 에 쓴다.** 개발·검증 DB 에서만 돌린다. 쓰기 테스트의 규칙:

- 테스트는 `E2E-`·`e2e-` 로 시작하는 **자기 데이터만** 만든다.
- 만든 것은 `finally` 나 픽스처 정리로 지운다. 단언이 실패해도 지운다.
- seed 데이터를 바꾸면 같은 테스트 안에서 되돌린다.
- seed_demo 비전검사항목 id 를 적어 넣지 않는다. `demo` 픽스처가 코드로 찾은 id 를 준다(`'wm_data_image/?inspection_item={ano}'.format(**demo)`).
  개발 DB 에 남은 검사 기록에 기대지 않는다 — 필요하면 `inspection` 픽스처가 `E2E-INSP-` 클라이언트·비전검사항목으로 한 건 보내고 끝나면 지운다.
- "확인창을 거치는가"처럼 **요청이 나가면 안 되는 것**을 보는 테스트는 쓰기 요청을
  `page.route('**/api/**', ...)` 로 끊는다(GET 만 통과, `test_crud.py`). 끊지 않으면 회귀가 생겼을 때 그 테스트가 실제로 지운다.
  끊은 경로는 같은 페이지의 픽스처 정리 요청도 끊는다 — 테스트 안에서 `try/finally` 로 `page.unroute(pattern)` 한다
  (`test_detail_form.test_검사_기록이_있어_삭제를_거절하면_사유를_보인다`).
- 스냅샷 Export 는 워커가 처리한다. 테스트가 `manage.py run_worker --once` 를
  `DB_CONN_MAX_AGE=0` 으로 직접 부른다(`test_write_paths.run_worker_once`).
- 쓰기 결과는 알림 문구가 아니라 **응답**을 기다려 본다(`page.expect_response`). 알림을 기다리면
  직전 동작의 알림을 읽고 넘어갈 수 있다.
- 화면에 삭제 기능이 없는 검사 기록은 `conftest.manage_shell` 로 지운다. Client 는 검사 기록이 없을 때만 지워지므로
  검사 기록 → 비전검사항목 → Client 순이다(`test_client_workflow.workflow`). 검사 기록이 없는 E2E Client 는
  `/api/vision/client?action=delete` 로 지운다(`test_detail_form.clients`).

화면을 열기만 하는 검사(`capture_ui.py`)와 경로만 보는 검사(`verify_links.py`)는 **눌러야 드러나는 결함**을
못 잡는다. 쓰기 동작을 더하면 `tests/e2e/test_write_paths.py` 에 누르는 테스트를 더한다.

### 2.3 라벨링 워크플로우 수동 점검

`tests/e2e/test_client_workflow.py` 가 자동으로 도는 흐름을 사람이 화면으로 따라간다. 서버와 워커가 떠 있어야 한다.

1. **Client 등록** — 비전검사 클라이언트 관리에서 `E2E-MANUAL` 을 등록하고 한 번만 보이는 API Key 를 적어 둔다.
2. **비전검사항목** — 비전검사항목 관리에서 `E2E-` 항목을 만들고 홈 편집 창에서 결함 라벨을 하나 더한다.
3. **수집** — Client 처럼 보낸다(키는 출력되지 않는다). 데이터 목록 [데이터 추가]로 사진도 올린다.
   ```bash
   VISION_API_KEY=<키> .venv/bin/python scripts/dev/send_inspections.py --client-id E2E-MANUAL --item-id <id> --kind mixed --count 5
   # 실제 사진 폴더: --images ~/사진   ·  서버 없이 도구만 확인: --self-check
   ```
4. **데이터 목록** — "수집" 열이 클라이언트·화면 업로드로 나뉘고, Client 이미지는 Client ID·촬영 시각이 보인다.
5. **이미지 편집** — 회전·크롭을 저장했다가 원본 복원. 확대(+)는 25% 씩, 100% 는 캔버스에 맞춘 크기다.
6. **라벨링** — 객체 검출은 BBOX, 이상 탐지는 결함 유형 → Polygon(점 클릭 → Enter), 정상은 "정상". 임시 저장 → 작업 완료.
7. **검수** — 한 장은 재작업 요청(사유 필수) → 라벨링에서 사유 배너 확인 → 다시 작업 → 검수 완료.
8. **스냅샷** — 등록(형식은 검사 유형마다 고정) → `.venv/bin/python manage.py run_worker --once` → [조회] → [받기].
9. **zip 확인** — 이미지는 `<sha256>.<원본 확장자>` 다(`send_inspections.py` 가 만든 이미지는 `.jpg`, `--images` 로 보낸 PNG 는 `.png`).

   | 형식 | 볼 파일 |
   |---|---|
   | COCO | `images/*`, `annotations/instances.json` 의 `file_name`·`bbox` |
   | ImageFolder | `<라벨>/*` |
   | MVTec AD | `train/good/*`, `test/<결함>/*`, `ground_truth/<결함>/*_mask.png`, `metadata.json` |

10. **정리** — `E2E-MANUAL` 은 [수정] → "사용" 해제 → [저장](검사 기록이 있어 [삭제]는 거절된다). 비전검사항목은 중지 → 삭제 요청 → 승인.

## 3. 검증 스크립트

`scripts/` 는 역할별 폴더로 나뉘고, 실행 도구 `maipctl.py` 만 바로 아래에 둔다.

| 폴더 | 파일 | 용도 |
|---|---|---|
| `scripts/verify/` | `verify_*`·`capture_ui.py` | 검증 스크립트(아래 표) |
| | `demo_item.py` | 서버가 필요한 검증 스크립트가 데모 비전검사항목 id 를 찾는 모듈. 직접 실행하지 않는다 |
| `scripts/` | `maipctl.py` | 개발·단독 실행에서 웹·워커 start·stop·status·restart(§1.3) |
| `scripts/dev/` | `send_inspections.py` | 비전검사 클라이언트처럼 검사 이미지를 보낸다(§2.3). e2e 가 `scripts.dev.send_inspections` 에서 `defect_jpeg`·`metadata` 를 가져다 쓴다 |
| `scripts/systemd/` | `maip.service`(웹, 워커를 함께 띄움)·`maip-worker.service` | 운영 서비스 유닛 |

모두 `PASS`/`FAIL` 을 출력하고 실패하면 종료 코드 1 이다.

| 스크립트 | 잡는 것 | 필요한 것 |
|---|---|---|
| `node scripts/verify/verify_screen_js.js` | 템플릿·정적 JS 의 ① 인라인 `<script>` 문법 오류 ② `AjaxUtil.*AsyncData` 의 `function` 콜백 안 `this.`(화면 객체가 아니다) | Node |
| `scripts/verify/verify_menu.py` | `gui.py` 화면 ↔ DB `menu_item.MenuCode` 양방향. 화면 없는 메뉴, 메뉴 없는 화면(`RETIRED_FROM_MENU` 와 `wm_noauth_default` 는 제외) | **DB**(seed_initial 후) |
| `scripts/verify/verify_permission_map.py` | `app/views/<task>/<view>.py` ↔ `taskview_menu_code_map()` 양방향. 매핑에 없는 경로, 없는 화면 코드를 가리키는 매핑(page 경로 매핑 포함) | Django 설정 |
| `scripts/verify/verify_response_keys.py` | 데이터 템플릿이 폐기된 응답 키 `response.project` 등을 읽는 곳. 서버는 `item` 만 내보내므로 화면이 조용히 빈다 | 없음 |
| `scripts/verify/verify_tokens.py` | `tokens.css` 를 거치지 않은 유채색 리터럴·`font-family` 직접 선언(데이터 CSS 3개 — `main.css`·`governance.css`·`preview.css`), MES CSS 의 지목된 브랜드색 리터럴 | 없음 |
| `scripts/verify/verify_korean_only.py` | 사용자 화면에 언어 변경 수단(국기·언어 목록·`data-lang-code` 등)이 다시 나왔는지. 관리자 i18n 화면은 제외 | 없음 |
| `scripts/verify/verify_links.py` | 템플릿·`static/data/*.js` 의 경로를 라우터로 해석해 404 를 찾는다(모듈·템플릿·`{% static %}` 파일 존재까지). 현행 문서의 md 링크·"FEATURES §8" 같은 절 참조·`근거:` 줄의 결정 ID 도 본다 | Django 설정 |
| `scripts/verify/verify_naming.py` | 소스(`app`·`domain`·`configurations`·`scripts`·`tests`)와 살아 있는 문서에 폐기한 원본 저장소 이름이 남았는지 | 없음 |
| `scripts/verify/verify_modals.py` | 모달 세 계열 — Alert · Confirm · Bootstrap 단독(API Key · 클라이언트 배포본 · 임시 비밀번호 · 데이터 업로드 · 비전검사항목 편집 · 비전검사항목 등록 · 스냅샷 등록) · PopupDraggable(컬럼 설정) — 을 실제로 열어 백드롭 실효 알파·Esc 닫힘·포커스·푸터 버튼 순서를 잰다 | **서버**·`.admin_pw`·seed_demo·playwright |
| `scripts/verify/verify_buttons.py` | 22개 화면을 1920 × 911 로 열고 보이는 활성 `button`·`a.btn` 의 계산된 색을 버튼 계층별 기대 형태(주요=빨강 채움, 위험=빨강 외곽선, 보조=중립 외곽선)와 맞춘다. 치수는 재지 않는다 | **서버**·`.admin_pw`·seed_demo·playwright |
| `scripts/verify/verify_layout_stable.py` | 화면 요소 바운딩 박스의 두 시점 비교(§4) | **서버**·`.admin_pw`·seed_demo·playwright |
| `scripts/verify/capture_ui.py` | `SCREENS` 22화면(대시보드·품목·BOM 조회·입고 내역·인터페이스 이력·검사 관리 일부·디지털 전환 화면은 없다)의 스크린샷 + 4xx·5xx 응답·JS 오류 수. 하나라도 있으면 FAIL | **서버**·`.admin_pw`·seed_demo·playwright |
| `scripts/verify/verify_dig_form_width.py` | 디지털 전환 5화면을 1024×768 셸 탭(930px)으로 열고 양식마다 상세·새 작성 모달, 구분마다 사진 넣기 팝업·결과 모달을 그려 가로 넘침·4xx·5xx·JS 오류를 센다. 쓰기 요청은 막는다. 개발 DB 의 렌더링 시험 양식 DF0005(병합 칸이 겹치게 일부러 만든 것)는 넘친다 | **서버**·`.admin_pw`·playwright |

"Django 설정" 은 `configurations.settings` 를 읽으므로 `.env` 가 있어야 한다는 뜻이다.
서버가 필요한 것 중 `verify_dig_form_width.py` 를 뺀 넷은 `scripts/verify/demo_item.py` 로 seed_demo 의 `FAN-PANEL-DET` id 를 찾아 `?inspection_item=<id>` 로 데이터 화면을 연다(없으면 멈춘다).

무엇을 돌릴지는 AGENTS.md [5] 의 테스트 범위 규칙을 따른다.

## 4. 레이아웃 회귀 비교

CSS 를 고쳤으면 레이아웃이 움직이지 않았는지 수치로 본다. 색이 바뀌면 스크린샷은 전부 달라지므로
"색만 바꿨다"는 스크린샷으로 증명되지 않는다.

```bash
python scripts/verify/verify_layout_stable.py capture /tmp/geo-before   # 고치기 전
python scripts/verify/verify_layout_stable.py capture /tmp/geo-after    # 고친 뒤
python scripts/verify/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-after
python scripts/verify/capture_ui.py /tmp/ui-after                       # 스크린샷 + 4xx/5xx·JS 오류
```

| 항목 | 값 |
|---|---|
| 뷰포트 | 1920×911 (최소 사양) |
| 허용 오차 | 0.5px (서브픽셀 반올림만) |
| 요소 주소 | 태그 + 형제 순번 경로. class 는 상태에 따라 바뀌므로 쓰지 않는다 |
| 대상 | 19화면 — `capture_ui.py` 의 22화면에서 로그 3화면(`wm_login_log`·`wm_menu_log`·`wm_system_log`)을 뺐다(도는 것만으로 로그 행이 늘어난다) |

**기준선은 데이터가 바뀌면 같이 흔들린다.** 비교는 화면에 그려진 행 수에 따라 그리드 높이가 달라지는 것까지 잡는다.

- e2e·seed_demo·수작업 입력으로 행이 늘거나 줄면 그 화면이 움직인다.

이동이 잡히면 **CSS 가 범인인지 먼저 격리한다.** 지금 데이터 그대로, 이전 커밋의 CSS 로 한 번 더
capture 해 고친 뒤 결과와 비교한다. 이 둘이 같으면 이동은 데이터 탓이다. 의도한 이동이면 기준선을 새로 뜬다.

## 5. 개발 함정

각 항목은 **증상 → 원인 → 대처** 순이다.

### 5.1 `DB_CONN_MAX_AGE` 는 개발에서 0

- **증상** e2e 도중 `/api/...` 가 500, 테스트가 타임아웃·JS 오류로 흔들린다. `pg_stat_activity` 에 `idle` 커넥션이 쌓인다.
- **원인** `runserver` 는 요청마다 스레드를 새로 만든다. 값이 0 보다 크면 끝난 스레드의 커넥션이 "재사용 가능"으로 남아 닫히지 않는다. e2e 한 번에 20여 개가 샌다.
- **대처** 개발 `.env` 에 `DB_CONN_MAX_AGE=0`. 운영(gunicorn)은 워커가 상주하므로 `60` 이 맞다.

### 5.2 공유 PostgreSQL 의 `max_connections`

- **증상** 코드를 안 바꿨는데 테스트가 흔들리거나 접속이 거부된다.
- **원인** 이 PostgreSQL 은 다른 프로젝트와 공유한다(`plant_i`·`vision_user`·`aidatahub` 등. 우리 DB 는 `yest`). `max_connections` 가 100 이라 누가 새든 모두 막힌다.
- **대처** 코드보다 여기를 먼저 본다.

  ```sql
  select datname, state, count(*) from pg_stat_activity group by 1,2 order by 3 desc;
  ```

### 5.3 RLS 밖 조회는 예외 없이 0건

- **증상** 데이터가 있는데 조회가 비어 있다. 오류도 로그도 없다. 사용자 삭제는 외래키 오류로 실패한다.
- **대처** `tenant_atomic()` 안에서 읽고 지운다. 단위 테스트는 `TENANT_RLS_ENABLED=False` 라 못 잡는다(§2.1-1 로 본다).

### 5.4 권한 매핑이 없으면 즉시 403

- **증상** 새 API·화면이 로컬에서 403. `domain/gui.py` 매핑 누락이다(AGENTS [3]) — `verify_permission_map.py` 가 잡는다.

### 5.5 `/api/v1` 라우트는 catch-all 앞에

- **증상** 새 `/api/v1/...` 경로가 `404 NOT_FOUND` 봉투를 돌려준다.
- **대처** `configurations/urls.py` 의 `api/v1/<path:rest>` catch-all 이 아래 경로를 모두 받는다 — 구체 라우트를 **앞**에 넣는다(AGENTS [2]).

### 5.6 HTTP 상태줄에 한글 금지

- **증상** 오류 응답이 브라우저에 닿지 않고 요청이 멈춘 채 기다린다.
- **원인** 상태줄(`HttpResponse(reason=...)`)은 latin-1 만 쓸 수 있어 한글이면 응답 머리를 쓰다 실패한다.
- **대처** `reason` 은 영문만. 사유는 본문 `message` 로 보낸다(`AjaxUtil.failureCallback` 이 읽는다).

### 5.7 Ajax 콜백 안의 `this`

- **증상** 응답은 200 인데 그리드가 비어 있다.
- **원인** `AjaxUtil.*AsyncData(url, data, function (result) {...})` 콜백의 `this` 는 화면 객체가 아니라 jQuery ajax 컨텍스트다.
- **대처** 바깥에서 `let _this = this` 로 잡아 쓰거나 화살표 함수를 쓴다. `verify_screen_js.js` 가 잡는다. 콜백을 변수에 먼저 담아 넘기면 못 잡는다.

### 5.8 데이터 화면의 실패는 조용하다

- **증상** 데이터 관리 화면의 일부가 그려지지 않는다. 콘솔에 아무것도 없을 수 있다.
- **원인** 응답 키가 틀린 것(`response.project` → `undefined`)처럼 예외가 없는 실패는 콘솔에도 남지 않는다.
- **대처** `verify_response_keys.py`(폐기 키)·`verify_links.py`(없는 경로)를 돌린다. `capture_ui.py` 는 화면을 열기만 하므로 눌러야 드러나는 경로는 e2e 로 확인한다.

### 5.9 `{% static %}` 은 없는 파일도 조용히 경로를 낸다

- **증상** 화면이 스타일 없이 뜬다. 서버 로그는 정상이다.
- **원인** 템플릿은 파일이 없어도 경로를 출력하고, 브라우저만 404 를 받는다.
- **대처** `verify_links.py` 가 파일 존재까지 본다.

### 5.10 Django `{# #}` 는 한 줄 전용

- **증상** 주석으로 쓴 글이 화면에 그대로 나온다.
- **원인** `{# ... #}` 는 한 줄 주석이다. 여러 줄이면 주석으로 처리되지 않는다.
- **대처** 여러 줄은 `{% comment %} ... {% endcomment %}`.

### 5.11 오류 트레이스는 파일 로그에 있다

- **증상** 화면의 "시스템 로그"에는 한 줄뿐이다.
- **대처** 500 을 쫓을 때는 `LOG_DIR`(비우면 `STORAGE_ROOT/logs`)의 `app-YYYY-MM-DD.log` 를 먼저 연다. 테스트 설정은 로그를 버린다.

### 5.12 GPU 의존성을 설치하지 않는다

- 웹 서버 venv 에 `torch` 를 넣지 않는다. 추론을 시험하려면 `.env` 에 Wezard 주소·키를 넣고 `sample_inspection`(§1.3)을 돌린다. `WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 비면 Stub(`GPU_INFERENCE_NOT_CONFIGURED`)이고 이미지 저장·라벨링은 정상이다.

### 5.13 정적 파일은 `{% static %}` 으로 싣는다

- **증상** 템플릿에 `/static/...` 을 직접 쓰면 `tests/test_static_storage.py` 가 실패한다. 직접 쓴 경로는 운영에서 해시가 붙지 않아 긴 캐시를 받지 못한다.
- **원인** 운영(`DEBUG=False`)의 `collectstatic` 이 `StaticStorage`(`configurations/storage.py`, whitenoise Manifest)로 해시 이름(`common.<해시>.js`)과 gzip 을 만들고, whitenoise 가 해시 이름 파일을 10년 immutable 로 낸다. 파일이 바뀌면 해시가 바뀌므로 `?v=` 를 손으로 올리지 않는다.
- **대처** `{% load static %}` 후 `src="{% static 'assets/js/common.js' %}"`. `?v=` 는 붙이지 않는다. 개발(runserver, `DEBUG=True`)은 해시 없이 원래 이름으로 나간다. JS 가 문자열로 만드는 정적 경로(테마 CSS 교체)는 해시 대상이 아니라 `WHITENOISE_MAX_AGE`(1시간)를 받는다.

### 5.14 서버 모드 그리드는 스스로 첫 조회를 하고 내보내기를 막는다

- **증상** 화면을 열 때 목록을 두 번 받는다. 엑셀 버튼이 아무것도 받지 않는다.
- **원인** WeZonGrid `dataMode:'server'` 는 만들어진 직후 `initial` 조회를 한다. 화면이 [조회]를 바로 부르면 한 번 더 받는다. 서버 모드에서는 `exportToExcel` 이 막혀 있다.
- **대처** 조건이 정해지기 전에는 `gridRemoteSource` 의 조건 함수가 `null` 을 준다(요청하지 않는다). `AjaxUtil.gridResearch` 는 첫 조회 전이면 다시 부르지 않는다. 엑셀은 `GridUtil.exportAll(grid, url, params, fileName)` — 조건 전체를 `export=1` 로 받는다.

### 5.15 `FormUtil.BindDataForm` 은 disabled 를 풀고 참/거짓을 체크하지 못한다

- **증상** 읽기 전용으로 둔 칸(Client ID 등)이 행을 고르면 입력 가능해진다. `active: true` 인데 체크박스가 꺼져 있다.
- **원인** `BindDataForm` 이 값을 넣으며 `disabled` 를 지운다. 체크박스는 `value` 문자열(`'on'`)과 비교한다.
- **대처** 상세 영역은 `DetailForm` 을 쓴다 — 처음부터 막힌 칸은 계속 막고, 참/거짓 값은 `checked` 로 맞춘다. 저장할 때 체크박스는 `'1'`/`'0'` 으로 직접 보낸다(빠지면 서버가 기본값으로 본다).

### 5.16 `setSelectionByRowId` 는 `rowIdField` 가 없으면 조용히 아무것도 안 한다

- **증상** 다시 읽은 뒤 고른 행이 선택되지 않는다. 오류도 없다.
- **원인** WeZonGrid 가 `props.rowIdField` 로 행을 찾는다. 서버 모드가 아닌 그리드는 지정하지 않아도 만들어진다.
- **대처** `GridUtil.setRows(..., {select})`·`DetailForm` 의 선택 복원을 쓰는 그리드에는 `rowIdField` 를 준다(클라이언트 `id`, Overlay `item_id`).

### 5.17 `$('<input>', {maxlength: …})` 는 속성이 아니라 플러그인을 부른다

- **증상** 입력칸을 누르면 아래에 "NaN / undefined" 가 붙는다.
- **원인** jQuery 는 속성 객체의 키가 같은 이름의 jQuery 메서드이면 그 메서드를 부른다. `vendor.min.js` 에 bootstrap-maxlength(`$.fn.maxlength`)가 있어 옵션 없이 글자 수 표시가 붙고 `maxlength` 속성은 빠진다.
- **대처** `maxlength` 는 `.attr('maxlength', n)` 로 넣는다. 속성 객체의 키가 jQuery 메서드 이름(`text`·`val`·`css` 와 실린 플러그인 이름 전부)이면 속성이 아니라 메서드 호출이 된다.

### 5.18 모델에 `index_together` 를 쓰지 않는다

- **증상** `TypeError: 'class Meta' got invalid attribute(s): index_together` 로 서버가 뜨지 않는다.
- **원인** Django 5.1 에서 `Meta.index_together` 가 없어졌다(지금 5.2 LTS). 원본 MES 모델을 옮길 때 자주 걸린다.
- **대처** 인덱스는 `Meta.indexes = [models.Index(fields=[...], name='...')]` 로 둔다(이름 30자 이하). 외래키 하나에 거는
  인덱스는 외래키가 이미 갖고 있어 따로 두지 않는다.

### 5.19 `GridUtil` 이름을 다시 선언하지 않는다

- `grid.js` 가 `let GridUtil` 로 선언한다. 다른 파일에서 같은 이름을 선언하면 모든 화면 스크립트가 멈춘다.

### 5.20 겹치는 `<svg>` 에는 크기를 준다

- 크기 없는 `<svg>` 는 `inset: 0` 만으로 늘지 않고 viewBox 비율로 잡혀 Polygon 층이 어긋난다. 겹치는 svg 에는 `width/height: 100%` 를 준다.

### 5.21 워크트리 서버는 저장소 경로를 main 으로 준다

- **증상** 워크트리에서 띄운 확인용 서버(예: 8124)에서만 썸네일·대표 이미지가 404 이고, `capture_ui.py` 가 오류를 내거나 `verify_layout_stable.py` 가 이미지가 있는 화면을 "이동"으로 잡는다. 8123(main)에서는 멀쩡하다.
- **원인** `.env` 에 `STORAGE_ROOT` 가 없으면 `BASE_DIR/storage` 다. 워크트리의 `BASE_DIR` 은 워크트리 폴더라 DB 는 같은데 파일은 다른 곳을 본다.
- **대처** `STORAGE_ROOT=<main 저장소>/storage python manage.py runserver 127.0.0.1:8124` 로 띄운다. 레이아웃 기준선과 비교 대상도 같은 경로를 본 서버로 뜬다.
- **e2e** 배포물 zip 도 git 에 없어 같은 일이 난다. 서버와 pytest 둘 다 `STORAGE_ROOT=<main>/storage DISTRIBUTION_ROOT=<main>/distribution` 으로 띄운다(워커를 pytest 프로세스에서 띄우는 `test_write_paths`·`test_client_workflow` 때문). 빠지면 Export zip 404·다운로드 시간 초과·"배포본 zip 이 있어야 한다" 로 실패한다.

