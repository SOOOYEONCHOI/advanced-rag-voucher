#!/usr/bin/env bash
# 운영 서버 배포 파일 3개를 만든다(개발 PC) — origin/main 을 받아 소스 + 운영 서버 조건(x86_64·CPython 3.12) wheel 로 묶는다. 절차: docs/DEPLOYMENT.md §0
#   deploy/build_package.sh          → deploy/dist/ 에 maip-<커밋>.tar.gz · maip-<커밋>.tar.gz.sha256 · deploy.sh
#   deploy/build_package.sh <ref>    → origin/main 대신 그 커밋(받지 않는다 — 원격 인증 없이 로컬에 있는 커밋으로 묶는다)
# 묶음 안: maip-<커밋>/{source/, wheels/(+SHA256SUMS.txt), VERSION}. .env·저장소 데이터·배포물(zip·tar.xz)은 넣지 않는다.
# domain/management/samples(약 62MB)는 그대로 들어간다 — 고객 양식 데이터·그림(seed_dig_form, 운영)과 seed_demo 표본 fan_panel.zip(시연용, deploy.sh 는 돌리지 않는다).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

REF=${1:-}
if [ -z "$REF" ]; then
    git fetch -q origin main || { echo "origin main 을 받지 못했다(원격 인증 등). 커밋을 지정해 다시 실행한다: deploy/build_package.sh <커밋>" >&2; exit 1; }
    REF=origin/main
fi
VER=$(git rev-parse --short "$REF")
NAME=maip-$VER
PIP=${PIP:-.venv/bin/pip}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/$NAME" deploy/dist
git archive --format=tar --prefix=source/ "$REF" | tar -x -C "$WORK/$NAME"
# 개발 PC 의 pip 설정(사내·NVIDIA 보조 인덱스 등)을 읽지 않는다 — 서버 wheel 은 pypi.org 에서만 받는다. 닿지 않는 인덱스가 있으면 재시도로 멈춘다
PIP_CONFIG_FILE=/dev/null "$PIP" download -q -r "$WORK/$NAME/source/requirements.txt" -d "$WORK/$NAME/wheels" --only-binary=:all: \
    --implementation cp --python-version 3.12 --abi cp312 \
    --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64
(cd "$WORK/$NAME/wheels" && sha256sum ./*.whl > SHA256SUMS.txt)
printf '%s %s\n' "$(git rev-parse "$REF")" "$(git log -1 --format=%cd --date=iso "$REF")" > "$WORK/$NAME/VERSION"

tar -czf "deploy/dist/$NAME.tar.gz" -C "$WORK" "$NAME"
(cd deploy/dist && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
install -m 755 "$WORK/$NAME/source/deploy/deploy.sh" deploy/dist/deploy.sh   # 그 커밋의 배포 스크립트

echo "$REF → deploy/dist/ ($(du -h "deploy/dist/$NAME.tar.gz" | cut -f1))"
echo "  로컬 PC 로 받아 서버 /home/yhan/dist/ 에 바이너리 모드로 올린다(DEPLOYMENT §0):"
echo "    deploy/dist/$NAME.tar.gz  deploy/dist/$NAME.tar.gz.sha256  deploy/dist/deploy.sh"
