#!/usr/bin/env bash
# WAS 배포 — 관리 계정(sychoi)으로, 묶음을 올린 폴더(/mnt/a/chatbot/offline)에서:
#   ./deploy.sh [--backend-only | --frontend-only] [chatbot-<버전>.tar.gz]
# 묶음을 주지 않으면 이 폴더에 가장 최근에 올린 chatbot-*.tar.gz 를 쓴다. 이전 묶음을 주면 그 소스·프런트·이미지로 되돌린다.
# 대조 → 풀기 → (런타임 이미지 load) → 소스·프런트 교체(.env·데이터 보존) → compose.env 이미지 태그 → alembic upgrade head → 점검
# 2026.11.02(sooyeon.choi) 추가 - 교체 범위 옵션. 기본값은 둘 다 교체(기존과 같음)
#   --backend-only   런타임 이미지·backend 소스·compose.env 태그·DB 스키마만. 프런트는 그대로
#   --frontend-only  프런트만. backend·이미지·DB 는 그대로(마이그레이션·restart 필요 없음)
#   적용 기록은 /opt/yest/chatbot/DEPLOYED 에 한 줄씩 남는다(지금 운영의 backend·프런트 판 확인용)
# 2026.11.04(sooyeon.choi) 추가 - 교체 전에 항상 /mnt/a/chatbot/backup/<시각>_<범위>/ 로 백업(RESTORE.txt 에 되돌리는 명령)
# 서비스는 다시 시작하지 않는다 — 끝나면 sudo systemctl restart chatbot (--frontend-only 는 필요 없음)
# 되돌릴 때 DB 를 이미 새 판으로 올렸으면 SKIP_MIGRATE=1 ./deploy.sh <이전 묶음> (downgrade 는 §4.6 되돌리기)
# 설명: docs/design/운영배포_수정배포_가이드_v1.1.md §4.3·§4.6
set -euo pipefail
cd "$(dirname "$0")"

BASE=/opt/yest/chatbot
SRC=$BASE/backend
WEB=$BASE/frontend
DATA=/mnt/a/chatbot/data
DC="sudo docker compose --env-file $BASE/compose.env -f $BASE/docker-compose.prod.yml"

MODE=all
TAR=""
for arg in "$@"; do
    case "$arg" in
        --backend-only)  [ "$MODE" = all ] || { echo "--backend-only 와 --frontend-only 는 함께 쓸 수 없습니다." >&2; exit 1; }; MODE=backend ;;
        --frontend-only) [ "$MODE" = all ] || { echo "--backend-only 와 --frontend-only 는 함께 쓸 수 없습니다." >&2; exit 1; }; MODE=frontend ;;
        -*) echo "모르는 옵션: $arg (쓸 수 있는 것: --backend-only, --frontend-only)" >&2; exit 1 ;;
        *) TAR=$arg ;;
    esac
done
DO_BE=1; DO_FE=1
[ "$MODE" = backend ] && DO_FE=0
[ "$MODE" = frontend ] && DO_BE=0

TAR=${TAR:-$(ls -t chatbot-*.tar.gz 2>/dev/null | head -1)}
[ -n "$TAR" ] && [ -f "$TAR" ] || { echo "chatbot-*.tar.gz 가 없습니다." >&2; exit 1; }
NAME=$(basename "$TAR" .tar.gz)
command -v rsync >/dev/null || { echo "rsync 가 없습니다 — sudo dnf install -y rsync" >&2; exit 1; }
for f in "$BASE/.env" "$BASE/compose.env" "$BASE/docker-compose.prod.yml"; do
    [ -f "$f" ] || { echo "$f 가 없습니다 — 서버별 가이드 §4.3 ⑦로 먼저 만듭니다." >&2; exit 1; }
done
grep -q '^RUNTIME_IMAGE=' "$BASE/compose.env" || { echo "$BASE/compose.env 에 RUNTIME_IMAGE= 줄이 없습니다." >&2; exit 1; }
# 마운트 원본·데이터 폴더 — 없으면 만든다(있으면 그대로). 없으면 Docker 가 root 소유로 만들어 앱이 쓰지 못한다
# 2026.11.13(sooyeon.choi) 수정 - 시트 미리보기 작업 폴더(sheet_preview, .env SHEET_PREVIEW_WORK_ROOT=/data/sheet_preview) 추가
sudo install -d -o chatbot -g chatbot -m 750 "$DATA"/{data,xl_res,parsed_md,chunk,db,manual_display,migrate,sheet_preview} /mnt/a/chatbot/logs /mnt/a/chatbot/cache

echo "== 0. 묶음 $TAR (교체 범위: $MODE)"
sha256sum -c "$TAR.sha256"
rm -rf "$NAME"
tar -xzf "$TAR"
(cd "$NAME" && sha256sum -c --quiet SHA256SUMS)
RUNTIME_IMAGE=$(cat "$NAME/RUNTIME_IMAGE")
head -1 "$NAME/VERSION"

# 2026.11.04(sooyeon.choi) 추가 - 교체 전 백업(항상). 교체할 쪽만 $BACKUP_ROOT/<시각>_<범위>/ 에 담는다
#   프런트: frontend.tar.gz / backend: backend.tar.gz(instance/ 제외) + compose.env(이미지 태그) / 공통: DEPLOYED 마지막 줄들
#   되돌리는 명령은 그 폴더의 RESTORE.txt. 오래된 백업은 최근 BACKUP_KEEP 개(기본 10)만 남긴다. DB 는 백업하지 않는다
BACKUP_ROOT=/mnt/a/chatbot/backup
BACKUP_KEEP=${BACKUP_KEEP:-10}
BK=$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)_$MODE
echo "== 0-1. 백업 $BK"
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 750 "$BACKUP_ROOT"
mkdir -p "$BK"
[ -f "$BASE/DEPLOYED" ] && tail -5 "$BASE/DEPLOYED" > "$BK/DEPLOYED.tail"
if [ "$DO_FE" = 1 ] && [ -d "$WEB" ] && [ -n "$(ls -A "$WEB")" ]; then
    tar -C "$BASE" -czf "$BK/frontend.tar.gz" frontend
fi
if [ "$DO_BE" = 1 ]; then
    if [ -d "$SRC" ] && [ -n "$(ls -A "$SRC")" ]; then
        tar -C "$BASE" --exclude=backend/instance -czf "$BK/backend.tar.gz" backend
    fi
    cp -p "$BASE/compose.env" "$BK/compose.env"
fi
cat > "$BK/RESTORE.txt" <<EOF
# $(date '+%Y-%m-%d %H:%M:%S') $NAME ($MODE) 적용 직전 백업 — 되돌리기(sychoi)
# 백업에 있는 파일만 해당. 권한은 deploy.sh 와 같은 rsync 방식으로 폴더 설정을 물려받는다
R=\$(mktemp -d) && cd "\$R"
# 프런트 (restart 필요 없음, 브라우저 Ctrl+F5)
tar -xzf $BK/frontend.tar.gz && rsync -rlt --delete frontend/ $WEB/ && find $WEB -user \$(id -un) -exec chmod g+rX,g-w,o-rwx {} +
# backend (DB 를 새 판으로 올렸으면 먼저 수정배포 가이드 §4.6 의 alembic downgrade)
tar -xzf $BK/backend.tar.gz && rsync -rlt --delete --exclude /instance/ backend/ $SRC/ && find $SRC -user \$(id -un) -exec chmod g+rX,g-w,o-rwx {} +
cp $BK/compose.env $BASE/compose.env && sudo systemctl restart chatbot
cd / && rm -rf "\$R"
EOF
ls -lh "$BK"
# 오래된 백업 정리 — 이 스크립트가 만든 이름(YYYYMMDD-HHMMSS_범위)만 대상
ls -1d "$BACKUP_ROOT"/[0-9]*-[0-9]*_* 2>/dev/null | sort -r | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -rf

if [ "$DO_BE" = 1 ]; then
    echo "== 1. 런타임 이미지 $RUNTIME_IMAGE"
    if sudo docker image inspect "$RUNTIME_IMAGE" >/dev/null 2>&1; then
        echo "서버에 이미 있어 그대로 씁니다"
    else
        IMG=$(ls "$NAME"/image/*.tar.gz 2>/dev/null | head -1 || true)
        [ -n "$IMG" ] || { echo "서버에 $RUNTIME_IMAGE 가 없고 묶음에도 이미지가 없습니다 — 개발 PC 에서 --with-image 로 다시 만듭니다." >&2; exit 1; }
        sudo docker load -i "$IMG"
    fi

    echo "== 2. backend 소스"
    # 그룹은 폴더의 setgid(chatbot)를 따른다. instance/ 는 마운트 자리(manual_display)만 둔다
    rsync -rlt --delete --exclude /instance/ "$NAME/backend/" "$SRC/"
    mkdir -p "$SRC/instance/manual_display"
    find "$SRC" -user "$(id -un)" -exec chmod g+rX,g-w,o-rwx {} +
else
    echo "== 1·2. 런타임 이미지·backend 소스 — 건너뜁니다(--frontend-only)"
fi

if [ "$DO_FE" = 1 ]; then
    echo "== 3. 프런트"
    # nginx 읽기 권한은 폴더의 기본 ACL(서버별 가이드 §4.3 ⑪)을 새 파일이 물려받는다
    rsync -rlt --delete "$NAME/frontend/" "$WEB/"
    find "$WEB" -user "$(id -un)" -exec chmod g+rX,g-w,o-rwx {} +
else
    echo "== 3. 프런트 — 건너뜁니다(--backend-only)"
fi

if [ "$DO_BE" = 1 ]; then
    echo "== 4. compose.env 이미지 태그"
    sed -i "s|^RUNTIME_IMAGE=.*|RUNTIME_IMAGE=$RUNTIME_IMAGE|" "$BASE/compose.env"
    $DC config -q

    echo "== 5. DB 스키마"
    if [ "${SKIP_MIGRATE:-0}" = 1 ]; then
        echo "SKIP_MIGRATE=1 — 건너뜁니다"
    else
        $DC run --rm --no-deps backend python init_database.py      # alembic upgrade head (chatbot UID 로)
    fi

    echo "== 6. 점검"
    [ -z "$(ls -A "$SRC/instance" | grep -v '^manual_display$' || true)" ] || { echo "!! $SRC/instance 에 manual_display 말고 다른 것이 있습니다" >&2; exit 1; }
    $DC run --rm --no-deps backend python -c "import app.core.config as c; print('config ok')"
else
    echo "== 4·5·6. 이미지 태그·DB 스키마·backend 점검 — 건너뜁니다(--frontend-only)"
fi

# 설정 파일이 바뀌었으면 알린다(자동으로 덮지 않는다 — 수정배포 가이드 §4.5 표대로 복사)
for pair in "docker-compose.prod.yml:$BASE/docker-compose.prod.yml" \
            "chatbot.service:/etc/systemd/system/chatbot.service" \
            "chatbot.conf:/etc/nginx/conf.d/chatbot.conf"; do
    new=$NAME/config/${pair%%:*}; cur=${pair#*:}
    if ! sudo cmp -s "$new" "$cur"; then echo "알림: $cur 가 묶음의 config/${pair%%:*} 와 다릅니다 — 바꾼 배포면 복사합니다"; fi
done

# 적용 기록: 날짜 묶음 범위 이미지(backend 를 바꿨을 때만) — 지금 운영 판은 tail $BASE/DEPLOYED
printf '%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$NAME" "$MODE" \
    "$([ "$DO_BE" = 1 ] && echo "$RUNTIME_IMAGE" || echo -)" >> "$BASE/DEPLOYED"

echo
if [ "$DO_BE" = 1 ]; then
    echo "배포 준비 끝: $NAME ($MODE) — 다음: sudo systemctl restart chatbot && curl -s http://127.0.0.1:8081/health"
else
    echo "배포 끝: $NAME ($MODE) — restart 필요 없음. 브라우저에서 Ctrl+F5 로 확인"
fi
