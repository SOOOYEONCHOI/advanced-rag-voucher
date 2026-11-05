# 배포 · 운영

근거: DECISIONS DEC-020. 관련: [ARCHITECTURE.md](ARCHITECTURE.md) · [STATUS.md](STATUS.md) · [DECISIONS.md](DECISIONS.md) ·
계약 [client/SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md)

## 한눈에 보기

| 항목 | 지금 |
|---|---|
| 서버 | Rocky Linux 9.6 x86_64 · Python 3.12 venv · Django 5.2.18. 외부 인터넷 불가 — dnf 는 NCP 내부 미러로만 받는다 |
| DB | 외부 PostgreSQL 16 |
| 요청 흐름 | 사용자 → NCP ALB(**지금 HTTP 80**) → 서버 nginx 80 → gunicorn `127.0.0.1:8080`(웹 `maip`) + 워커 `maip-worker` |
| 계정 | 서비스 계정 `maip`(실행만) · 관리 계정 `yhan`(배포·설정, sudo) |
| 배포 | 개발 PC 에서 묶음 만들기 → 로컬 PC 로 받기 → 서버 `/home/yhan/dist` 에 올리기 → `./deploy.sh` → `systemctl restart maip` (§0) |
| 지금 단계 | `HTTPS_ENABLED=False` · SELinux Disabled · Wezard 연결 안 함 |
| 남은 것 | ALB HTTPS·서브도메인(§5) · SELinux 켜기(§6) · 백업(§7) · Client 운영 주소판(§8-1) · Wezard 연동(§8) |

| 하려는 일 | 볼 곳 |
|---|---|
| 새 버전 배포 · 되돌리기 | §0 |
| 서버를 처음 세우기 | §2 (순서대로) |
| `.env` 키 뜻 | §3 |
| nginx 설정이 왜 이런지 | §4 |
| 오류가 났다 | §10 |

---

## 0. 매 배포

근거: 사용자 결정 2026-10-23·2026-10-26.

```bash
# 1. 개발 PC — 배포 파일 3개를 만든다. 인자가 없으면 origin/main 을 받는다(원격 인증 필요).
#    인증 없이 만들려면 커밋을 지정한다 — 받지 않고 로컬에 있는 그 커밋으로 묶는다(git log 로 최신인지 먼저 본다)
deploy/build_package.sh <커밋>
.\deploy\build_package.ps1 <커밋>        # Windows PowerShell — 같은 묶음을 만든다
#    실행 정책에 막히면 powershell -ExecutionPolicy Bypass -File deploy\build_package.ps1 <커밋>
#    pip 은 .venv → py → python 순으로 찾는다. "pip 을 찾지 못했다" 로 멈추면 pip 경로를 직접 준다:
#      $env:PIP = (Get-Command pip).Source; .\deploy\build_package.ps1 <커밋>                    # PATH 에 pip 이 있을 때
#      $env:PIP = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\pip.exe"; .\deploy\build_package.ps1 <커밋>   # 설치 경로를 알 때
#    → deploy/dist/maip-<커밋>.tar.gz · maip-<커밋>.tar.gz.sha256 · deploy.sh

# 2. 로컬 PC 로 받는다(VS Code 탐색기 "Download…" 또는 SFTP). 받은 파일 확인 — PowerShell:
#    Get-FileHash .\maip-<커밋>.tar.gz -Algorithm SHA256      # .sha256 파일 안의 값과 같아야 한다

# 3. 서버 /home/yhan/dist/ 에 SFTP(WinSCP 등)로 올린다 — 바이너리 모드

# 4. 서버(yhan) — 가장 최근에 올린 묶음을 반영한다. 실패하면 그 단계에서 멈추고 서비스는 그대로다
cd /home/yhan/dist && chmod +x deploy.sh && ./deploy.sh

# 5. 재시작(워커도 따라온다)과 확인
sudo systemctl restart maip && systemctl is-active maip maip-worker
curl -s -H 'Host: <ALB 주소>' http://127.0.0.1/api/v1/health      # {"status":"ok",...}
```

`deploy.sh` 가 하는 일: 해시 대조 → 소스를 `/opt/yest/maip` 에 반영(`.env`·`static/` 은 그대로) → 묶음의 wheel 로 의존성 설치(인터넷 없이)
→ `migrate` → `seed_initial` → `seed_vision_items`·`seed_dig_form`(아래) → `collectstatic` → `check --deploy` → `verify_menu`·`verify_permission_map`.
서비스는 다시 시작하지 않는다.

- **바이너리 모드로 옮긴다.** 텍스트 모드는 `deploy.sh` 를 CRLF 로 바꿔 실행이 안 되고, `tar.gz` 가 바뀌면 첫 단계에서 멈춘다
- **되돌리기:** `./deploy.sh maip-<이전 커밋>.tar.gz` 뒤 5. — 소스·의존성만 돌아가고 DB 마이그레이션은 되돌리지 않는다. 지난 묶음은 지우지 않는다
- **nginx·서비스 유닛을 바꾼 배포**는 그 파일을 다시 복사한다(§2-5·§2-6). 메뉴를 바꾼 배포는 `seed_initial` 이 반영한다
- **인덱스를 만드는 마이그레이션**은 업무 외 시간에 배포한다 — 큰 테이블(`vision_inspection` 등)의 쓰기가 그동안 막힌다
- **`seed_vision_items`·`seed_dig_form` 은 그 기본 데이터가 바뀐 배포에서만 돈다** — 평소에는 "건너뜁니다"가 정상이다. 두 명령은 없는 것을 만들고
  화면의 삭제는 행을 지우므로, 매번 돌리면 운영에서 지운 기본 항목·양식이 되살아난다. 비교 대상은 `seed_vision_items.py`·`samples/dig_form_forms.json`·`dig_form_images/` 이고,
  성공한 데이터의 해시를 `/home/yhan/dist/.seed-<명령>` 에 남긴다(지우면 다음 배포에서 다시 돈다). 기본 데이터를 바꾼 배포에서는 지운 항목이 다시 생길 수 있다
- `seed_vision_items --update-descriptions`(설명을 고친 판을 배포할 때만, 화면에서 고친 설명을 덮는다)는 스크립트가 하지 않는다 — 따로 돌린다

---

## 1. 구성

### 프로세스 두 개

| 프로세스 | 하는 일 | 없으면 |
|---|---|---|
| **웹** `maip` (gunicorn `127.0.0.1:8080`, worker 4, `--timeout 120`) | 화면·API | 서비스가 안 뜬다 |
| **워커** `maip-worker` (`manage.py run_worker --interval 5`) | 스냅샷 Export(zip), 하루 한 번 DB 로그·만료 세션 정리 | 버튼은 눌리는데 작업이 **영원히 대기**로 남는다 |

워커는 `maip` 를 따라 뜨고 멈춘다(`Wants=`·`PartOf=`) — 운영자는 `systemctl start|stop|restart maip` 하나만 쓴다. 워커만 다시 띄울 때는 `restart maip-worker`.
워커가 종료 신호를 받으면 지금 묶음을 끝내고 나가는데 systemd 는 90초 뒤 강제 종료한다 — 긴 Export 가 있으면 `TimeoutStopSec` 을 늘린다.
워커 옵션·재시도는 ARCHITECTURE §8.

### 경로 · 권한

| 구분 | 경로 | 소유자 | 권한 |
|---|---|---|---|
| 소스 | `/opt/yest/maip` | `yhan:maip` | 폴더 2750 / 파일 640(실행 파일 750) |
| 정적 파일 (`collectstatic`) | `/opt/yest/maip/static` | `maip:maip` | 2750 |
| 환경 변수 | `/opt/yest/maip/.env` | `yhan:maip` | 640 |
| 실행 환경 (venv) · wheel | `/opt/envs/maip` · `/opt/envs/maip/wheels` | `yhan:maip` | 2750 |
| 데이터 (`STORAGE_ROOT`) | `/mnt/a/maip/data` | `maip:maip` | 750 |
| 로그 (`LOG_DIR`) | `/mnt/a/maip/logs` | `maip:maip` | 750 |
| 배포물 (`DISTRIBUTION_ROOT`) | `/mnt/a/maip/distribution` (`licenses/`·`client/`) | `yhan:maip` | 750 |
| 서비스 계정 홈 (캐시) | `/var/lib/maip` | `maip:maip` | 700 |
| 서비스 유닛 · nginx 설정 | `/etc/systemd/system/maip*.service` · `/etc/nginx/conf.d/*.conf`(§4) | `root` | 644 |
| 배포 파일 업로드 | `/home/yhan/dist` | `yhan` | 묶음·`deploy.sh`·seed 기록 |

- 소스·venv·`.env` 는 `yhan` 이 쓰고 `maip` 는 **읽기만** 한다. 데이터·로그는 `maip` 만 쓴다. 그 밖의 계정은 접근하지 못한다
- 폴더의 setgid(2750) 때문에 새 파일이 그룹 `maip` 를 물려받는다 — `deploy.sh` 가 이것에 기댄다
- 서비스 유닛은 `UMask=0027` 이라 앱이 만드는 파일도 750·640 이다
- 데이터·로그·배포물은 `/mnt/a`(2T), 소스·venv 는 `/`(49G) — 이미지 보존정책이 없어 데이터가 계속 늘어난다
- `yhan` 은 그룹 `maip` 라 로그를 sudo 없이 읽는다. nginx 는 그룹 `maip` 에 넣지 않고 ACL 로 두 폴더만 읽는다(§2-6)
- **관리 계정을 바꿀 때:** 새 계정을 그룹 `maip` 에 넣고 옛 계정의 파일만 넘긴다 —
  `sudo find /opt/yest/maip /opt/envs/maip /mnt/a/maip/distribution -user <옛 계정> -exec chown -h <새 계정> {} +`.
  `chown -R` 은 `static/` 까지 넘겨 `collectstatic` 이 실패한다

의존성은 `requirements.txt` 가 전부이고 모두 미리 빌드된 wheel 이다(gcc 불필요). WEB 서버에 `torch` 를 설치하지 않는다.
서버 상태 점검은 `deploy/check_rocky.sh`(조회만 한다)다.

---

## 2. 처음 설치 (순서대로)

관리 계정(`yhan`)으로 한다. `manage.py` 는 반드시 서비스 계정으로 돌린다 — 설정을 읽는 순간 데이터·로그 폴더에 쓰기 때문에,
다른 계정으로 돌리면 권한 오류가 나거나 폴더가 그 계정 소유가 된다.

```bash
PY="sudo -u maip /opt/envs/maip/bin/python"     # 아래에서 계속 쓴다
```

### 2-1. 서버 준비

```bash
# 기본 python3(3.9)는 Django 5.2 를 못 쓴다 — 3.12 를 따로. 기본 python3 는 dnf 가 쓰므로 바꾸지 않는다
sudo dnf install -y python3.12 python3.12-pip nginx rsync acl

# 서비스 계정(로그인 불가) · 관리 계정을 그룹 maip 에(다시 로그인해야 적용)
sudo useradd --system --home-dir /var/lib/maip --create-home --shell /usr/sbin/nologin maip
sudo chmod 700 /var/lib/maip
sudo usermod -aG maip yhan

# 폴더 — 표는 §1
sudo install -d -o yhan -g maip -m 2750 /opt/yest/maip /opt/envs/maip
python3.12 -m venv /opt/envs/maip
sudo install -d -o maip -g maip -m 2750 /opt/yest/maip/static
sudo install -d -o maip -g maip -m 750  /mnt/a/maip/data /mnt/a/maip/logs
sudo install -d -o yhan -g maip -m 750  /mnt/a/maip/distribution /mnt/a/maip/distribution/licenses /mnt/a/maip/distribution/client
sudo -u maip mkdir -p /mnt/a/maip/data/media
```

배포 파일 3개는 §0 의 1~3 으로 `/home/yhan/dist` 에 올리고 `sha256sum -c maip-<커밋>.tar.gz.sha256` 으로 확인한다.

### 2-2. DB 확인

DB 와 전용 계정이 있어야 한다. **테이블은 마이그레이션이 만든다** — 스키마 SQL 파일은 없다.

| 조건 | 이유 |
|---|---|
| 계정이 DB 소유자(최소한 `public` 스키마 CREATE) | 마이그레이션이 테이블·함수·뷰·RLS 정책을 만든다 |
| **superuser·`BYPASSRLS` 가 아니다** | 그런 계정에는 RLS(조직 격리)가 적용되지 않는다 |
| PostgreSQL 16 · UTF8 · 빈 DB | |
| 앱 서버 IP 에서 접속 허용(pg_hba·ACG) | |

직접 만들 수 있으면(DB 서버에서): `sudo -u postgres createuser --pwprompt <DB_USER>` → `sudo -u postgres createdb --owner=<DB_USER> <DB_NAME>`.
비밀번호를 명령줄에 적지 않는다. 접속 정보만 받았으면 2-3 의 `.env` 를 채운 뒤 앱 서버에서 확인한다
(venv 에 psycopg 가 없으면 먼저 `tar -xzf` 한 묶음의 wheel 로 `pip install --no-index --find-links <묶음>/wheels -r <묶음>/source/requirements.txt`):

```bash
/opt/envs/maip/bin/python - <<'EOF'
import psycopg
env = dict(l.strip().split('=', 1) for l in open('/opt/yest/maip/.env', encoding='utf-8')
           if l.strip() and not l.lstrip().startswith('#') and '=' in l)
conn = psycopg.connect(host=env['DB_HOST'], port=env['DB_PORT'], dbname=env['DB_NAME'],
                       user=env['DB_USER'], password=env['DB_PASSWORD'], connect_timeout=5)
print(conn.execute("""select current_user, r.rolsuper, r.rolbypassrls, has_schema_privilege('public','CREATE'),
    current_setting('server_version'), (select count(*) from pg_tables where schemaname='public')
    from pg_roles r where r.rolname = current_user""").fetchone())
EOF
# 정상: ('<계정>', False, False, True, '16.x', 0)
```

### 2-3. `.env`

```bash
cd /home/yhan/dist
tar -xzOf maip-<커밋>.tar.gz maip-<커밋>/source/.env.example > /opt/yest/maip/.env
chmod 640 /opt/yest/maip/.env                                  # yhan:maip 640
python3.12 -c "import secrets; print(secrets.token_urlsafe(50))"   # SECRET_KEY
vi /opt/yest/maip/.env
```

지금 단계(ALB HTTP)에서 바꾸는 값이다. 나머지는 예시 그대로 두고, 키 뜻은 §3.

| 키 | 값 |
|---|---|
| `DEBUG` | `False` |
| `SECRET_KEY` | 위에서 만든 값 |
| `ALLOWED_HOSTS` | `<ALB 주소>,<서버 사설 IP>` — 사설 IP 는 서버 안 `curl` 확인용 |
| `CSRF_TRUSTED_ORIGINS` | `http://<ALB 주소>` — **브라우저 주소창의 주소**. 앱 포트 8080·끝의 `/` 는 넣지 않는다 |
| `HTTPS_ENABLED` | `False` (ALB HTTPS 뒤에는 `True`, §5) |
| `DB_HOST`·`DB_PORT`·`DB_NAME`·`DB_USER`·`DB_PASSWORD` | 운영 DB |
| `STORAGE_ROOT`·`LOG_DIR`·`DISTRIBUTION_ROOT` | `/mnt/a/maip/data`·`/mnt/a/maip/logs`·`/mnt/a/maip/distribution` |
| `FILE_ACCEL_REDIRECT` | `True` |
| `WEZARD_BASE_URL`·`WEZARD_API_KEY` | 비운다 — 예시 값은 개발 Wezard 다. 연동할 때 채운다(§8) |
| `WERAG_URL` | `https://chatbot.yest.co.kr` — 예시 값은 개발 주소다 |

`sudo -u maip test -r /opt/yest/maip/.env && echo ok` 로 서비스 계정이 읽는지 본다.

### 2-4. 배포 스크립트 · 첫 배포에만 할 일

```bash
cd /home/yhan/dist && chmod +x deploy.sh && ./deploy.sh maip-<커밋>.tar.gz
```

정상이면 `migrate` 가 `0001_initial` 을 적용하고, 두 seed 가 비전검사항목 16개·고객 양식 15종을 넣고, verify 둘이 PASS 하고,
마지막 줄이 `배포 준비 끝` 이다. `check --deploy` 의 경고는 §3 끝 "check --deploy".

이어서 **첫 배포에만**:

```bash
cd /opt/yest/maip

# 관리자 계정(admin) — 비밀번호를 히스토리에 남기지 않는다. 잊었을 때 다시 정하는 것도 같은 명령이다
read -rs ADMIN_PW; $PY manage.py seed_initial --admin-password "$ADMIN_PW"; unset ADMIN_PW

# 다국어 라벨·그리드 컬럼·메뉴 번역. 서버에 psql 이 없어 앱의 DB 연결로 넣는다(000_run_i18n.sql 과 같은 세 파일·한 트랜잭션, 다시 돌려도 된다)
$PY manage.py shell <<'EOF'
from pathlib import Path
from django.db import connection, transaction
d = Path('domain/_sql/i18n')
with transaction.atomic(), connection.cursor() as c:
    for f in ['010_template_data_labelcd.sql', '020_template_grid_columns.sql', '030_side_menu_translations.sql']:
        c.execute((d / f).read_text(encoding='utf-8'))
print('i18n ok')
EOF
```

- psql 이 있으면 `cd domain/_sql/i18n && psql -X -v ON_ERROR_STOP=1 -h … -f 000_run_i18n.sql` 과 같다. `*_clean.sql` 은 운영에서 돌리지 않는다
- `seed_initial` 은 메뉴 트리에 없는 메뉴와 그 권한을 지운다. 관리자 그룹 전 메뉴 RW, 모든 그룹 대시보드 RW 를 다시 넣는다

### 2-5. 서비스 등록

```bash
cd /opt/yest/maip
sudo install -m 644 scripts/systemd/maip.service scripts/systemd/maip-worker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now maip
systemctl is-active maip maip-worker                                       # active 두 줄
curl -s -H "Host: <서버 사설 IP>" http://127.0.0.1:8080/api/v1/health     # {"status":"ok",...}
```

경로·계정이 다르면 유닛 파일을 고쳐 복사한다. 고쳤으면 다시 복사하고 `daemon-reload`. 운영에서는 `scripts/maipctl.py` 를 쓰지 않는다.

### 2-6. nginx · ACL · ALB

```bash
# Rocky 기본 nginx.conf 의 80 server 블록을 지운다(백업 후) — default_server 가 둘이면 nginx -t 가 실패한다
sudo cp -a /etc/nginx/nginx.conf /etc/nginx/nginx.conf.orig && sudo vi /etc/nginx/nginx.conf

# 공통(기본 server) + 앱 설정 — server_name·set_real_ip_from 을 이 서버 값으로 확인한다(§4). Chatbot·Wezard 관리자 화면은 §5
sudo install -m 644 /opt/yest/maip/scripts/nginx/{00-default,maip}.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx

# nginx 가 이미지·배포물 두 폴더만 읽게(지금 것과 앞으로 생길 것)
sudo setfacl -m u:nginx:x /mnt/a/maip /mnt/a/maip/data
sudo setfacl -R -m u:nginx:rX -m d:u:nginx:rX /mnt/a/maip/data/media /mnt/a/maip/distribution
sudo -u nginx test -r /mnt/a/maip/data/media && echo ok

# 방화벽 — 80 만. 8080 은 열지 않는다
sudo firewall-cmd --permanent --add-service=http && sudo firewall-cmd --reload
```

NCP 콘솔:

| ALB 항목 | 값 |
|---|---|
| 리스너 → 대상 그룹 | HTTP 80 → 이 서버 HTTP 80 |
| 헬스체크 | HTTP 80 경로 **`/lb-health`** (nginx 가 200 으로 답한다) |
| 유휴 시간 제한 | 120초 이상 — 큰 업로드·85MB 배포본 내려받기 |
| ACG | 서버 80 은 ALB 대역과 Wezard 서버(172.16.10.6, §8)에서만 받는다 |

확인: `curl -s http://127.0.0.1/lb-health` → `ok`, 콘솔 대상 상태 healthy, PC 브라우저로 `http://<ALB 주소>` 접속,
브라우저 접속 뒤 `sudo tail -n 3 /var/log/nginx/access.log` 의 첫 칸이 ALB 가 아니라 접속한 PC 주소(realip).

### 2-7. 배포물

LGPL 대응 소스와 Client 배포본을 넣는다 — §8-1.

### 2-8. 기준정보 인터페이스

PLM 품목·BOM, ERP 구매요청(= 입고) 엑셀(**xlsx**, `.xls` 는 못 읽는다)을 명령으로 받는다. `/home/yhan/interface` 에 바이너리 모드로 올리고
서비스 계정이 읽는 곳으로 옮긴다(`maip` 는 `/home/yhan` 을 못 읽는다). **PLM 을 먼저** — ERP 에만 있는 품번은 구매요청 값으로 품목을 만들기 때문이다.

```bash
sudo install -d -o maip -g maip -m 750 /var/lib/maip/interface
sudo install -o maip -g maip -m 640 /home/yhan/interface/*.xlsx /var/lib/maip/interface/
cd /opt/yest/maip
$PY manage.py import_interface plm_part_bom /var/lib/maip/interface/<PLM 파일>.xlsx      # → 수신건 N: … M행
$PY manage.py apply_interface <N>
$PY manage.py import_interface erp_purchase_req /var/lib/maip/interface/<ERP 파일>.xlsx
$PY manage.py apply_interface <N>
rm -r /home/yhan/interface && sudo rm -r /var/lib/maip/interface      # 반영을 확인한 뒤
```

머리글이 다르면 한 행도 넣지 않고 수신 실패로 남는다. 반영은 하나라도 틀리면 아무것도 바꾸지 않고, 다시 해도 결과가 같다(규칙은 DATA_MODEL §2).
확인: 시스템 관리 › 인터페이스 이력, 기준정보 › 품목·BOM 조회·입고 내역.

### 2-9. 데이터 파이프라인 점검과 정리 (초기 세팅 때만)

근거: 사용자 결정 2026-10-26. `seed_demo`·`sample_inspection` 은 개발용이다 — 운영에서는 **초기 세팅 때 한 번만** 돌리고 바로 정리한다.

```bash
$PY manage.py seed_demo              # FAN-PANEL-CLS·FAN-PANEL·FAN-PANEL-DET + 클라이언트 CLIENT-001. API Key 를 한 번 출력 — 채팅·문서에 남기지 않는다
$PY manage.py seed_demo --samples    # 대표 이미지·Overlay·이미지 20장
$PY manage.py sample_inspection --item FAN-PANEL --defect 2 --normal 2
```

- `sample_inspection` 은 Client 처럼 `POST /api/v1/inspections` 로 보낸다. Wezard 가 없으면 `RECEIVED`(모델 매핑 없음)로 남고
  "SUCCESS 가 아닌 검사 N건"으로 끝나는 것이 정상이다 — 인증·접수·저장·라벨링 대기를 지나간 것을 본다
- 실제 Client: 배포본 `config\config.json` 의 `server.base_url` 을 `http://<ALB 주소>` 로 바꿔 `CLIENT-001` 로 등록하고 "이미지 파일로 검사"
- 화면: 비전 검사 이력, 비전 데이터 관리 › FAN-PANEL(데이터 목록 → 라벨링 → 검수 → 스냅샷 Export — 워커가 zip 을 만드는지).
  수입검사: 수입검사 품목 지정 → 수입검사 작성에 대기로 나오는지 → 제출 → 결과

**정리:** 비전검사 클라이언트 관리에서 `CLIENT-001`·`PIPELINE-TEST` 비활성화, 비전검사항목 관리에서 `FAN-PANEL*` 3종 삭제 요청·승인,
시험으로 작성한 수입검사 결과 삭제. 기준정보는 실제 데이터라 남긴다. 검사 기록이 있는 DB 에서 `seed_demo` 는 `--force` 없이 멈춘다.

---

## 3. 참고: `.env`

`.env` 는 커밋하지 않는다. 이미 설정된 실제 환경변수가 `.env` 보다 이긴다. 값을 비우면 기본값이다.

| 키 | 비었을 때 | 운영 | 뜻 |
|---|---|---|---|
| `DEBUG` | `False` | `False` | `True` 면 오류 화면에 소스·설정이 나온다 |
| `SECRET_KEY` | 개발용 고정값 | 새로 생성 | 세션·CSRF 서명. `DEBUG=False` 인데 비면 부팅을 거부한다 |
| `ALLOWED_HOSTS` | `DEBUG` 면 `*` | 접속 주소 + 서버 사설 IP | 쉼표 구분. 없는 Host 는 400. `DEBUG=False` 에서 비거나 `*` 면 부팅 거부 |
| `CSRF_TRUSTED_ORIGINS` | 빈 값 | `http(s)://<접속 주소>` | 스킴까지. 브라우저 주소와 다르면 로그인·저장이 403 |
| `HTTPS_ENABLED` | `False` | 지금 `False`, ALB HTTPS 뒤 `True` | SSL 리다이렉트·HSTS(1년·하위 도메인·preload)·Secure 쿠키를 함께 켠다 |
| `DB_HOST`·`DB_PORT`·`DB_NAME`·`DB_USER`·`DB_PASSWORD` | `127.0.0.1`·`5432`·`yest`·`yest`·빈 값 | 운영 DB | |
| `DB_SEARCH_PATH` · `DB_APPLICATION_NAME` | `public` · `manufacturing_ai_platform` | 그대로 | |
| `DB_CONN_MAX_AGE` | `60` | `60` | 개발(`runserver`)만 `0` |
| `STORAGE_ROOT` | `<프로젝트>/storage` | `/mnt/a/maip/data` | 업로드 원본·파생 파일. nginx 로 노출하지 않는다 |
| `DISTRIBUTION_ROOT` | `<프로젝트>/distribution` | `/mnt/a/maip/distribution` | 배포물(§8-1) |
| `LOG_DIR` · `LOG_RETENTION_DAYS` · `LOG_LEVEL` | `STORAGE_ROOT/logs` · `30` · `INFO` | `/mnt/a/maip/logs` · `30` · `INFO` | 보존 일수가 지난 로그를 지운다(`0` 이면 안 지움) |
| `WORKER_STALE_SECONDS` | `3600` | `3600` | 강제 종료돼 `RUNNING` 으로 남은 작업을 다시 집기까지. 가장 긴 Export 보다 길게 |
| `API_AUTHZ_MODE` | `enforce` | `enforce` | 매핑 없는 API 는 403. `warn` 은 경고만 남기고 통과시키고, `off` 는 검사하지 않는다 |
| `FILE_ACCEL_REDIRECT` | `False` | `True` | 큰 파일 전송을 nginx 에 넘긴다 — nginx `/_protected/` 설정과 함께(§4). 없이 켜면 빈 응답 |
| `TENANT_RLS_ENABLED` | `True` | `True` | `False` 면 데이터 관리 조회가 전부 0건 |
| `WEZARD_BASE_URL` · `WEZARD_API_KEY` | 빈 값 | 운영 Wezard 주소 · 발급 키 | 비면 모델 매핑이 있는 검사도 추론 없이 이미지만 저장(`GPU_INFERENCE_NOT_CONFIGURED`) |
| `WERAG_URL` | 빈 값 | `https://chatbot.yest.co.kr` | 상단 바 We.RAG 로고가 새 탭으로 여는 주소. 비거나 `http(s)://` 가 아니면 로고를 보이지 않는다. 바꾸면 `restart maip` |

**HTTPS 와 프록시 헤더:** `HTTPS_ENABLED=True` 인데 nginx 가 ALB 의 `X-Forwarded-Proto` 를 넘기지 않으면 무한 리다이렉트다(§5).
HSTS 는 브라우저가 한 번 받으면 되돌리기 어렵다 — 같은 도메인 아래 HTTP 서비스가 있으면 켜기 전에 확인한다.

**check --deploy:** HTTPS 뒤에는 `W019`(`X_FRAME_OPTIONS` 가 `DENY` 가 아님) 하나만 남는 것이 정상이고 고치지 않는다(§4 지킬 것 1).
지금(ALB HTTP)은 `W004`·`W008`·`W012`·`W016` 도 남는다.

---

## 4. 참고: nginx

설정 파일은 저장소 `scripts/nginx/` 이고 서버 `/etc/nginx/conf.d/` 에 같은 이름으로 복사한다. 서버는 TLS 를 하지 않는다 — 언제나 평문 80 을 받아 Host 로 서비스를 가른다.

| 파일 | 받는 Host → 넘기는 곳 |
|---|---|
| `00-default.conf` | 기본 server(아래)·`server_names_hash_bucket_size`·`$forwarded_proto` — 나머지 파일이 이것에 기댄다 |
| `maip.conf` | `maip-web.yest.co.kr`·ALB 주소 → `127.0.0.1:8080` |
| `chatbot.conf` | `chatbot.yest.co.kr` → `127.0.0.1:8081` |
| `ai-api.conf` | `ai-api.yest.co.kr` → Wezard `172.16.10.6:8000`. 위존 사무실 공인 IP 만, Wezard 공개 API `/api/v1` 는 막는다(§5) |

| 설정 | 하는 일 |
|---|---|
| 기본 server(`default_server`) | 앱 주소가 아닌 Host 를 응답 없이 끊는다(444). ALB 헬스체크(Host 가 서버 IP)에는 `/lb-health`·`/` 를 200 으로 답한다 |
| 앱 server `server_name maip-web.yest.co.kr <ALB 주소>` | 이 주소로 온 요청만 앱으로 넘긴다 — 아무 Host 로 찌르는 요청이 앱 로그(DisallowedHost)에 쌓이지 않는다. ALB 주소는 옛 Client 를 모두 바꾼 뒤 뺀다(§5) |
| `server_names_hash_bucket_size 128` | ALB 주소(55자)가 기본 칸(64)에 안 들어가 `nginx -t` 가 실패해서 둔다 |
| realip(`set_real_ip_from <ALB 대역>`) | ALB 가 넘긴 `X-Forwarded-For` 로 실제 사용자 주소를 쓴다. 빠지면 모든 사용자가 ALB 주소 하나로 보여 로그인 잠금이 모두를 막는다. ALB 대역에서 온 값만 믿는다 — `0.0.0.0/0` 을 넣지 않는다 |
| `proxy_read_timeout 120s` · `client_max_body_size 40m` | gunicorn `--timeout 120` 과 맞춘다(nginx 기본 60초) · 업로드 한 요청의 합계 |
| `X-Forwarded-Proto $forwarded_proto` | ALB 가 붙인 원래 스킴. `$scheme`(늘 http)을 넘기면 `HTTPS_ENABLED` 에서 무한 리다이렉트 |
| `/api/v1/datasets/` | Wezard 서버(172.16.10.6)에만 연다. ALB 를 거치지 않고 바로 오므로 `X-Forwarded-Proto https` 를 고정해 `HTTPS_ENABLED` 의 301 을 피한다(이 API 는 절대 URL 을 만들지 않는다) |
| `/_protected/media/`·`/_protected/distribution/` (`internal`) | 앱이 권한을 확인한 뒤 넘긴 파일만 nginx 가 보낸다(`FILE_ACCEL_REDIRECT`). 배포물은 `max_ranges 1` |

### 반드시 지킬 것

근거: DECISIONS DEC-019.

1. **`X-Frame-Options` 를 `DENY` 로 덮지 않는다.** 화면을 iframe 탭으로 띄우는 구조라 모든 화면이 빈 탭이 된다
2. **`STORAGE_ROOT` 를 공개 경로로 내지 않는다.** `location /media/ { alias …; }` 를 넣으면 검사 이미지가 인증 없이 공개된다. `internal` 인 `/_protected/` 만 예외다
3. **gunicorn 은 `127.0.0.1` 에만 붙인다.** 로그인 잠금이 nginx 가 넘긴 `X-Real-IP` 로 주소를 세는데, 외부에 붙이면 아무나 헤더로 주소를 바꾼다

정적 파일은 whitenoise 가 내므로 nginx 에 `/static/` 은 필요 없다.

### 업로드 크기

| 경로 | 앱 한도 |
|---|---|
| Client 검사 `POST /api/v1/inspections` | 이미지 32MB(요청 33MB) |
| 데이터 관리 이미지 업로드 | 파일당 30MB, 화면이 **20장씩** 나눠 보낸다 |
| 디지털 양식 이미지 | 장당 30MB, 요청당 1장 |

`client_max_body_size` 는 요청 하나의 합계다 — "20장 × 한 장 크기"를 넘으면 그 묶음이 nginx 413 으로 끊긴다. 장당 2MB 면 40m 으로 충분하다(§11).

---

## 5. ALB HTTPS · 서브도메인

근거: 사용자 결정 2026-10-23·2026-10-27. 인증서는 NCP ALB 에 둔다. 서버 nginx 는 계속 평문 80 이고 Host 로 서비스를 가른다(§4).

```
사용자 ─https─▶ NCP ALB:443(인증서) ─http─▶ 10.0.10.6:80 nginx ─┬─ maip-web.yest.co.kr ▶ 127.0.0.1:8080
                                                                ├─ chatbot.yest.co.kr  ▶ 127.0.0.1:8081
                                                                └─ ai-api.yest.co.kr   ▶ 172.16.10.6:8000 (위존 공인 IP 만, /api/v1 403)
Wezard 172.16.10.6 ─http─▶ 10.0.10.6:80 (maip-web.yest.co.kr /api/v1/datasets/ — ALB 를 거치지 않는다, §8)
```

**1단계 — 도메인 이름으로 받는다(HTTP).** DNS 전에는 PC `hosts` 로 시험한다. 서버, `yhan`:

1. nginx — 네 파일을 넣는다. `ai-api.conf` 는 위존 사무실 공인 IP(`61.40.239.178`)만 연다 — 사용처가 늘면 `allow` 줄을 더한다. 이전 판 `maip.conf` 는 기본 server 를 품고 있어 같이 두면 `nginx -t` 가 실패한다 — 새 `maip.conf` 로 덮는다

   ```bash
   sudo install -m 644 /opt/yest/maip/scripts/nginx/{00-default,maip,chatbot,ai-api}.conf /etc/nginx/conf.d/
   sudo nginx -t && sudo systemctl reload nginx
   ```
2. `.env` — `ALLOWED_HOSTS=maip-web.yest.co.kr,<ALB 주소>,<서버 사설 IP>`, `CSRF_TRUSTED_ORIGINS=http://maip-web.yest.co.kr,http://<ALB 주소>` → `sudo systemctl restart maip`
3. PC `hosts`(Windows `C:\Windows\System32\drivers\etc\hosts`, 관리자 권한) — `<ALB 공인 IP> maip-web.yest.co.kr chatbot.yest.co.kr ai-api.yest.co.kr`.
   IP 는 `nslookup <ALB 주소>` 로 본다. ALB 공인 IP 는 바뀔 수 있으니 DNS 가 붙으면 이 줄을 지운다
4. 확인 — `http://maip-web.yest.co.kr` 로그인·저장, `http://ai-api.yest.co.kr` 관리자 화면(사무실 밖은 403, 화면이 깨지면 관리자 화면이 `/api/v1` 을 부르는지 Wezard 에 확인), `http://<ALB 주소>` 도 그대로 열린다.
   `sudo tail -n 3 /var/log/nginx/access.log` 의 첫 칸이 PC 공인 주소(realip)

**2단계 — 인증서를 붙인다.** 이 순서를 지킨다 — `HTTPS_ENABLED` 를 켜면 `http://<ALB 주소>` 로 오는 요청이 `https://<ALB 주소>` 로 301 되는데, 인증서가 ALB 주소를 덮지 않아 옛 Client 가 끊긴다.

1. ALB — HTTPS 443 리스너(인증서 `*.yest.co.kr` 또는 세 이름 SAN) → 같은 대상 그룹. HTTP 80 은 아직 리다이렉트하지 않는다. ALB 가 `X-Forwarded-For`·`X-Forwarded-Proto` 를 넘기는지 본다
2. 확인 — PC 에서 `curl -s https://maip-web.yest.co.kr/api/v1/health`, `openssl s_client -connect maip-web.yest.co.kr:443 -servername maip-web.yest.co.kr` 로 체인·SAN·만료일. 세 주소가 https 로 열린다
3. Client — `https://maip-web.yest.co.kr` 로 **재빌드**해 배포물을 바꾸고(§8-1, `licenses/sources` 주소가 고지문에 박혀 있다 — 계약 §10-4) 현장 PC 를 모두 바꾼다. 사내 CA 인증서면 CA PEM 도 준다
4. `.env` — `HTTPS_ENABLED=True`, `CSRF_TRUSTED_ORIGINS=https://maip-web.yest.co.kr` → `sudo systemctl restart maip`. `check --deploy` 는 `W019` 하나만 남는다
5. ALB — HTTP 80 리스너를 443 으로 리다이렉트
6. 정리 — `maip.conf` `server_name` 과 `ALLOWED_HOSTS` 에서 ALB 주소를 뺀다. Wezard 는 서버끼리 직접이라 바꿀 것이 없다(§8)

---

## 6. 예정: SELinux 켜기

지금 SELinux 는 Disabled 다. 켜면 아래가 빠졌을 때 화면이 **502**, 이미지·배포물이 **403·404** 다(`/var/log/audit/audit.log` 에 `denied`).
꺼진 동안 만든 파일에는 라벨이 없어 재부팅 때 전체를 다시 라벨링한다 — **업무 외 시간**에 한다.

```bash
# 1. permissive 로 켜고 전체 라벨링 재부팅(부팅이 오래 걸린다)
sudo sed -i 's/^SELINUX=.*/SELINUX=permissive/' /etc/selinux/config
sudo touch /.autorelabel && sudo reboot

# 2. 다시 접속해 정책(semanage 는 켠 뒤에만 된다. 없으면 dnf install -y policycoreutils-python-utils)
sudo setsebool -P httpd_can_network_connect 1                  # nginx → 127.0.0.1:8080
sudo semanage fcontext -a -t httpd_sys_content_t '/mnt/a/maip/data/media(/.*)?'
sudo semanage fcontext -a -t httpd_sys_content_t '/mnt/a/maip/distribution(/.*)?'
sudo restorecon -Rv /mnt/a/maip/data/media /mnt/a/maip/distribution

# 3. 화면·로그인·이미지 보기·배포물 받기를 해 본 뒤 — 비어 있어야 한다
sudo ausearch -m avc -ts boot | grep denied

# 4. enforcing
sudo sed -i 's/^SELINUX=.*/SELINUX=enforcing/' /etc/selinux/config && sudo setenforce 1
```

3 에서 `denied` 가 나오면 enforcing 으로 바꾸지 않는다(permissive 는 기록만 하고 막지 않는다). `setenforce 0`·SELinux 끄기로 풀지 않는다.

---

## 7. 로그 · 백업

### 로그

| 무엇 | 어디 |
|---|---|
| 앱 로그(웹·워커, 오류 스택 트레이스 포함) | `/mnt/a/maip/logs/app-YYYY-MM-DD.log` — 날짜별 분리·보존 삭제를 앱이 한다(logrotate 걸지 않는다) |
| gunicorn · 워커 표준 출력 | `journalctl -u maip` · `journalctl -u maip-worker` |
| nginx 접근 | `/var/log/nginx/access.log` |

화면 "시스템 로그"(DB)는 한 줄 요약이고 트레이스는 앱 로그에 있다. 실패 찾기: `grep -E ' (WARNING|ERROR) ' /mnt/a/maip/logs/app-$(date +%F).log`.

### 백업

이미지는 DB 가 아니라 파일이다 — **DB 와 파일을 같은 시점으로** 백업한다. 방식은 아직 정하지 않았다(DB 담당자 백업인지, 이 서버에서 할지).
이 서버에서 하려면 `pg_dump` 가 DB 서버(16)보다 낮으면 거부되므로 `sudo dnf module enable -y postgresql:16 && sudo dnf install -y postgresql` 로 16 클라이언트를 받는다.

| 대상 | 이유 |
|---|---|
| PostgreSQL DB (`pg_dump -Fc`) | 메타데이터·라벨·권한·이력 |
| `/mnt/a/maip/data` | 업로드 원본·썸네일·Overlay·Export — DB 행이 가리키는 파일 |
| `/mnt/a/maip/distribution` | git 에 없다. LGPL 대응 소스는 3년 보존 의무(§8-1) |
| `.env` | 비밀이 있다 — 다른 백업과 분리해 접근을 제한한다 |

복구 리허설: 받은 백업을 다른 곳에 실제로 복구해 로그인·이미지 표시까지 본다.

---

## 8. Client · Wezard 연결

`/api/v1` 은 비전검사 클라이언트(현장 PC 프로그램)가 부르는 API 다. 경로·응답의 정본은 계약 client/SERVER_API_CONTRACT.md 다 — 바꾸면 함께 고쳐 전달한다.

| 구분 | 인증 |
|---|---|
| `GET /api/v1/health` · 배포물 4경로 | 없음(접근 범위는 서버 밖에서 막는다, §8-1) |
| 나머지 `/api/v1/...` | `X-Client-ID` + `X-API-Key` — 없으면 `AUTH_REQUIRED`, 틀리면 `AUTH_INVALID` |
| Wezard 가 부르는 `/api/v1/datasets/...` | `X-API-Key` 하나(`maip_…`) |

- **Client 등록:** 화면 "비전검사 클라이언트 관리"에서 등록하면 API Key 가 **한 번만** 보인다(해시만 저장, 분실하면 재발급). 현장 PC 의 Client 등록 화면에 Client ID·Key 를 넣는다
- **Client 가 붙는 주소:** 배포본 `config\config.json` 의 `server.base_url`(예: `{"server": {"base_url": "http://<ALB 주소>"}}`). 배포본은 빌드할 때의 주소를 담아 오므로
  운영 주소로 빌드한 판을 `client/` 에 둔다(§8-1). 그 전에 시험할 때만 손으로 바꾼다
- **Wezard 연동:** 서버끼리 직접 잇는다 — `ai-api.yest.co.kr`(관리자 화면, §5)도 ALB 도 거치지 않는다.
  ① `.env` 에 `WEZARD_BASE_URL=http://172.16.10.6:8000`·`WEZARD_API_KEY`(Wezard 관리자 발급) → `restart maip` ② Wezard 가 우리를 부를 연동 키를 발급해 전달한다(§8-2)
  ③ Wezard 쪽 — 우리 주소 `http://maip-web.yest.co.kr`, GPU 서버 `/etc/hosts` 에 `10.0.10.6 maip-web.yest.co.kr`(nginx `maip.conf` 가 `/api/v1/datasets/` 를 172.16.10.6 에만 연다). ACG 가 172.16.10.6 → 10.0.10.6:80 을 허용하는지 본다 ④ 비전검사항목 관리 상세의 AI 모델 칸에서 Wezard 배포 모델을 골라 매핑 → 검사 1건이 "판정 완료"인지 본다

`/api/v1/health` 는 DB(`SELECT 1`)·저장소(쓰기·삭제)를 보고, 하나라도 실패하면 **503** `status: "degraded"` 다. 감시는 본문의 `components` 를 본다.

### 8-1. 배포물 반입 · 교체

근거: DECISIONS DEC-024. `DISTRIBUTION_ROOT` 의 두 폴더 바로 아래 파일을 **인증 없이** 목록·다운로드로 내준다(LGPL 대응 — 인증을 걸지 않는다).
전송·Range 이어받기는 nginx 가 한다. 내부망 한정은 서버 밖(ACG·방화벽)에서 지킨다.

| 폴더 | 내용 |
|---|---|
| `licenses/` | `SHA256SUMS.txt`, `pyside-setup-everywhere-src-6.11.2.tar.xz`, `qt-everywhere-src-6.11.2.tar.xz`(약 1GB) |
| `client/` | `SHA256SUMS.txt`, `VisionInspectionClient-<버전>.zip` — 최신 하나만 |

```bash
# 저장소 distribution/ 과 같은 모양(licenses/·client/)으로 /home/yhan/distribution 에 바이너리 모드로 올린 뒤
cp -r /home/yhan/distribution/licenses/. /mnt/a/maip/distribution/licenses/
cp -r /home/yhan/distribution/client/.   /mnt/a/maip/distribution/client/
for d in licenses client; do       # 배포된 소스의 SHA256SUMS.txt 로 대조한다
    cp /opt/yest/maip/distribution/$d/SHA256SUMS.txt /mnt/a/maip/distribution/$d/
    (cd /mnt/a/maip/distribution/$d && sha256sum -c SHA256SUMS.txt)
done
rm -r /home/yhan/distribution      # 대조 뒤 — / 디스크에 1GB 를 두 번 두지 않는다
```

- **Client 교체:** 새 zip 과 `SHA256SUMS.txt` 를 `client/` 에 넣고 옛 zip 을 뺀다. `sha256sum -c` 와 요청서의 크기·해시로 대조하고, zip 에 `.env`·인증서·API Key 가 없는지 본다.
  서버는 재시작하지 않는다. 저장소에는 `SHA256SUMS.txt` 만 커밋하고 계약 문서를 고쳐 전달한다
- 반입한 zip 은 관리자 화면 비전검사 클라이언트 관리 › [배포본 받기]에서도 받는다
- 이 폴더에 자동 삭제가 닿지 않게 한다 — LGPL 대응 소스는 **마지막 배포 후 3년** 보존이다
- 이 경로는 Client 배포본의 LGPL 고지문에 박혀 있다 — host·port·경로를 바꾸기 **전에** Client 담당에게 알린다
- 넣어도 되는 파일·파일명·`SHA256SUMS.txt` 형식은 저장소 distribution/README.md 가 정본이다

### 8-2. Wezard 연동 키

근거: DECISIONS DEC-029. Wezard 가 `/api/v1/datasets` 를 부를 때 쓰는 키(`maip_…`)다. 화면 없이 관리 명령 `integration_key` 로 다룬다.
반대 방향 키 `WEZARD_API_KEY`(Wezard 관리자가 발급해 우리 `.env` 에 넣는다)와 다르다.

```bash
cd /opt/yest/maip
# 발급 — 원문은 권한 600 파일에만 쓰고 화면에는 끝 4자리만 보인다. DB 에는 SHA-256 해시만 남는다
$PY manage.py integration_key issue WEZARD --name "Wezard 학습 플랫폼" --output /var/lib/maip/wezard_key.txt
sudo cat /var/lib/maip/wezard_key.txt      # 원문을 Wezard 담당자에게 전달한다(/var/lib/maip 는 maip 전용 700)
sudo rm /var/lib/maip/wezard_key.txt       # 전달했으면 지운다
$PY manage.py integration_key list         # WEZARD  Wezard 학습 플랫폼  사용  최근 접속 -
```

- **발급한 서버의 DB 에서만 맞는다.** 개발 서버에서 발급한 키는 운영에서 401 이다 — 운영 키는 운영 서버에서 발급한다
- **전달:** 메일·메신저에 원문이 남지 않는 경로로 준다. Wezard 는 환경 변수 `MAIP_API_KEY` 에만 둔다(Wezard/maip-api.md)
- **확인:** GPU 서버(172.16.10.6)에서 `curl -s -H "X-API-Key: $MAIP_API_KEY" "http://maip-web.yest.co.kr/api/v1/datasets/snapshots?limit=1"` 이 200 이면
  `list` 의 최근 접속에 시각이 찍힌다
- **재발급:** 새거나 잃어버리면 `$PY manage.py integration_key reissue WEZARD --output /var/lib/maip/wezard_key.txt` 뒤 위처럼 전달·삭제한다.
  이전 키는 바로 무효라 Wezard 가 새 키를 넣을 때까지 스냅샷을 받지 못한다
- **폐기:** 연동을 끊을 때 `$PY manage.py integration_key revoke WEZARD` — 행은 남고 그 키의 요청은 401 이다. 다시 쓰려면 `reissue`

---

## 9. 점검 목록

**설치·배포 직후**

- [ ] `maip`·`maip-worker` active, `maip` enabled. `127.0.0.1:8080` 에만 LISTEN
- [ ] `check --deploy` 경고가 §3 끝과 같다. `verify_menu`·`verify_permission_map` PASS
- [ ] 경로·소유자·권한이 §1 표와 같다 — `deploy/check_rocky.sh` 로 한 번에 본다(소스 안 권한·`maip` 읽기/쓰기·nginx `.env` 못 읽음까지)
- [ ] `.env`: `DEBUG=False`, 비밀값 운영값, `ALLOWED_HOSTS`·`CSRF_TRUSTED_ORIGINS` 가 접속 주소, `API_AUTHZ_MODE=enforce`, `TENANT_RLS_ENABLED=True`, 쓰지 않는 `WEZARD_*` 는 비어 있다
- [ ] DB 계정이 superuser·`BYPASSRLS` 가 아니다(§2-2)
- [ ] ALB 대상 healthy, 접근 로그에 ALB 노드의 `444` 가 쌓이지 않는다. 접근 로그 첫 칸이 접속 PC 주소(realip)
- [ ] firewalld 는 `http` 만, 서버 80 은 ALB 대역에서만(ACG)
- [ ] `GET /api/v1/health` 200(`components` 둘 다 `ok`). 로그인 → 좌측 메뉴 → 화면이 탭으로 뜬다. 화면 문구가 한글(다국어 SQL)
- [ ] `/mnt/a/maip/logs` 에 오늘 날짜 로그가 생긴다
- [ ] 파이프라인 점검을 했으면 정리했다(§2-9)

**운영 전에 한 번**

- [ ] 메뉴 권한 화면에서 그룹마다 메뉴 R·W 를 준다(예시 FEATURES §2). Client 마다 API Key 발급
- [ ] 스냅샷 하나를 Export 해 워커가 zip 을 만들고 받아지는지
- [ ] `GET /api/v1/licenses/sources` 200, 항목 3개, tar.xz 의 `sha256` 이 `null` 이 아니다
- [ ] 파일 전송(`FILE_ACCEL_REDIRECT`): `curl -s -D - -o /dev/null .../api/v1/client-packages/<zip>`(이 경로는 HEAD 가 405)에 `X-Accel-Redirect` 가 **안 보이고**
      `Content-Length` 가 파일 크기, `curl -r 0-0` 이 206, `curl -r 0-1,5-6` 이 200 전체, `curl -C -` 이어받기 뒤 `sha256sum -c` 통과
- [ ] 로그인 잠금: 같은 아이디로 틀린 비밀번호 5번 → 잠금. `X-Forwarded-For` 를 바꿔 보내도 잠겨 있다
- [ ] 서버 시간대 Asia/Seoul·NTP 동기화(`timedatectl`) — 앱은 `USE_TZ = False` 라 서버 시각이 그대로 기록된다
- [ ] 감시(서비스 다운·health 실패·디스크)와 백업·복구 리허설(§7)을 정했다

---

## 10. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| 개발 PC `build_package.sh` — `fatal: … 인증이 실패했습니다` | 원격 인증이 없다(§0) | 커밋을 지정한다: `deploy/build_package.sh <커밋>` |
| 개발 PC `build_package.sh` 에서 wheel 을 못 받는다(`versions: none`) | pip 설정에 다른 저장소(extra-index-url)가 있다 | `PIP_CONFIG_FILE=/dev/null deploy/build_package.sh` |
| `deploy.sh` — `/usr/bin/env: 'bash\r'` · 해시 대조 실패 | 텍스트 모드로 옮겼다 | 바이너리 모드로 다시 올린다 |
| `deploy.sh` — `.env 가 없습니다` · `static 이 없습니다` · `rsync 가 없습니다` | 처음 설치 준비가 빠졌다 | §2-3 · §2-1 |
| DB 접속 `password authentication failed` / `no pg_hba.conf entry`·시간 초과 | `.env` 계정·비밀번호 / DB 쪽이 앱 서버 IP 를 허용하지 않는다 | `.env` 확인 / DB 담당자에게 허용 요청(§2-2) |
| 화면 문구가 라벨 코드로 보인다 | 다국어 SQL 을 넣지 않았다 | §2-4 |
| PC 에서 ALB 주소가 **503** | ALB 대상 unhealthy(접근 로그에 ALB 노드의 `GET / … 444` 가 30초마다) | 헬스체크 경로 `/lb-health`(§2-6) |
| **400** Bad Request · 앱 로그 `DisallowedHost` | Host 가 `ALLOWED_HOSTS` 에 없다 | 접속 주소를 `ALLOWED_HOSTS` 에. 모르는 Host(`www` 등)로 찌르는 요청은 nginx 기본 server 가 끊는다(§4) |
| 로그인·저장이 **403** CSRF | `CSRF_TRUSTED_ORIGINS` 가 주소창과 다르다 | 스킴·호스트를 같게, 포트·끝의 `/` 없이(§2-3) |
| HTTPS 로 바꾼 뒤 무한 리다이렉트 | nginx 가 `X-Forwarded-Proto` 를 http 로 넘긴다 | §5 의 `map` |
| `nginx -t` — `could not build server_names_hash` | ALB 주소가 길다(§4) | `server_names_hash_bucket_size 128;` |
| `nginx -t` — `duplicate default server` | Rocky 기본 `nginx.conf` 의 80 server 블록 | 그 블록을 지운다(§2-6) |
| 서버 안에서 ALB 주소로 `curl` 이 멈춘다 | 서버가 외부 인터넷으로 못 나간다 — 정상 | `curl -H 'Host: <ALB 주소>' http://127.0.0.1/...`. ALB 경유 확인은 PC 에서 |
| 한 사람의 로그인 실패로 모두 잠긴다 · 접근 로그가 전부 ALB 주소 | realip 가 없거나 대역이 틀렸다 · ALB 가 `X-Forwarded-For` 를 안 넘긴다 | `set_real_ip_from` 을 ALB 대역으로(§4) |
| **502** | gunicorn 이 죽었다 · (SELinux 를 켰으면) nginx 가 8080 에 못 붙는다 | `systemctl status maip`, `journalctl -u maip` · `setsebool -P httpd_can_network_connect 1`(§6) |
| 이미지·배포물이 안 보인다(403·404·빈 응답) | nginx ACL · (SELinux 를 켰으면) 폴더 컨텍스트 · `/_protected/` 설정 없이 `FILE_ACCEL_REDIRECT=True` | §2-6 ACL · §6 · §4 |
| 모든 화면이 빈 탭 | `X-Frame-Options DENY` 를 덮었다 | 그 줄을 지운다(§4 지킬 것 1) |
| 업로드가 413 | 한 요청 합계가 `client_max_body_size` 를 넘는다 | §4 업로드 크기 |
| 스냅샷 Export 가 계속 대기 | 워커가 안 돈다 | `systemctl status maip-worker` |
| Wezard 스냅샷 요청이 **401** `AUTH_REQUIRED`·`AUTH_INVALID` | 키 헤더가 없다 · 다른 서버에서 발급한 키, 재발급 전 키, 폐기한 키 | `integration_key list` 로 사용 여부를 보고 필요하면 재발급(§8-2) |
| Wezard 스냅샷 요청이 nginx **403** · 연결 시간 초과 | 172.16.10.6 이 아닌 곳에서 왔다(ALB 경유 등) · ACG 가 172.16.10.6 → 10.0.10.6:80 을 막는다 | GPU 서버 `/etc/hosts`(§8) · ACG 허용 요청 |
| 앱이 루트 디스크에 데이터를 쓴다 | `/mnt/a` 가 붙지 않은 채 부팅(fstab `nofail`) | 디스크 확인 뒤 재시작. 유닛에 `RequiresMountsFor=/mnt/a` 를 검토한다 |

---

## 11. 확인 필요

정해지면 이 문서와, Client 에 영향이 있으면 계약 문서도 함께 고친다.

| 항목 | 누가 | 왜 |
|---|---|---|
| TLS 인증서 방식 · 전환 일정 · LGPL 소스 사외 공개와 3년 보존 주체 · `/api/v1` 인증 실패 rate limit | 인프라 · 법무 · Client | Client 변경·재빌드가 걸린다 |
| 운영 데이터 규모(검사 건수/일, 이미지 크기) | 현장 | 디스크 산정. 보존정책이 없어 그대로 쌓인다 |
| Client 대수 | 현장 | 발급할 API Key 수 |
| 한 번에 올리는 업로드 합계 | 현장 | `client_max_body_size`·`--timeout` 산정(§4) |
| 백업 방식 | 운영 · DB 담당 | §7 |
