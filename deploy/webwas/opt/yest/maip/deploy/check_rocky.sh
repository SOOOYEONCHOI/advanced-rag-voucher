#!/usr/bin/env bash
# 운영 서버(Rocky Linux 9.6) 점검 — 조회만 하고 아무것도 바꾸지 않는다. 기준은 docs/DEPLOYMENT.md §1·§2·§6.
# 관리 계정(yhan)으로 실행한다. sudo 비밀번호를 한 번 묻는다. 비밀값(.env 의 키·비밀번호)은 출력하지 않는다.
#   bash check_rocky.sh 2>&1 | tee check_rocky.txt
set -u

SRC=/opt/yest/maip
VENV=/opt/envs/maip
DATA=/mnt/a/maip/data
LOGS=/mnt/a/maip/logs
DIST=/mnt/a/maip/distribution
ENVF=$SRC/.env

sec() { printf '\n===== %s\n' "$*"; }
run() { printf '$ %s\n' "$*"; bash -c "$*" 2>&1; echo "[exit $?]"; }
envv() { sudo grep -E "^$1=" "$ENVF" 2>/dev/null | tail -1 | cut -d= -f2-; }

sudo -v || exit 1

sec "1. OS · 아키텍처 · 시간"
run "grep -E '^(NAME|VERSION_ID)=' /etc/os-release"
run "uname -m; ldd --version | head -1"
run "timedatectl | grep -E 'Time zone|synchronized|NTP'"

sec "2. Python · 패키지"
run "command -v python3.12 && python3.12 -V; python3 -V"
run "rpm -q python3.12 python3.12-pip nginx postgresql acl policycoreutils-python-utils"
run "timeout 60 dnf -q module list --enabled postgresql 2>/dev/null | grep -i postgresql"
run "pg_dump --version; nginx -v"
run "$VENV/bin/python -V && $VENV/bin/pip -V"
run "$VENV/bin/pip list --format=freeze 2>/dev/null | grep -iE '^(django|pillow|psycopg|psycopg-binary|gunicorn|whitenoise|packaging|openpyxl)=='"
run "$VENV/bin/pip check"

sec "3. 네트워크 — PyPI(인터넷)·DB"
run "curl -sS -o /dev/null -w 'pypi %{http_code}\n' --max-time 10 https://pypi.org/simple/pip/"
DBH=$(envv DB_HOST); DBP=$(envv DB_PORT)
run "timeout 5 bash -c '</dev/tcp/${DBH:-127.0.0.1}/${DBP:-5432}' && echo 'DB ${DBH:-127.0.0.1}:${DBP:-5432} 연결됨'"

sec "4. 계정"
run "id maip; id yhan; id nginx"
run "getent passwd maip"

sec "5. 경로 · 소유자 · 권한 (§2 표)"
run "sudo stat -c '%A %a %U:%G %n' $SRC $VENV $SRC/static $DATA $LOGS $DIST $DIST/licenses $DIST/client /var/lib/maip $ENVF /etc/systemd/system/maip.service /etc/systemd/system/maip-worker.service"
run "sudo namei -l $DATA/media; sudo namei -l $DIST/client"
run "df -h / /mnt/a"
run "findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS /mnt/a"
run "ls -lt $HOME/dist 2>/dev/null | head -6"   # 가장 최근 maip-<커밋>.tar.gz 가 지금 배포본(DEPLOYMENT §0)
run "ls $VENV/wheels 2>/dev/null | wc -l"
# 소스 안 — 다른 계정 권한·그룹 쓰기·그룹 maip 가 아닌 것, 파일 640·750 이 아닌 것(출력 없으면 정상)
run "sudo find $SRC -path $SRC/static -prune -o ! -type l \( -perm /o=rwx -o -perm /g=w -o ! -group maip \) -print | head"
run "sudo find $SRC -path $SRC/static -prune -o -type f ! -perm 640 ! -perm 750 -print | head"
run "sudo -u maip test -r $ENVF && echo 'maip: .env 읽기 됨'; sudo -u maip test -w $SRC/manage.py && echo '경고: maip 가 소스를 고칠 수 있다' || echo 'maip: 소스 쓰기 불가(정상)'"
run "sudo -u maip test -w $DATA && sudo -u maip test -w $LOGS && echo 'maip: 데이터·로그 쓰기 됨'"

sec "6. .env — 비밀이 아닌 값만, 비밀은 설정 여부만"
for k in DEBUG ALLOWED_HOSTS CSRF_TRUSTED_ORIGINS HTTPS_ENABLED DB_HOST DB_PORT DB_NAME DB_USER DB_CONN_MAX_AGE \
         STORAGE_ROOT LOG_DIR DISTRIBUTION_ROOT FILE_ACCEL_REDIRECT API_AUTHZ_MODE TENANT_RLS_ENABLED WEZARD_BASE_URL; do
    printf '%s=%s\n' "$k" "$(envv $k)"
done
for k in SECRET_KEY DB_PASSWORD WEZARD_API_KEY; do
    v=$(envv $k); printf '%s=%s\n' "$k" "$([ -n "$v" ] && echo '(설정됨)' || echo '(비어 있음)')"
done

sec "7. SELinux"
run "getenforce; sestatus | grep -E 'status|mode|policy name'"
run "getsebool httpd_can_network_connect"
run "sudo semanage fcontext -l -C | grep /mnt/a/maip"
run "ls -Zd $DATA/media $DIST $DIST/client $SRC/static"

sec "8. ACL — nginx 는 두 폴더만 읽는다"
run "sudo getfacl -p /mnt/a/maip $DATA $DATA/media $DIST 2>&1 | grep -vE '^$'"
run "sudo -u nginx test -r $DIST/client && echo 'nginx: distribution 읽기 됨'"
run "sudo -u nginx test -r $DATA/media && echo 'nginx: media 읽기 됨'"
run "sudo -u nginx test -r $ENVF && echo '경고: nginx 가 .env 를 읽는다' || echo 'nginx: .env 못 읽음(정상)'"

sec "9. 방화벽 · 열린 포트"
run "systemctl is-active firewalld; sudo firewall-cmd --list-services; sudo firewall-cmd --list-ports"
run "sudo ss -ltnp | grep -E ':(80|443|8080) '"

sec "10. systemd"
run "systemctl is-enabled maip maip-worker; systemctl is-active maip maip-worker"
run "systemctl show -p User -p WorkingDirectory -p UMask -p ExecStart maip maip-worker | sed 's/ ; .*//'"
run "systemctl show -p Wants maip | tr ' ' '\n' | grep maip; systemctl show -p PartOf maip-worker"
run "sudo journalctl -u maip -u maip-worker -n 30 --no-pager"

sec "11. nginx"
run "sudo nginx -t"
run "ls /etc/nginx/conf.d/"
run "sudo grep -rnE 'proxy_pass|alias|internal|client_max_body_size|proxy_read_timeout|X-Frame-Options' /etc/nginx/conf.d/"
# ALB 뒤 설정(§6) — 앱 주소 server_name·기본 server(444·헬스체크)·realip·Wezard 허용
run "sudo grep -rnE 'server_name|bucket_size|default_server|lb-health|set_real_ip_from|real_ip_|allow |deny ' /etc/nginx/conf.d/"
run "curl -sS --max-time 5 http://127.0.0.1/lb-health"
run "sudo tail -n 5 /var/log/nginx/access.log"   # 첫 칸이 ALB 노드가 아니라 접속 PC 주소(realip), ALB 노드의 444 줄 없음

# 이 절만 예외로 쓴다 — 설정을 읽는 순간 STORAGE_ROOT 아래 폴더(없으면)와 LOG_DIR 로그 줄이 생긴다. 서비스 계정 소유라 그대로 둬도 된다
sec "12. 앱 — 서비스 계정으로 설정 점검"
run "cd $SRC && sudo -u maip $VENV/bin/python manage.py check --deploy"
run "cd $SRC && sudo -u maip $VENV/bin/python scripts/verify/verify_menu.py | tail -3"
run "cd $SRC && sudo -u maip $VENV/bin/python scripts/verify/verify_permission_map.py | tail -3"
HOST=$(envv ALLOWED_HOSTS | cut -d, -f1)
run "curl -sS --max-time 10 -H 'Host: ${HOST:-localhost}' http://127.0.0.1:8080/api/v1/health"

sec "13. 로그 · SELinux 거부"
run "sudo ls -l $LOGS | tail -5"
run "sudo grep -cE ' (WARNING|ERROR) ' $LOGS/app-\$(date +%F).log"
run "sudo grep -c denied /var/log/audit/audit.log; sudo grep denied /var/log/audit/audit.log | tail -10"

sec "끝"
