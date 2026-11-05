#!/bin/bash
# ASR Qwen3-ASR-1.7B — GPU 1, 포트 8107 (개발 run_qwen3_ASR.sh 기준)
# systemd vllm@asr.service 가 실행한다.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${VOICE_ASR_API_KEY:?env.sh에 VOICE_ASR_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=1

MODEL_ROOT=/mnt/a/chatbot/models   # 2026.10.30 수정 - 서버 실제 위치(gen/embedding/reranker 구조)

echo "Starting Qwen3-ASR-1.7B server (8107)..."

exec vllm serve "${MODEL_ROOT}/gen/Qwen3-ASR-1.7B" \
  --served-model-name Qwen3-ASR-1.7B \
  --host 0.0.0.0 \
  --port 8107 \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.15 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --api-key "${VOICE_ASR_API_KEY}"
