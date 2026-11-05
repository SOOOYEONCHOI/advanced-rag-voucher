#!/usr/bin/env bash
# 개발 PC(WSL): WAS(Rocky 9.6)용 Docker 29.9.2 RPM 을 받아 로컬 저장소로 묶는다. 처음 설치 때 한 번.
#   deploy/webwas/chatbot/download_docker_rpms.sh [출력 폴더]     (기본 deploy/webwas/mnt/a/chatbot/offline)
# 결과: docker-rocky96-x86_64_29.9.2.tar.gz · SHA256SUMS.top → 서버 /mnt/a/chatbot/offline/
# 설명: docs/design/운영배포_가이드_서버별_v1.1.md §4.2 (2026-10-28 실행 확인: RPM 37개, 93MB, 네트워크 없는 9.6 컨테이너에 설치됨)
#
# - 9.6 은 최신 부 버전이 아니라 OS 저장소를 vault 9.6 으로 고정한다(아니면 9.7+ 의존 패키지가 섞인다)
# - 받는 컨테이너에는 아무것도 먼저 설치하지 않는다 — 먼저 깔린 패키지는 받지 않아 서버에서 빠진다
# - repodata 를 만들어 서버에서 저장소로 쓴다 — 서버에 이미 있는 systemd·selinux-policy 등은 dnf 가 건너뛴다
set -euo pipefail

# 2026.10.30 수정 - 기본 출력을 서버 경로와 같은 구조로(/mnt/d/adrag-offline/web → deploy/webwas/mnt/a/chatbot/offline)
OUT=${1:-$(cd "$(dirname "$0")/.." && pwd)/mnt/a/chatbot/offline}
mkdir -p "$OUT"
VER=29.9.2
NAME=docker-rocky96-x86_64_$VER
IMG=rockylinux/rockylinux:9.6
command -v docker >/dev/null || { echo "docker 가 없습니다 — WSL 에서 실행합니다." >&2; exit 1; }

rm -rf "$OUT/docker-rpms" "$OUT/$NAME.tar.gz" "$OUT/SHA256SUMS.top"
mkdir -p "$OUT/docker-rpms"

echo "== 1. RPM 받기 (vault 9.6 + docker-ce)"
docker run --rm -e VER="$VER" -v "$OUT/docker-rpms:/out" "$IMG" bash -c '
set -euo pipefail
cat /etc/rocky-release
sed -i -e "s|^mirrorlist=|#mirrorlist=|" \
       -e "s|^#\?baseurl=http://dl.rockylinux.org/\$contentdir/\$releasever|baseurl=https://dl.rockylinux.org/vault/rocky/9.6|" \
       /etc/yum.repos.d/rocky*.repo
curl -fsSL https://download.docker.com/linux/rhel/docker-ce.repo -o /etc/yum.repos.d/docker-ce.repo
dnf clean all >/dev/null
dnf repolist -v 2>/dev/null | grep -i baseurl
# docker-ce(epoch 3)와 docker-ce-cli(epoch 1)는 epoch 가 달라 "이름-버전-*" 으로 고른다
dnf -y install --downloadonly --downloaddir=/out --setopt=install_weak_deps=False \
    "docker-ce-$VER-*" "docker-ce-cli-$VER-*" containerd.io docker-compose-plugin \
    python3-dnf-plugin-versionlock rsync acl
'

echo "== 2. 저장소 정보 (다른 컨테이너 — 같은 컨테이너에서 dnf install 하면 받은 RPM 을 지운다)"
docker run --rm -v "$OUT/docker-rpms:/out" "$IMG" bash -c \
    'dnf -y -q install createrepo_c >/dev/null && createrepo_c -q /out'

echo "== 3. 네트워크 없는 9.6 컨테이너에 설치해 본다"
docker run --rm --network none -v "$OUT/docker-rpms:/rpms:ro" "$IMG" bash -c '
set -e
dnf -y -q --disablerepo="*" --repofrompath=chatbot-local,file:///rpms --setopt=chatbot-local.gpgcheck=0 \
    install docker-ce docker-ce-cli containerd.io docker-compose-plugin python3-dnf-plugin-versionlock rsync acl >/dev/null
docker --version && docker compose version'

echo "== 4. 묶기·체크섬"
cd "$OUT"
(cd docker-rpms && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar czf "$NAME.tar.gz" docker-rpms
sha256sum "$NAME.tar.gz" > SHA256SUMS.top
echo "RPM $(ls docker-rpms/*.rpm | wc -l)개, $(du -h "$NAME.tar.gz" | cut -f1)"
echo "올릴 파일: $OUT/$NAME.tar.gz · $OUT/SHA256SUMS.top → 서버 /mnt/a/chatbot/offline/ (바이너리 모드)"
