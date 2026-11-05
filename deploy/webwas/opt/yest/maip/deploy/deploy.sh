#!/usr/bin/env bash
# 운영 서버 배포 — 관리 계정(yhan)으로, 묶음을 올린 폴더에서: ./deploy.sh [maip-<커밋>.tar.gz]   (docs/DEPLOYMENT.md §0)
# 묶음을 주지 않으면 이 폴더에 가장 최근에 올린 maip-*.tar.gz 를 쓴다. 이전 묶음을 주면 그 소스로 되돌린다(DB 마이그레이션은 되돌리지 않는다).
# 대조 → 풀기 → 소스 교체(.env·static 보존) → wheel 로 의존성(인터넷 없이) → migrate·기본 데이터·collectstatic·점검.
# 서비스는 다시 시작하지 않는다 — 끝나면 sudo systemctl restart maip
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD

SRC=/opt/yest/maip
VENV=/opt/envs/maip
PY="sudo -u maip $VENV/bin/python"

TAR=${1:-$(ls -t maip-*.tar.gz 2>/dev/null | head -1)}
[ -n "$TAR" ] && [ -f "$TAR" ] || { echo "maip-*.tar.gz 가 없습니다." >&2; exit 1; }
NAME=$(basename "$TAR" .tar.gz)
command -v rsync >/dev/null || { echo "rsync 가 없습니다 — sudo dnf install -y rsync" >&2; exit 1; }
[ -f "$SRC/.env" ] || { echo "$SRC/.env 가 없습니다 — DEPLOYMENT §2-3 으로 먼저 만듭니다." >&2; exit 1; }
[ -d "$SRC/static" ] || { echo "$SRC/static 이 없습니다 — DEPLOYMENT §2-1 로 maip 소유로 만듭니다." >&2; exit 1; }

echo "== 0. 묶음 $TAR"
sha256sum -c "$TAR.sha256"
tar -xzf "$TAR"
(cd "$NAME/wheels" && sha256sum -c --quiet SHA256SUMS.txt)

echo "== 1. 소스 $(cut -d' ' -f1 "$NAME/VERSION")"
# 그룹은 폴더의 setgid(maip)를 따른다(-g 를 쓰지 않는다). .env·static(maip 소유)·점검 결과는 건드리지 않는다
rsync -rlt --delete --exclude /.env --exclude /static/ --exclude '/deploy/*.txt' "$NAME/source/" "$SRC/"
find "$SRC" -user "$(id -un)" -exec chmod g+rX,g-w,o-rwx {} +

echo "== 2. 의존성 (인터넷 없이)"
rsync -rlt --delete "$NAME/wheels/" "$VENV/wheels/"
"$VENV/bin/pip" install -q --no-index --find-links "$VENV/wheels" -r "$SRC/requirements.txt"
"$VENV/bin/pip" check

# 기본 데이터가 지난번 seed 때와 다를 때만 그 seed 를 돌린다 — 매번 돌리면 운영에서 지운 기본 항목·양식이 되살아난다.
# 성공한 데이터의 해시를 이 폴더 .seed-<명령> 에 남긴다(중간에 실패해 다시 돌려도 빠지지 않는다)
seed() {
    local cmd=$1 sum
    shift
    sum=$(cd "$SRC" && find "$@" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
    if [ "$sum" = "$(cat "$HERE/.seed-$cmd" 2>/dev/null)" ]; then
        echo "$cmd — 기본 데이터가 그대로라 건너뜁니다"
        return
    fi
    $PY manage.py "$cmd"
    echo "$sum" > "$HERE/.seed-$cmd"
}

echo "== 3. DB·기본 데이터·정적 파일·점검 (서비스 계정으로)"
cd "$SRC"
$PY manage.py migrate --noinput
$PY manage.py seed_initial                 # 메뉴 변경 반영. 관리자 비밀번호는 건드리지 않는다
seed seed_vision_items domain/management/commands/seed_vision_items.py
seed seed_dig_form domain/management/samples/dig_form_forms.json domain/management/samples/dig_form_images
$PY manage.py collectstatic --noinput
$PY manage.py check --deploy
$PY scripts/verify/verify_menu.py
$PY scripts/verify/verify_permission_map.py

echo
echo "배포 준비 끝: $NAME — 다음: sudo systemctl restart maip"
