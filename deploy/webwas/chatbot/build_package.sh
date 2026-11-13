#!/usr/bin/env bash
# 개발 PC(WSL)에서 WAS 배포 묶음을 만든다. 저장소 어디서 불러도 된다:
#   deploy/webwas/chatbot/build_package.sh [--with-image] [--skip-frontend-build] [버전]
# 결과(deploy/webwas/mnt/a/chatbot/offline/ — 서버 /mnt/a/chatbot/offline 과 같은 자리): chatbot-<버전>.tar.gz · chatbot-<버전>.tar.gz.sha256 · deploy.sh
# 설명: docs/design/운영배포_수정배포_가이드_v1.1.md §4.1
#
# --with-image          런타임 이미지(docker save)를 묶음에 넣는다. 처음 설치·requirements.txt 를 바꾼 배포에만 쓴다(수 GB)
# --skip-frontend-build 이미 만든 adrag_frontend/dist 를 그대로 쓴다(npm 이 Windows 에만 있을 때)
# 버전을 주지 않으면 날짜-시각(YYYYMMDD-HHMM)으로 한다. VERSION 파일에 svnversion 결과도 남긴다
#
# 소스는 아래 목록만 넣는다(허용 목록). instance/·.env·tests/·원본 문서·이미지는 넣지 않고, 섞이면 멈춘다(CLAUDE.md 절대 규칙 3)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
BE=$ROOT/adrag_backend
FE=$ROOT/adrag_frontend
# 2026.10.30 수정 - 반입 파일을 서버 경로와 같은 구조로 모은다(dist/ → mnt/a/chatbot/offline/)
OUT=$ROOT/deploy/webwas/mnt/a/chatbot/offline

BACKEND_INCLUDE=(main.py init_database.py alembic.ini requirements.txt app excel_ingest migrations scripts)

WITH_IMAGE=0
BUILD_FE=1
VER=""
for arg in "$@"; do
    case "$arg" in
        --with-image) WITH_IMAGE=1 ;;
        --skip-frontend-build) BUILD_FE=0 ;;
        -*) echo "모르는 옵션: $arg" >&2; exit 1 ;;
        *) VER=$arg ;;
    esac
done
VER=${VER:-$(date +%Y%m%d-%H%M)}
NAME=chatbot-$VER
STAGE=$OUT/stage/$NAME

command -v docker >/dev/null || { echo "docker 가 없습니다 — WSL 에서 실행합니다." >&2; exit 1; }
rm -rf "$OUT/stage" && mkdir -p "$STAGE"/{backend,frontend,config,image}

# 런타임 이미지 태그 = requirements.txt + Dockerfile.runtime 해시. 두 파일이 그대로면 서버 이미지를 다시 쓴다
HASH=$(cat "$BE/requirements.txt" "$HERE/Dockerfile.runtime" | sha256sum | cut -c1-12)
RUNTIME_IMAGE=chatbot-backend-runtime:$HASH

echo "== 1. 런타임 이미지 $RUNTIME_IMAGE"
if ! docker image inspect "$RUNTIME_IMAGE" >/dev/null 2>&1; then
    docker build -f "$HERE/Dockerfile.runtime" -t "$RUNTIME_IMAGE" "$BE"
fi
# 네트워크를 끊고 의존성을 불러 본다(8.3 반입 전 검증)
docker run --rm --network none "$RUNTIME_IMAGE" sh -c \
    'pip check && python -c "import fastapi, uvicorn, psycopg, sqlalchemy, alembic, qdrant_client, langgraph, kiwipiepy, openpyxl, pdfplumber, torch, ezdxf, matplotlib; print(\"imports ok\")" \
     && test -x /usr/bin/soffice && /usr/bin/python3 -c "import uno; print(\"uno ok\")" \
     && env -i PATH=/usr/local/bin:/usr/bin:/bin dwg2dxf --version'
# 2026.11.13(sooyeon.choi) 수정 - 도면용 ezdxf·matplotlib·dwg2dxf(앱과 같이 PATH 만 준 환경), 시트 미리보기용 soffice·uno 도 확인

echo "== 2. backend 소스 (허용 목록)"
for item in "${BACKEND_INCLUDE[@]}"; do
    [ -e "$BE/$item" ] || { echo "$BE/$item 가 없습니다." >&2; exit 1; }
done
tar -C "$BE" -cf - \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
    --exclude='app/graphs/workflow-graphs' \
    "${BACKEND_INCLUDE[@]}" | tar -C "$STAGE/backend" -xf -
# 들어가면 안 되는 것이 섞였는지 본다 — 있으면 멈춘다
BAD=$(find "$STAGE/backend" \( -name 'instance' -o -name '.env*' -o -iname '*.db' -o -iname '*.sqlite*' \
      -o -iname '*.xls' -o -iname '*.xlsx' -o -iname '*.xlsm' -o -iname '*.dxf' -o -iname '*.dwg' -o -iname '*.pdf' \
      -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.gif' -o -iname '*.bmp' \
      -o -iname '*.emf' -o -iname '*.wmf' -o -iname '*.wav' -o -iname '*.mp3' \) -print)
[ -z "$BAD" ] || { echo "!! 묶음에 넣으면 안 되는 파일 — 반출 중지:" >&2; echo "$BAD" >&2; exit 1; }

echo "== 3. 프런트"
if [ "$BUILD_FE" = 1 ]; then
    command -v npm >/dev/null || { echo "npm 이 없습니다 — Windows 에서 npm run build 후 --skip-frontend-build 로 다시 실행합니다." >&2; exit 1; }
    (cd "$FE" && npm ci && npm run build)
fi
[ -f "$FE/dist/index.html" ] || { echo "$FE/dist/index.html 이 없습니다." >&2; exit 1; }
cp -a "$FE/dist/." "$STAGE/frontend/"
# public/ 의 개발용 목업은 운영에 올리지 않는다(누구나 /admin-mockup.html 로 열 수 있게 된다)
rm -f "$STAGE/frontend/admin-mockup.html"
# 폐쇄망: 사용자 PC 가 인터넷에 못 나가면 CDN 파일이 깨진다(P-8). 남아 있으면 알린다
if grep -rlE 'https?://(cdnjs\.cloudflare\.com|cdn\.sheetjs\.com|cdn\.jsdelivr\.net|unpkg\.com)' "$STAGE/frontend" --include='*.html' --include='*.js' >/dev/null; then
    echo "!! 경고: 프런트가 외부 CDN 을 부른다(P-8 미해결) — 폐쇄망에서 아이콘·엑셀 보기가 깨진다" >&2
fi

echo "== 4. 설정 파일 (처음 설치·바뀐 배포에서 손으로 복사)"
cp "$ROOT/deploy/webwas/opt/yest/chatbot/docker-compose.prod.yml" \
   "$ROOT/deploy/webwas/opt/yest/chatbot/compose.env.example" \
   "$ROOT/deploy/webwas/opt/yest/chatbot/.env.example" \
   "$ROOT/deploy/webwas/etc/systemd/system/chatbot.service" \
   "$ROOT/deploy/webwas/etc/nginx/conf.d/chatbot.conf" \
   "$HERE/check_rocky.sh" "$STAGE/config/"
# SVN 작업 폴더가 Windows 라 CRLF 일 수 있다 — 서버에서 쓰는 텍스트 파일은 LF 로
find "$STAGE/config" -type f -exec sed -i 's/\r$//' {} +

if [ "$WITH_IMAGE" = 1 ]; then
    echo "== 5. 런타임 이미지 저장 (수 분)"
    docker save "$RUNTIME_IMAGE" | gzip -1 > "$STAGE/image/chatbot-backend-runtime_$HASH.tar.gz"
fi

echo "== 6. 버전·체크섬·묶음"
echo "$RUNTIME_IMAGE" > "$STAGE/RUNTIME_IMAGE"
{
    echo "$VER"
    echo "built=$(date '+%Y-%m-%d %H:%M:%S')"
    echo "runtime=$RUNTIME_IMAGE"
    echo "svn=$(command -v svnversion >/dev/null && svnversion "$ROOT" 2>/dev/null || echo unknown)"
} > "$STAGE/VERSION"
(cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
mkdir -p "$OUT"
tar -C "$OUT/stage" -czf "$OUT/$NAME.tar.gz" "$NAME"
(cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
sed 's/\r$//' "$HERE/deploy.sh" > "$OUT/deploy.sh" && chmod +x "$OUT/deploy.sh"
rm -rf "$OUT/stage"

echo
echo "묶음: $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1)), 이미지 포함=$WITH_IMAGE"
echo "올릴 파일 3개: $NAME.tar.gz · $NAME.tar.gz.sha256 · deploy.sh → 서버 /mnt/a/chatbot/offline/ (바이너리 모드)"
