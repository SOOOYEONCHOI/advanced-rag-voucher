#!/usr/bin/env bash
# 개발 PC(WSL): GPU 서버(Ubuntu 24.04)용 Docker 29.9.2 + NVIDIA Container Toolkit 1.20.1 .deb 를 받는다. 처음 설치 때 한 번.
# Ubuntu 24.04 컨테이너 안에서 실행한다(/out 에 .deb 가 쌓인다). 저장소 루트에서:
#   docker run --rm -v "$PWD/deploy/gpu/tools:/t:ro" -v "$HOME/adrag-offline/gpu/gpu-debs:/out" ubuntu:24.04 bash /t/download_gpu_debs.sh
#   (cd ~/adrag-offline/gpu && sha256sum gpu-debs/*.deb | sed 's#gpu-debs/##' > gpu-debs/SHA256SUMS && tar czf docker-nvidia-noble-amd64_29.9.2_1.20.1.tar.gz gpu-debs #      && sha256sum docker-nvidia-noble-amd64_29.9.2_1.20.1.tar.gz > docker-nvidia-noble-amd64_29.9.2_1.20.1.tar.gz.sha256)
#   → 두 파일을 deploy/gpu/mnt/a/chatbot/offline/ 로 옮긴다 (서버 /mnt/a/chatbot/offline/)
# 설명: docs/design/운영배포_가이드_서버별_v1.1.md §1.3 ①
# 2026.10.28 작성(scratchpad dl-gpu.sh) · 2026.10.30 저장소로 옮김
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq ca-certificates curl gnupg >/dev/null
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /etc/apt/keyrings/nvidia-ct.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-ct.gpg] https://#' > /etc/apt/sources.list.d/nvidia-ct.list
apt-get update -qq
apt-cache madison docker-ce | head -2
apt-cache madison nvidia-container-toolkit | head -3
DV=$(apt-cache madison docker-ce | awk '/29.9.2/{print $3; exit}')
NV=$(apt-cache madison nvidia-container-toolkit | awk '/1.20.1/{print $3; exit}')
echo "DV=$DV NV=$NV"
rm -f /var/cache/apt/archives/*.deb
apt-get install -y -qq --download-only --no-install-recommends \
  docker-ce=$DV docker-ce-cli=$DV containerd.io docker-compose-plugin \
  nvidia-container-toolkit=$NV nvidia-container-toolkit-base=$NV libnvidia-container-tools=$NV libnvidia-container1=$NV >/dev/null
cp /var/cache/apt/archives/*.deb /out/
ls /out; du -sh /out
