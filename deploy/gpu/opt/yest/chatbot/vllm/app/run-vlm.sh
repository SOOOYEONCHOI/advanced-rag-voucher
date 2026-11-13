#!/bin/bash
# VLM 테스트 A.X-4.0-VL-Light — GPU 1, 포트 8110
# 2026.11.05 추가 - 흐름도·도면 이미지 인식 비교 테스트용. systemd vllm@vlm.service 가 실행한다.
# 2026.11.05 수정 - 모델을 Gemma4-12B-it → A.X-4.0-VL-Light 로 변경(서버 /mnt/a/chatbot/models/vlm/ 에 반입됨)
# GPU 1 비율 합계: 임베딩 0.18 + 리랭커 0.05 + ASR 0.15 + VLM 0.35 = 0.73 (0.9 이하)
#   2026.11.10(sooyeon.choi) 수정 - TTS(0.24, V-6)는 GPU 3에 올리기로 해서(사용자 결정) 이 서비스는 1번에 그대로 둔다.
# 포트 8109는 TTS 자리라 8110을 쓴다.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${VLM_API_KEY:?env.sh에 VLM_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=1

MODEL_ROOT=/mnt/a/chatbot/models

echo "Starting A.X-4.0-VL-Light VLM server (8110)..."

# --gpu-memory-utilization 0.35 ≈ 28GB: 가중치(약 7B, bf16) 약 16GB + 이미지 처리·KV 캐시
# --max-model-len 16384: 도면 1장 + 긴 JSON 출력이면 충분. KV 캐시 부족 오류가 나면 8192로 낮춘다
exec vllm serve "${MODEL_ROOT}/vlm/A.X-4.0-VL-Light" \
  --served-model-name A.X-4.0-VL-Light \
  --host 0.0.0.0 \
  --port 8110 \
  --dtype bfloat16 \
  --max-model-len 16384 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 4096 \
  --limit-mm-per-prompt '{"image": 4}' \
  --gpu-memory-utilization 0.35 \
  --tensor-parallel-size 1 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --trust-remote-code \
  --api-key "${VLM_API_KEY}"
