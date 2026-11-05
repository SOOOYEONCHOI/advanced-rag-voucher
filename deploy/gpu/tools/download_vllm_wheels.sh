#!/usr/bin/env bash
# 개발 PC(WSL): GPU 서버용 vLLM 0.30.0(+audio) wheel 을 받아 폐쇄망 설치를 시험하고 tar 로 묶는다.
# Ubuntu 24.04 컨테이너 안에서 실행한다(/work 작업, /out 결과). 저장소 루트에서:
#   docker run --rm -v "$PWD/deploy/gpu/tools:/t:ro" -v "$PWD/deploy/gpu/mnt/a/chatbot/offline/vllm:/out" ubuntu:24.04 bash /t/download_vllm_wheels.sh
#   → /out(= deploy/gpu/mnt/a/chatbot/offline/vllm/) 에 vllm-wheels_0.30.0.tar · .sha256 (서버 /mnt/a/chatbot/offline/vllm/)
# 설명: docs/design/운영배포_가이드_서버별_v1.1.md §1.3 ②
# 2026.10.28 작성(scratchpad dl-vllm.sh, 실행 확인: wheel 205개 3.96GB) · 2026.10.30 저장소로 옮김
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq python3.12 python3.12-venv >/dev/null
python3.12 --version
W=/work/vllm-wheels
mkdir -p $W
python3.12 -m venv /v && /v/bin/pip install -q -U pip
/v/bin/pip download -q -d $W pip setuptools wheel
/v/bin/pip download -d $W "vllm[audio]==0.30.0"
echo "== 받은 파일 수: $(ls $W | wc -l), 크기: $(du -sh $W | cut -f1)"
# sdist(.tar.gz/.zip)가 섞여 있으면 서버에서 빌드가 필요하므로 표시
ls $W | grep -vE '\.whl$' || echo "== wheel 외 파일 없음"

# 받은 파일만으로 설치되는지 확인 (폐쇄망과 같은 조건)
python3.12 -m venv /t
/t/bin/pip install -q --no-index --find-links $W -U pip setuptools wheel
/t/bin/pip install -q --no-index --find-links $W "vllm[audio]==0.30.0"
# vllm --version 은 GPU 장치를 찾다가 실패하므로(컨테이너에 GPU 없음) 패키지 정보로 확인
/t/bin/pip show vllm | head -2
/t/bin/python -c "import torch;print('torch', torch.__version__, 'cuda', torch.version.cuda)"
/t/bin/pip check || true
/t/bin/pip freeze > $W/pip-freeze.txt

(cd $W && sha256sum * > SHA256SUMS)
tar cf /out/vllm-wheels_0.30.0.tar -C /work vllm-wheels
(cd /out && sha256sum vllm-wheels_0.30.0.tar > vllm-wheels_0.30.0.tar.sha256)
ls -la /out/vllm-wheels_0.30.0.tar*
