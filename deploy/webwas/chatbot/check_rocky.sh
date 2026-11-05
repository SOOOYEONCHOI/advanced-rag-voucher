#!/usr/bin/env bash
# WAS 상태 점검 — 조회만 한다(아무것도 바꾸지 않는다). 관리 계정(sychoi)으로: ./check_rocky.sh > check_$(date +%m%d).txt 2>&1
# 결과 파일에는 주소·비밀이 섞일 수 있다(.env 는 읽지 않지만 nginx·docker 출력에 IP 가 나온다) — 그대로 밖에 붙이지 않는다
# 설명: docs/design/운영배포_가이드_서버별_v1.1.md §4.4
set -u

BASE=/opt/yest/chatbot
DATA=/mnt/a/chatbot
DC="sudo docker compose --env-file $BASE/compose.env -f $BASE/docker-compose.prod.yml"

sec() { echo; echo "===== $*"; }
run() { echo "\$ $*"; bash -c "$*" 2>&1; }

sec "1. OS"
run "cat /etc/rocky-release; uname -r; getenforce; stat -fc %T /sys/fs/cgroup"
run "df -h / /mnt/a"

sec "2. 계정"
run "id sychoi; id chatbot; id nginx"
run "getent passwd chatbot | cut -d: -f6,7"
run "grep -E '^(CHATBOT_UID|CHATBOT_GID)=' $BASE/compose.env"

sec "3. 경로·권한 (소유자·권한이 표와 같아야 한다)"
run "sudo stat -c '%A %U:%G %n' $BASE $BASE/backend $BASE/frontend $BASE/.env $BASE/compose.env $BASE/docker-compose.prod.yml"
run "sudo stat -c '%A %U:%G %n' $DATA $DATA/data $DATA/logs $DATA/cache $DATA/data/manual_display $DATA/offline"
run "sudo find $BASE/backend -maxdepth 1 -perm -o+r -printf '경고: 다른 계정이 읽는다 %p\n' | head"

sec "4. nginx 가 읽는 범위"
run "sudo getfacl -p $BASE $BASE/frontend 2>&1 | grep -vE '^$'"
run "sudo -u nginx test -r $BASE/frontend/index.html && echo 'nginx: 프런트 읽기 됨' || echo '경고: nginx 가 프런트를 못 읽는다'"
run "sudo -u nginx test -r $BASE/.env && echo '경고: nginx 가 .env 를 읽는다' || echo 'nginx: .env 못 읽음(정상)'"
run "sudo -u nginx test -r $BASE/backend/main.py && echo '경고: nginx 가 소스를 읽는다' || echo 'nginx: 소스 못 읽음(정상)'"

sec "5. Docker"
run "docker --version; docker compose version; rpm -q docker-ce docker-ce-cli containerd.io docker-compose-plugin"
run "sudo dnf versionlock list 2>/dev/null | grep -E 'docker|containerd'"
run "sudo docker info 2>/dev/null | grep -Ei 'server version|cgroup version|docker root dir|default address|security options'"
run "sudo cat /etc/docker/daemon.json"
run "sudo docker image ls 'chatbot-backend-runtime'"
run "grep '^RUNTIME_IMAGE=' $BASE/compose.env"

sec "6. 서비스"
run "systemctl is-enabled docker chatbot nginx; systemctl is-active docker chatbot nginx"
run "sudo docker ps --filter name=chatbot_backend --format '{{.Names}} {{.Image}} {{.Status}}'"
run "ss -ltnp 2>/dev/null | grep -E ':(80|8081)\b'"     # 8081 은 127.0.0.1 에만
run "curl -s -m 5 http://127.0.0.1:8081/health"
run "curl -s -m 5 -H 'Host: chatbot.yest.co.kr' http://127.0.0.1/api/health"
run "curl -s -m 5 -o /dev/null -w 'index %{http_code}\n' -H 'Host: chatbot.yest.co.kr' http://127.0.0.1/"
run "curl -s -m 5 -o /dev/null -w 'internal %{http_code} (404 정상)\n' -H 'Host: chatbot.yest.co.kr' http://127.0.0.1/internal/x"

sec "7. 컨테이너 안 실행 계정·마운트"
run "sudo docker exec chatbot_backend id"
run "sudo docker inspect chatbot_backend --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}'"
run "sudo find $DATA/data $DATA/logs -maxdepth 2 ! -user chatbot -printf '경고: chatbot 소유가 아님 %u %p\n' | head"

sec "8. nginx"
run "sudo nginx -t"
run "ls /etc/nginx/conf.d/"
run "sudo grep -nE 'server_name|root |proxy_pass|client_max_body_size|proxy_read_timeout|proxy_buffering' /etc/nginx/conf.d/chatbot.conf"

sec "9. 최근 로그"
run "sudo journalctl -u chatbot -n 20 --no-pager"
run "sudo docker logs --tail 30 chatbot_backend"
run "sudo ls -lt $DATA/logs | head"
