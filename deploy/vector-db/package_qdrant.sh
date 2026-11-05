#!/usr/bin/env bash
# 개발 PC(WSL): Vector DB 서버용 Qdrant 배포 묶음(공식 이미지 + compose + 서비스)을 만든다.
#   deploy/vector-db/package_qdrant.sh [--without-image] [출력 폴더]     (기본 deploy/vector-db/mnt/a/chatbot/offline)
# --without-image : 서버에 qdrant/qdrant:v1.18.2 가 이미 있으면 이미지를 넣지 않는다(설정만, 수 KB)
# 결과: qdrant-chatbot-1.18.2.tar.gz · SHA256SUMS.top → yest-vector-db /mnt/a/chatbot/offline/
# 설명: docs/design/운영배포_가이드_서버별_v1.1.md §2.2
set -euo pipefail

IMG=qdrant/qdrant:v1.18.2
WITH_IMAGE=1
OUT=
for a in "$@"; do
    case "$a" in
        --without-image) WITH_IMAGE=0 ;;
        -*) echo "모르는 옵션: $a" >&2; exit 1 ;;
        *) OUT=$a ;;
    esac
done
HERE=$(cd "$(dirname "$0")" && pwd)
# 2026.10.30 수정 - 기본 출력을 서버 경로와 같은 구조로(/mnt/d/adrag-offline/vector → deploy/vector-db/mnt/a/chatbot/offline)
OUT=${OUT:-$HERE/mnt/a/chatbot/offline}
NAME=qdrant-chatbot-1.18.2
STAGE=$OUT/stage/$NAME

rm -rf "$OUT/stage" "$OUT/$NAME.tar.gz" "$OUT/SHA256SUMS.top"
mkdir -p "$STAGE/config" "$STAGE/image"

echo "== 1. 이미지 $IMG"
docker image inspect "$IMG" >/dev/null 2>&1 || docker pull "$IMG"
docker image inspect "$IMG" --format 'arch={{.Architecture}} id={{.Id}}'

echo "== 2. 비root·통계 끔·네트워크 없이 띄워 본다"
T=$(mktemp -d)
mkdir -p "$T/storage" "$T/snapshots" && chmod 777 "$T/storage" "$T/snapshots"
docker rm -f qdrant-pkgtest >/dev/null 2>&1 || true
docker run -d --name qdrant-pkgtest --network none --user 1999:1999 \
    -e QDRANT__TELEMETRY_DISABLED=true -v "$T/storage:/qdrant/storage" -v "$T/snapshots:/qdrant/snapshots" "$IMG" >/dev/null
ok=0
for _ in $(seq 1 20); do
    sleep 1
    if docker logs qdrant-pkgtest 2>&1 | grep -q 'HTTP listening on 6333'; then ok=1; break; fi
done
docker logs qdrant-pkgtest 2>&1 | grep -iE 'telemetry|listening|panic|denied' | head -5
docker rm -f qdrant-pkgtest >/dev/null
docker run --rm -v "$T:/t" alpine:3.20 rm -rf /t/storage /t/snapshots >/dev/null 2>&1 || true
rm -rf "$T"
[ "$ok" = 1 ] || { echo "!! 기동 확인 실패 — 반출 중지" >&2; exit 1; }

echo "== 3. 설정 파일"
cp "$HERE/opt/yest/chatbot/qdrant/docker-compose.yml" "$HERE/opt/yest/chatbot/qdrant/compose.env.example" \
   "$HERE/etc/systemd/system/qdrant.service" "$STAGE/config/"
find "$STAGE/config" -type f -exec sed -i 's/\r$//' {} +

if [ "$WITH_IMAGE" = 1 ]; then
    echo "== 4. 이미지 저장"
    docker save "$IMG" | gzip -1 > "$STAGE/image/qdrant_v1.18.2.tar.gz"
fi

echo "== 5. 체크섬·묶기"
(cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
(cd "$OUT/stage" && tar czf "$OUT/$NAME.tar.gz" "$NAME")
(cd "$OUT" && sha256sum "$NAME.tar.gz" > SHA256SUMS.top)
rm -rf "$OUT/stage"
ls -l "$OUT"
echo "올릴 파일: $OUT/$NAME.tar.gz · $OUT/SHA256SUMS.top → yest-vector-db /mnt/a/chatbot/offline/ (바이너리 모드), 이미지 포함=$WITH_IMAGE"
