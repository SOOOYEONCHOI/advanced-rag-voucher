#!/bin/bash
# VLM 테스트 Gemma4-12B-it — GPU 1, 포트 8110 (개발 run_gemma4_12b_tp2.sh 기준, 운영은 1장·TP 1)
# 2026.11.05 추가 - 흐름도·도면 이미지 인식 비교 테스트용. systemd vllm@vlm.service 가 실행한다.
# GPU 1 비율 합계: 임베딩 0.18 + 리랭커 0.05 + ASR 0.15 + VLM 0.45 = 0.83 (0.9 이하)
#   TTS(0.24, V-6)를 1번에 올리면 합계가 넘는다 → 그때는 이 서비스를 GPU 2로 옮기거나 멈춘다.
# 포트 8109는 TTS 자리라 8110을 쓴다.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${VLM_API_KEY:?env.sh에 VLM_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=1

MODEL_ROOT=/mnt/a/chatbot/models

echo "Starting Gemma4-12B-it VLM server (8110)..."

# --gpu-memory-utilization 0.45 ≈ 36GB: 가중치(bf16) 약 24GB + 이미지 처리·KV 캐시
# --max-model-len: 개발 32768 → 16384 (1장 36GB 안에서 KV 캐시 확보. 도면 1장 + 긴 JSON 출력이면 충분)
exec vllm serve "${MODEL_ROOT}/gen/gemma-4-12B-it" \
  --served-model-name gemma-4-12B-it \
  --host 0.0.0.0 \
  --port 8110 \
  --dtype bfloat16 \
  --max-model-len 16384 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 4096 \
  --limit-mm-per-prompt '{"image": 4}' \
  --gpu-memory-utilization 0.45 \
  --kv-cache-dtype fp8 \
  --tensor-parallel-size 1 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --trust-remote-code \
  --api-key "${VLM_API_KEY}"
