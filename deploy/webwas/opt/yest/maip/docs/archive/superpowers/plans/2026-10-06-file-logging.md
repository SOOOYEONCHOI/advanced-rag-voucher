# 시스템 로그를 파일로 남긴다 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.env` 의 `LOG_DIR` 에 시스템 로그가 **날짜별 파일**(`app-YYYY-MM-DD.log`)로 쌓인다. 비우면 `<STORAGE_ROOT>/logs` 다. 보존 기간(`LOG_RETENTION_DAYS`)이 지난 파일은 지운다.

**Architecture:** 날짜별 파일 핸들러(`configurations/log.py` `DailyFileHandler`)를 `LOGGING` 에 더한다. 각 프로세스가 **그날 파일을 append 로 열고** 날짜가 바뀌면 새 파일로 넘어간다 — 이름을 바꾸는 회전이 없어 웹 워커 4개와 `run_worker` 가 함께 써도 충돌하지 않는다. `LogWriter.add_dblog`(화면의 "시스템 로그" = DB `SystemLog`)는 DB 기록을 유지하면서 같은 내용을 파일에 스택 트레이스와 함께 남긴다.

**Tech Stack:** Python `logging`(표준 라이브러리). Django 가 프로세스 시간대를 `TIME_ZONE`(Asia/Seoul)으로 맞추므로 날짜는 KST 자정에 갈린다(실측).

## 지금 상태 (2026-10-06 실측)

- **파일로 남는 로그가 없다.** `LOGGING` 의 핸들러는 `console` 하나뿐이다
  (`configurations/settings.py:194`). `storage/logs` 폴더도 없다.
- 운영은 gunicorn 이 stdout 을 systemd 로 넘겨 **journald** 에만 남는다
  (`08_DEPLOYMENT.md` §5 `--access-logfile - --error-logfile -`).
- 화면의 "시스템 로그"(`wm_system_log`)는 **DB 테이블** `SystemLog` 다.
  `LogWriter.add_dblog` 가 쓰며 **스택 트레이스를 남기지 않는다** — 예외 문자열 한 줄뿐이다.

## Global Constraints

- **비밀을 로그에 남기지 않는다.** 요청 본문·헤더(`X-API-Key`)·비밀번호를 찍지 않는다
- 새 설정 키는 `.env.example` 에 placeholder 와 함께 더한다
- 테스트는 `--settings=configurations.test_settings`. **테스트는 로그 파일을 쓰지 않는다**
- 의존성을 더하지 않는다

## 판단 (제안)

| # | 판단 | 제안 | 이유 |
|---|---|---|---|
| L-1 | 일 단위 정리(사용자 요구, 2026-10-06) | **앱이 날짜별 파일에 직접 쓴다**(`DailyFileHandler`) | 표준 `TimedRotatingFileHandler` 는 자정에 파일 이름을 바꾸는데, 여러 프로세스가 각자 바꾸려 해 충돌한다. logrotate 는 운영 설정이 따로 필요하고 개발 환경엔 없다. 날짜별 파일에 append 만 하면 둘 다 필요 없다. 보존은 `LOG_RETENTION_DAYS`(기본 30, 0 이면 지우지 않음) |
| L-2 | 파일 구성 | **날마다 `app-YYYY-MM-DD.log` 하나** | 프로세스 id 를 줄마다 남겨 웹·워커를 가른다. 오류만 보려면 `grep ' ERROR '` |
| L-3 | DB 시스템 로그 | **DB 는 유지, 파일에도 같이** | 화면이 DB 를 읽는다. 파일에는 트레이스까지 남긴다 |
| L-4 | gunicorn 접근 로그 | **지금처럼 journald** | 요구는 시스템 로그다. 접근 로그는 nginx 에도 있다 |

---

### Task 1: 날짜별 파일 핸들러

**Files:**
- Create: `configurations/log.py` (`DailyFileHandler`)
- Test: `tests/test_logging_config.py`

- [ ] **Step 1: 실패하는 테스트** — 그날 파일에 쓴다 · 날짜가 바뀌면 새 파일 · 보존 기간이 지난
  `app-*.log` 만 지운다(다른 이름의 파일은 건드리지 않는다) · `retention_days=0` 이면 지우지 않는다.
  `LogRecord.created` 를 바꿔 날짜를 흉내 낸다.
- [ ] **Step 2: 구현** — `logging.Handler` 를 상속. `emit` 에서 기록의 날짜(`date.fromtimestamp(record.created)`)가
  열어 둔 날짜와 다르면 닫고 `<dir>/<prefix>-YYYY-MM-DD.log` 를 `'a'` 로 연 뒤 오래된 파일을 지운다.
  한 줄 쓰고 `flush`. 폴더가 없으면 만든다. 삭제는 `unlink(missing_ok=True)` — 다른 프로세스가 먼저 지워도 된다.
- [ ] **Step 3:** 통과 확인 → 커밋 `feat: 로그를 날짜별 파일에 쓰는 핸들러를 더한다`

### Task 1-2: `LOG_DIR`·`LOG_RETENTION_DAYS` 와 설정

**Files:** `configurations/settings.py` · `configurations/test_settings.py` · `.env.example` · `tests/test_logging_config.py`

- [ ] **실패하는 테스트:** `LOG_DIR` 을 비우면 `STORAGE_ROOT/logs` · `LOGGING['handlers']['file']` 이
  `DailyFileHandler` 이고 `directory` 가 `LOG_DIR` · `root` 핸들러에 `file` 이 있다
- [ ] **구현:**

```python
# 시스템 로그. 비우면 저장소 아래 logs/. 날마다 app-YYYY-MM-DD.log 로 나뉜다.
LOG_DIR = Path(env('LOG_DIR', '') or STORAGE_ROOT / 'logs')
LOG_RETENTION_DAYS = int(env('LOG_RETENTION_DAYS', '30'))   # 0 이면 지우지 않는다
```

`LOGGING['handlers']['file'] = {'()': 'configurations.log.DailyFileHandler', 'directory': str(LOG_DIR),
'retention_days': LOG_RETENTION_DAYS, 'formatter': 'standard'}`, `root` 핸들러에 `'file'`.
포맷에 `{process}` 를 더한다(웹·워커를 가른다).
`test_settings.py` 는 `file` 핸들러를 뺀다 — 테스트가 운영 로그 폴더에 쓰지 않게.
`.env.example` 에 `LOG_DIR=` · `LOG_RETENTION_DAYS=30` 과 한 줄 설명.
- [ ] 커밋 `feat: 시스템 로그를 LOG_DIR 의 날짜별 파일로 남긴다`

### Task 2: DB 시스템 로그를 파일에도 (트레이스 포함)

**Files:**
- Modify: `domain/services/logging.py` (`add_dblog`)
- Test: `tests/test_logging_config.py`

- [ ] **Step 1: 실패하는 테스트**

```python
from domain.services.logging import LogWriter


class DbLogMirrorTest(TestCase):  # django.test.TestCase — SystemLog 를 쓴다

    def test_DB_시스템_로그는_파일_로그에도_트레이스와_함께_남는다(self):
        try:
            raise ValueError('boom')
        except ValueError as ex:
            with self.assertLogs('system', level='ERROR') as captured:
                LogWriter.add_dblog('error', 'unit : action-x', ex)
        self.assertIn('unit : action-x', captured.output[0])
        self.assertIn('Traceback', captured.output[0])
```

Expected: FAIL — `no logs of level ERROR or higher triggered on system`

- [ ] **Step 2: 구현** — `add_dblog` 의 `SystemLog.add_log(...)` 다음 줄에

```python
        # 화면(시스템 로그)은 DB 를 읽는다. 파일에는 트레이스까지 남긴다.
        level = logging.ERROR if logtype == 'error' else logging.INFO
        exc_info = (type(ex), ex, ex.__traceback__) if isinstance(ex, BaseException) else None
        system_logger.log(level, '%s %s', source, message, exc_info=exc_info)
```

모듈 위에 `import logging` · `system_logger = logging.getLogger('system')`.
`logtype` 값을 먼저 확인한다(`grep -rn "add_dblog('" app domain | cut -d"'" -f2 | sort | uniq -c`).
`error` 외의 값이 있으면 매핑을 그 값에 맞춘다.

- [ ] **Step 3:** 통과 확인 → **Step 4: 커밋** `feat: DB 시스템 로그를 파일 로그에도 트레이스와 함께 남긴다`

### Task 3: 배포 문서와 실측

**Files:** `docs/08_DEPLOYMENT.md` · `AGENTS.md` [6]

- [ ] `.env` 표에 `LOG_DIR` 행. 서비스 계정(`www-data` 등)이 쓸 수 있게 `chown` 하는 절차
- [ ] `LOG_RETENTION_DAYS` 행. 일 단위 파일과 보존이 앱에서 처리되므로 **logrotate 가 필요 없다**는 것
- [ ] 운영 전 확인 목록에 "`LOG_DIR` 쓰기 권한"
- [ ] AGENTS.md [6] 에 로그 위치 한 줄
- [ ] **실측:** 개발 서버를 다시 띄우고(`DB_CONN_MAX_AGE=0`), 화면 하나를 열고, 없는 action 으로 MES API 를 불러 오류를 낸 뒤 `storage/logs/app-<오늘>.log` 에 요청 로그와 `system` 오류(트레이스 포함)가 있는지 본다. `run_worker --once` 의 로그도 같은 파일에 다른 `process` 로 찍히는지 본다
- [ ] 커밋 `docs: LOG_DIR·LOG_RETENTION_DAYS 를 배포 문서에 더한다`
